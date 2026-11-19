from collections import deque
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Motion:
    speed: float = 0.0
    hip_down_speed: float = 0.0
    angle_speed: float = 0.0
    hip_drop: float = 0.0
    angle_delta: float = 0.0
    prior_upright: bool = False
    walking: bool = False
    duration: float = 0.0
    height_ratio: float = 1.0


class MotionWindow:
    def __init__(self, config):
        self.c = config
        self.samples = deque()

    def reset(self):
        self.samples.clear()

    def update(self, t, f, posture):
        if self.samples and t <= self.samples[-1][0]:
            raise ValueError("Timestamps must strictly increase")
        if self.samples and t-self.samples[-1][0] > self.c.max_gap_s:
            self.reset()
        self.samples.append((t, f, posture))
        while self.samples and t-self.samples[0][0] > self.c.window_s:
            self.samples.popleft()
        # Bound memory even for malformed high-frequency streams.
        while len(self.samples) > 1000:
            self.samples.popleft()
        if len(self.samples) < 2:
            return Motion()
        # Net motion over a short real-time interval reduces frame-to-frame pose jitter.
        # Rapid fall signals below still use raw upright references, not this averaging.
        anchor = min(list(self.samples)[:-1], key=lambda item: abs((t-item[0])-self.c.motion_speed_window_s))
        pt, pf, _ = anchor
        dt = t-pt
        scale = max(pf.torso, self.c.min_torso)
        speed = float(np.mean(np.linalg.norm(np.array(f.points)-np.array(pf.points), axis=1)) / scale / dt)
        recent = [(st, sf, sp) for st, sf, sp in self.samples if t-st <= self.c.transition_s]
        upright = [(st, sf, sp) for st, sf, sp in recent[:-1] if sp in ("STANDING", "SITTING")]
        delta = drop = 0.0
        height_ratio=1.0
        angle_speed = hip_speed = 0.0
        if upright:
            # Compare displacement and speed against the SAME upright reference.
            candidates = []
            for st, sf, _ in upright:
                d = (f.hip_y-sf.hip_y)/max(sf.torso, self.c.min_torso)
                a = f.lean-sf.lean
                elapsed = t-st
                ratio=f.body_height/max(sf.body_height,1e-6) if f.coverage==sf.coverage and f.coverage!='CORE_ONLY' else 1.0
                candidates.append((d, a, d/elapsed, a/elapsed,ratio))
            drop, delta, hip_speed, angle_speed,height_ratio = max(candidates, key=lambda x: x[0])
        walking_samples = [(st, sf) for st, sf, sp in self.samples if t-st <= self.c.walking_window_s and sp == "STANDING" and sf.both_legs_visible]
        walking = False
        if len(walking_samples) >= 8 and walking_samples[-1][0]-walking_samples[0][0] >= self.c.walking_window_s*.8:
            ankles = np.array([sf.ankle_delta for _, sf in walking_samples])
            centered = ankles-np.median(ankles)
            # Require alternating legs, sustained interval, and nontrivial body motion.
            signs = np.sign(centered[np.abs(centered) > self.c.walking_ankle_range*.2])
            changes = int(np.sum(signs[1:] != signs[:-1]))
            walking = bool(changes >= 2 and np.ptp(ankles) >= self.c.walking_ankle_range and speed >= self.c.walking_min_speed)
        supported=len(upright)>=2 and upright[-1][0]-upright[0][0]>=self.c.prior_support_s
        return Motion(speed, hip_speed, angle_speed, drop, delta, supported, walking,
                      t-self.samples[0][0],height_ratio)
