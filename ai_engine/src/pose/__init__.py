from pathlib import Path
import math
import cv2
import mediapipe as mp

EDGES = [(11,12),(11,23),(12,24),(23,24),(11,13),(13,15),(12,14),(14,16),
         (23,25),(25,27),(24,26),(26,28),(27,31),(28,32)]


class LandmarkSmoother:
    """Adaptive exponential moving average (EMA) filter to reduce pose landmark jitter."""
    def __init__(self, tau_s=0.06, max_dt_s=0.25):
        self.tau_s = tau_s
        self.max_dt_s = max_dt_s
        self.reset()

    def reset(self):
        self.prev = None
        self.last_t = None

    def update(self, pose, t):
        if pose is None or self.tau_s <= 0:
            if pose is None:
                self.reset()
            return pose
        if self.prev is None or self.last_t is None or t - self.last_t > self.max_dt_s or t <= self.last_t:
            self.prev = [list(p) for p in pose]
            self.last_t = t
            return [list(p) for p in pose]
        dt = t - self.last_t
        alpha = 1.0 - math.exp(-dt / self.tau_s)
        smoothed = []
        for cur, old in zip(pose, self.prev):
            if cur[3] < 0.3 or old[3] < 0.3:
                smoothed.append(list(cur))
            else:
                smoothed.append([
                    old[0] + alpha * (cur[0] - old[0]),
                    old[1] + alpha * (cur[1] - old[1]),
                    old[2] + alpha * (cur[2] - old[2]),
                    cur[3],
                ])
        self.prev = smoothed
        self.last_t = t
        return [list(p) for p in smoothed]


class PoseTracker:
    def __init__(self, model, config):
        self.c = config
        if not Path(model).is_file():
            raise FileNotFoundError(f"Pose model missing: {model}; run scripts/setup.ps1")
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(Path(model).resolve())),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=2, min_pose_detection_confidence=.5, min_pose_presence_confidence=.5,
            min_tracking_confidence=.5)
        self.detector = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self.last_ms = -1
        self.reset_identity()

    def reset_identity(self):
        self.center = self.last_seen = None
        self.torso_scale = None
        self.locked = False
        self.last_world_landmarks = None
        self.last_people_count = 0
        tau = getattr(self.c, 'landmark_smooth_tau_s', 0.0)
        self.smoother = LandmarkSmoother(tau) if tau > 0 else None

    def process(self, frame, timestamp):
        ms = round(timestamp*1000)
        if ms <= self.last_ms:
            raise ValueError("Pose timestamps must increase by at least one millisecond")
        self.last_ms = ms
        self.last_world_landmarks = None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
        poses = result.pose_landmarks
        self.last_people_count = len(poses)
        world_poses = getattr(result, 'pose_world_landmarks', None) or []
        selected_idx = 0
        auto_reacquire = getattr(self.c, 'auto_reacquire', False)
        if len(poses) > 1:
            # Select only when exactly one pose matches the already locked location.
            # A single ambiguous frame cannot permanently poison the remaining video.
            if self.center is None:
                return None, "MULTIPLE_PEOPLE_RESET_REQUIRED"
            candidates = []
            for idx, p in enumerate(poses):
                hip=((p[23].x+p[24].x)/2,(p[23].y+p[24].y)/2)
                shoulder=((p[11].x+p[12].x)/2,(p[11].y+p[12].y)/2)
                scale=max(math.dist(hip,shoulder),self.c.min_torso)
                dist_ratio = math.dist(hip,self.center)/scale
                scale_ok = True if self.torso_scale is None else 0.5 <= (scale / self.torso_scale) <= 2.0
                if dist_ratio < self.c.identity_match_radius and scale_ok:
                    candidates.append((idx, p))
            if len(candidates)==1:
                selected_idx, poses = candidates[0][0], [candidates[0][1]]
            else:
                if self.last_seen is not None and timestamp-self.last_seen > self.c.identity_loss_s:
                    if auto_reacquire:
                        self.center = None
                        self.torso_scale = None
                    else:
                        self.locked=True
                return None, "MULTIPLE_PEOPLE_WAITING" if auto_reacquire else "MULTIPLE_PEOPLE_RESET_REQUIRED"
        if not poses:
            if self.last_seen is not None and timestamp-self.last_seen > self.c.identity_loss_s:
                if auto_reacquire:
                    self.center = None
                    self.torso_scale = None
                else:
                    self.locked = True
            return None, "PERSON_NOT_DETECTED" if not self.locked else "IDENTITY_RESET_REQUIRED"
        pose = [[p.x, p.y, p.z, min(p.visibility or 0, p.presence or 0)] for p in poses[0]]
        if selected_idx < len(world_poses):
            self.last_world_landmarks = [
                [p.x, p.y, p.z, min(p.visibility or 0, p.presence or 0)] for p in world_poses[selected_idx]
            ]
        center = ((pose[23][0]+pose[24][0])/2, (pose[23][1]+pose[24][1])/2)
        torso = max(math.dist(center, ((pose[11][0]+pose[12][0])/2, (pose[11][1]+pose[12][1])/2)), .04)
        reacquired = False
        if self.center is not None and math.dist(center, self.center)/torso > self.c.identity_max_jump:
            if auto_reacquire:
                reacquired = True
            else:
                self.locked = True
        if self.locked:
            return None, "IDENTITY_RESET_REQUIRED"
        if auto_reacquire and self.center is None and self.last_seen is not None and (timestamp - self.last_seen) > self.c.identity_loss_s:
            reacquired = True
        self.center, self.last_seen, self.torso_scale = center, timestamp, torso
        if getattr(self, 'smoother', None) is not None:
            if reacquired:
                self.smoother.reset()
            pose = self.smoother.update(pose, timestamp)
        return pose, "REACQUIRED" if reacquired else "LOW_CONFIDENCE"

    def draw(self, frame, pose):
        if pose is None:
            return
        h, w = frame.shape[:2]
        for a, b in EDGES:
            if min(pose[a][3], pose[b][3]) >= self.c.visibility:
                pa = (int(pose[a][0]*w), int(pose[a][1]*h))
                pb = (int(pose[b][0]*w), int(pose[b][1]*h))
                cv2.line(frame, pa, pb, (80,220,160), 2)
                cv2.circle(frame, pa, 4, (255,190,50), -1)

    def close(self):
        self.detector.close()
