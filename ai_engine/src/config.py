from dataclasses import dataclass, fields, replace
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Config:
    visibility: float = 0.6
    min_torso: float = 0.04
    core_visibility: float = 0.85
    core_fall_lean: float = 65.0
    core_fall_aspect: float = 1.0
    standing_lean: float = 32.0
    standing_knee: float = 150.0
    standing_leg_vertical: float = 1.4
    standing_thigh_vertical: float = 0.5
    standing_hip: float = 145.0
    sitting_knee: float = 135.0
    sitting_hip: float = 140.0
    lying_lean: float = 62.0
    lying_aspect: float = 1.35
    lying_leg_vertical: float = 0.55
    posture_debounce_s: float = 0.25
    smoothing_tau_s: float = 0.12
    window_s: float = 2.5
    max_gap_s: float = 0.5
    motion_speed_window_s: float = 0.3
    transition_s: float = 1.2
    prior_support_s: float = 0.08
    fall_angle_delta: float = 38.0
    fall_angle_speed: float = 45.0
    fall_hip_drop: float = 0.5
    fall_hip_speed: float = 0.65
    fall_height_ratio: float = 0.6
    fall_foreshortening_angle_delta: float = 15.0
    collapsed_body_aspect: float = 1.35
    collapsed_body_leg_vertical: float = 0.9
    verification_s: float = 1.0
    verification_timeout_s: float = 5.0
    immobile_speed: float = 0.3
    cooldown_s: float = 30.0
    cancel_cooldown_s: float = 1.5
    lying_long_s: float = 1800.0
    inactivity_s: float = 600.0
    walking_window_s: float = 1.5
    walking_ankle_range: float = 0.25
    walking_min_speed: float = 0.15
    heartbeat_s: float = 30.0
    status_min_interval_s: float = 5.0
    identity_max_jump: float = 2.0
    identity_match_radius: float = 0.6
    identity_loss_s: float = 3.0
    # V2 ML, occlusion grace period, bending ADL, filtering, and auto re-acquisition
    grace_period_s: float = 0.0
    auto_reacquire: bool = False
    enable_bending: bool = False
    bending_lean_min: float = 32.0
    bending_lean_max: float = 78.0
    bending_hip_max: float = 128.0
    bending_knee_min: float = 125.0
    bending_leg_vertical_min: float = 0.65
    landmark_smooth_tau_s: float = 0.0
    ml_model_path: str = ""
    ml_fall_threshold: float = 0.55
    ml_min_consecutive: int = 2
    stumble_risk_threshold: float = 0.35
    # Post-fall convulsion / thrashing detection (limb oscillation while grounded)
    enable_convulsion: bool = True
    convulsion_window_s: float = 2.0
    convulsion_min_hz: float = 2.0
    convulsion_max_hz: float = 9.0
    convulsion_amp: float = 0.12
    convulsion_max_drift: float = 1.2
    convulsion_sustain_s: float = 1.0
    # Floor entrapment: still on the floor (even if moving/jittering) this long without rising -> alert
    entrapment_s: float = 5.0
    # Safety lock: an ALERT only auto-clears after an uninterrupted observed upright hold
    recovery_hold_s: float = 3.0
    # Believe the person is still on the floor for this long after the last floor observation
    occlusion_hold_s: float = 2.0
    # Max time a VERIFYING candidate is kept alive while helpers occlude the camera
    assist_hold_s: float = 20.0
    # Stroke slump / slow wall-slide collapse detection (no rapid fall required)
    enable_slump_detection: bool = True
    slump_head_droop: float = -0.12
    slump_lean_3d: float = 34.0
    slump_alert_s: float = 3.5
    slump_prior_window_s: float = 30.0

    def __post_init__(self):
        bool_fields = {"auto_reacquire", "enable_bending", "enable_convulsion", "enable_slump_detection"}
        str_fields = {"ml_model_path"}
        non_neg_fields = {"grace_period_s", "landmark_smooth_tau_s"}
        signed_fields = {"slump_head_droop"}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in bool_fields:
                if not isinstance(value, bool):
                    raise ValueError(f"Invalid boolean flag: {field.name}")
                continue
            if field.name in str_fields:
                if not isinstance(value, str):
                    raise ValueError(f"Invalid string path: {field.name}")
                continue
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f"Invalid positive threshold: {field.name}")
            if field.name in signed_fields:
                continue
            if field.name in non_neg_fields:
                if value < 0:
                    raise ValueError(f"Invalid non-negative threshold: {field.name}")
            elif value <= 0:
                raise ValueError(f"Invalid positive threshold: {field.name}")
        if self.visibility > 1 or self.core_visibility > 1 or self.verification_timeout_s < self.verification_s:
            raise ValueError("Invalid visibility or verification window")
        if self.ml_fall_threshold > 1 or self.stumble_risk_threshold > 1:
            raise ValueError("ML probability thresholds must be in (0, 1]")
        if self.window_s < self.transition_s:
            raise ValueError("Window must cover transition")

    @classmethod
    def load(cls, path=None):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8"))) if path else cls()

    def demo(self):
        return replace(self, lying_long_s=15.0, inactivity_s=20.0, cooldown_s=10.0)
