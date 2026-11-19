from pathlib import Path
import math
import cv2
import mediapipe as mp

EDGES = [(11,12),(11,23),(12,24),(23,24),(11,13),(13,15),(12,14),(14,16),
         (23,25),(25,27),(24,26),(26,28),(27,31),(28,32)]


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
        self.locked = False

    def process(self, frame, timestamp):
        ms = round(timestamp*1000)
        if ms <= self.last_ms:
            raise ValueError("Pose timestamps must increase by at least one millisecond")
        self.last_ms = ms
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
        poses = result.pose_landmarks
        if len(poses) > 1:
            # Select only when exactly one pose matches the already locked location.
            # A single ambiguous frame cannot permanently poison the remaining video.
            if self.center is None:
                return None, "MULTIPLE_PEOPLE_RESET_REQUIRED"
            candidates = []
            for p in poses:
                hip=((p[23].x+p[24].x)/2,(p[23].y+p[24].y)/2)
                shoulder=((p[11].x+p[12].x)/2,(p[11].y+p[12].y)/2)
                scale=max(math.dist(hip,shoulder),self.c.min_torso)
                if math.dist(hip,self.center)/scale < self.c.identity_match_radius:
                    candidates.append(p)
            if len(candidates)==1:
                poses=candidates
            else:
                if self.last_seen is not None and timestamp-self.last_seen > self.c.identity_loss_s:
                    self.locked=True
                return None, "MULTIPLE_PEOPLE_RESET_REQUIRED"
        if not poses:
            if self.last_seen is not None and timestamp-self.last_seen > self.c.identity_loss_s:
                self.locked = True
            return None, "PERSON_NOT_DETECTED" if not self.locked else "IDENTITY_RESET_REQUIRED"
        pose = [[p.x, p.y, p.z, min(p.visibility or 0, p.presence or 0)] for p in poses[0]]
        center = ((pose[23][0]+pose[24][0])/2, (pose[23][1]+pose[24][1])/2)
        torso = max(math.dist(center, ((pose[11][0]+pose[12][0])/2, (pose[11][1]+pose[12][1])/2)), .04)
        if self.center is not None and math.dist(center, self.center)/torso > self.c.identity_max_jump:
            self.locked = True
        if self.locked:
            return None, "IDENTITY_RESET_REQUIRED"
        self.center, self.last_seen = center, timestamp
        return pose, "LOW_CONFIDENCE"

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
