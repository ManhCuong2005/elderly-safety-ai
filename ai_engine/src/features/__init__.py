"""Image-space geometry. Values are not physical heights or velocities."""
from dataclasses import dataclass
import math
import numpy as np


def angle(a, b, c):
    u, v = np.asarray(a, dtype=float) - b, np.asarray(c, dtype=float) - b
    denominator = np.linalg.norm(u) * np.linalg.norm(v)
    if not math.isfinite(denominator) or denominator < 1e-9:
        return None
    return float(np.degrees(np.arccos(np.clip(np.dot(u, v) / denominator, -1, 1))))


@dataclass(frozen=True)
class Features:
    hip_x: float
    hip_y: float
    torso: float
    lean: float
    knee: float
    hip_angle: float
    aspect: float
    leg_vertical: float
    ankle_delta: float
    points: tuple
    confidence: float = 1.0
    both_legs_visible: bool = True
    coverage: str = 'FULL'
    body_height: float = 0.0
    body_width: float = 0.0
    thigh_vertical: float = 0.0
    head_y: float = 0.0
    shoulder_y: float = 0.0
    head_below_hip: float = 0.0
    z_lean_3d: float = 0.0
    head_droop: float = -0.35
    torso_inverted: bool = False


def _head_metrics(data, xy, shoulder, torso):
    """Return (head_y, head_droop) using real distinct head landmarks when present."""
    head_ids = [i for i in (0, 2, 5, 7, 8) if data[i, 3] >= 0.4]
    if head_ids:
        pts = xy[head_ids]
        spread = float(np.max(np.ptp(pts, axis=0))) if len(head_ids) > 1 else 0.0
        # Guard against degenerate synthetic arrays (all identical coords, or dummy points far from nose).
        if len(head_ids) > 1 and spread < 1e-4:
            return float(np.mean(pts[:, 1])), -0.35
        if 0 in head_ids and spread > 0.6 * max(torso, 1e-4):
            head_y = float(xy[0, 1])
        else:
            head_y = float(np.mean(pts[:, 1]))
        droop = float((head_y - shoulder[1]) / max(torso, 1e-4))
        return head_y, droop
    return float(shoulder[1]), -0.35


def _lean_3d(world_landmarks, fallback_lean):
    """Compute 3D torso lean angle (degrees from vertical Y axis) using MediaPipe world landmarks."""
    if world_landmarks is None or len(world_landmarks) != 33:
        return float(fallback_lean)
    w = np.asarray(world_landmarks, dtype=float)
    if w.shape != (33, 4) or not np.isfinite(w).all():
        return float(fallback_lean)
    if np.min(w[[11, 12, 23, 24], 3]) < 0.4:
        return float(fallback_lean)
    shoulder = (w[11, :3] + w[12, :3]) / 2.0
    hip = (w[23, :3] + w[24, :3]) / 2.0
    vec = shoulder - hip
    horiz = math.hypot(float(vec[0]), float(vec[2]))
    vert = abs(float(vec[1]))
    if horiz < 1e-6 and vert < 1e-6:
        return float(fallback_lean)
    return float(math.degrees(math.atan2(horiz, vert)))


def extract(landmarks, width, height, config, world_landmarks=None):
    if width <= 0 or height <= 0 or landmarks is None or len(landmarks) != 33:
        return None
    data = np.asarray(landmarks, dtype=float)
    if data.shape != (33, 4) or not np.isfinite(data).all():
        return None
    core = [11, 12, 23, 24]
    legs = [(11,23,25,27), (12,24,26,28)]
    trusted = [leg for leg in legs if np.min(data[list(leg),3]) >= config.visibility]
    if np.min(data[core, 3]) < config.visibility or not trusted:
        return None
    ids = sorted(set(core + [i for leg in trusted for i in leg]))
    if np.any(data[ids,:2] < -.05) or np.any(data[ids,:2] > 1.05):
        return None
    xy = data[:, :2].copy()
    xy[:, 0] *= width / height  # both axes now in image-height units
    shoulder = (xy[11] + xy[12]) / 2
    hip = (xy[23] + xy[24]) / 2
    knee_mid = np.mean([xy[leg[2]] for leg in trusted],axis=0)
    ankle_mid = np.mean([xy[leg[3]] for leg in trusted],axis=0)
    torso = float(np.linalg.norm(shoulder - hip))
    if torso < config.min_torso:
        return None
    knees = [angle(xy[h], xy[k], xy[a]) for s,h,k,a in trusted]
    hips = [angle(xy[s], xy[h], xy[k]) for s,h,k,a in trusted]
    if any(a is None for a in knees + hips):
        return None
    body = xy[ids]
    extent = np.ptp(body, axis=0)
    lean = math.degrees(math.atan2(abs(shoulder[0]-hip[0]), abs(shoulder[1]-hip[1])))
    head_y, head_droop = _head_metrics(data, xy, shoulder, torso)
    lean_3d = _lean_3d(world_landmarks, lean)
    torso_inv = bool(shoulder[1] >= hip[1] + 0.05 * torso)
    return Features(float(hip[0]), float(hip[1]), torso, lean,
                    float(np.mean(knees)), float(np.mean(hips)),
                    float(extent[1] / max(extent[0], 1e-6)),
                    float(abs(ankle_mid[1]-hip[1]) / torso),
                    float((xy[27, 0]-xy[28, 0]) / torso) if len(trusted)==2 else 0.0,
                    tuple(map(tuple, xy[core])), float(np.min(data[ids, 3])),len(trusted)==2,
                    'FULL' if len(trusted)==2 else 'ONE_LEG',float(extent[1]),float(extent[0]),
                    float((knee_mid[1]-hip[1])/torso),
                    head_y, float(shoulder[1]), float((head_y - hip[1]) / torso), lean_3d,
                    head_droop, torso_inv)


def extract_core(landmarks, width, height, config, world_landmarks=None):
    """High-confidence visible torso only; never invent leg angles or a posture label."""
    if landmarks is None or width<=0 or height<=0:
        return None
    data=np.asarray(landmarks,dtype=float)
    if data.shape!=(33,4) or not np.isfinite(data).all():
        return None
    core=[11,12,23,24]
    if np.min(data[core,3]) < config.core_visibility:
        return None
    if np.any(data[core,:2] < 0) or np.any(data[core,:2] > 1):
        return None
    xy=data[:,:2].copy();xy[:,0]*=width/height
    shoulder=(xy[11]+xy[12])/2;hip=(xy[23]+xy[24])/2
    torso=float(np.linalg.norm(shoulder-hip))
    if torso<config.min_torso:return None
    extent=np.ptp(xy[core],axis=0)
    lean=math.degrees(math.atan2(abs(shoulder[0]-hip[0]),abs(shoulder[1]-hip[1])))
    head_y, head_droop = _head_metrics(data, xy, shoulder, torso)
    lean_3d = _lean_3d(world_landmarks, lean)
    torso_inv = bool(shoulder[1] >= hip[1] + 0.05 * torso)
    return Features(float(hip[0]),float(hip[1]),torso,lean,0,0,
                    float(extent[1]/max(extent[0],1e-6)),0,0,tuple(map(tuple,xy[core])),
                    float(np.min(data[core,3])),False,'CORE_ONLY',float(extent[1]),float(extent[0]),
                    0.0, head_y, float(shoulder[1]), float((head_y - hip[1]) / torso), lean_3d,
                    head_droop, torso_inv)
