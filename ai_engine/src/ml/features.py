"""Canonical 21-dimensional Spatio-Temporal Kinematic Feature Vector.

Shared verbatim between offline dataset extraction and online real-time Engine
inference to guarantee zero train/serve feature skew.
"""
import math
import numpy as np

FEATURE_NAMES = [
    "lean",
    "z_lean_3d",
    "lean_max",
    "angle_delta",
    "angle_speed",
    "aspect",
    "aspect_min",
    "aspect_ratio_change",
    "hip_y",
    "hip_drop",
    "hip_down_speed",
    "hip_down_accel",
    "head_y",
    "head_below_hip",
    "head_drop",
    "head_down_speed",
    "body_height_ratio",
    "knee_angle",
    "hip_angle",
    "leg_vertical",
    "motion_energy",
    "post_drop_speed",
    "prior_upright_ratio",
    "occlusion_ratio",
    "is_core_only",
]


def _safe(value, lo=-1e4, hi=1e4):
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return float(max(lo, min(hi, float(value))))


def build_feature_dict(features, motion):
    """Build named dict of spatio-temporal kinematic features for one valid sample."""
    if features is None or motion is None:
        return None
    is_core = 1.0 if features.coverage == "CORE_ONLY" else 0.0
    return {
        "lean": _safe(features.lean, 0.0, 90.0),
        "z_lean_3d": _safe(features.z_lean_3d, 0.0, 90.0),
        "lean_max": _safe(motion.lean_max, 0.0, 90.0),
        "angle_delta": _safe(motion.angle_delta, -90.0, 90.0),
        "angle_speed": _safe(motion.angle_speed, -500.0, 500.0),
        "aspect": _safe(features.aspect, 0.0, 10.0),
        "aspect_min": _safe(motion.aspect_min, 0.0, 10.0),
        "aspect_ratio_change": _safe(motion.aspect_ratio_change, 0.0, 5.0),
        "hip_y": _safe(features.hip_y, -0.5, 1.5),
        "hip_drop": _safe(motion.hip_drop, -5.0, 10.0),
        "hip_down_speed": _safe(motion.hip_down_speed, -20.0, 30.0),
        "hip_down_accel": _safe(motion.hip_down_accel, -100.0, 150.0),
        "head_y": _safe(features.head_y, -0.5, 1.5),
        "head_below_hip": _safe(features.head_below_hip, -5.0, 5.0),
        "head_drop": _safe(motion.head_drop, -5.0, 10.0),
        "head_down_speed": _safe(motion.head_down_speed, -20.0, 30.0),
        "body_height_ratio": _safe(motion.height_ratio, 0.0, 5.0),
        "knee_angle": _safe(features.knee, 0.0, 180.0),
        "hip_angle": _safe(features.hip_angle, 0.0, 180.0),
        "leg_vertical": _safe(features.leg_vertical, 0.0, 5.0),
        "motion_energy": _safe(motion.motion_energy, 0.0, 30.0),
        "post_drop_speed": _safe(motion.post_drop_speed, 0.0, 30.0),
        "prior_upright_ratio": _safe(motion.prior_upright_ratio, 0.0, 1.0),
        "occlusion_ratio": _safe(motion.occlusion_ratio, 0.0, 1.0),
        "is_core_only": is_core,
    }


def build_feature_vector(features, motion):
    """Return 1D float32 numpy array ordered strictly by FEATURE_NAMES."""
    row = build_feature_dict(features, motion)
    if row is None:
        return None
    return np.array([row[name] for name in FEATURE_NAMES], dtype=np.float32)
