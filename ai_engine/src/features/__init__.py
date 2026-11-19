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


def extract(landmarks, width, height, config):
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
    return Features(float(hip[0]), float(hip[1]), torso, lean,
                    float(np.mean(knees)), float(np.mean(hips)),
                    float(extent[1] / max(extent[0], 1e-6)),
                    float(abs(ankle_mid[1]-hip[1]) / torso),
                    float((xy[27, 0]-xy[28, 0]) / torso) if len(trusted)==2 else 0.0,
                    tuple(map(tuple, xy[core])), float(np.min(data[ids, 3])),len(trusted)==2,
                    'FULL' if len(trusted)==2 else 'ONE_LEG',float(extent[1]),float(extent[0]),
                    float((knee_mid[1]-hip[1])/torso))


def extract_core(landmarks, width, height, config):
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
    return Features(float(hip[0]),float(hip[1]),torso,lean,0,0,
                    float(extent[1]/max(extent[0],1e-6)),0,0,tuple(map(tuple,xy[core])),
                    float(np.min(data[core,3])),False,'CORE_ONLY',float(extent[1]),float(extent[0]))
