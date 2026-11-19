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

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid positive threshold: {field.name}")
        if self.visibility > 1 or self.core_visibility>1 or self.verification_timeout_s < self.verification_s:
            raise ValueError("Invalid visibility or verification window")
        if self.window_s < self.transition_s:
            raise ValueError("Window must cover transition")

    @classmethod
    def load(cls, path=None):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8"))) if path else cls()

    def demo(self):
        return replace(self, lying_long_s=15.0, inactivity_s=20.0, cooldown_s=10.0)
