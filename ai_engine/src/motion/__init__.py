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
    hip_down_accel: float = 0.0
    head_drop: float = 0.0
    head_down_speed: float = 0.0
    motion_energy: float = 0.0
    post_drop_speed: float = 0.0
    prior_upright_ratio: float = 0.0
    lean_max: float = 0.0
    aspect_min: float = 1.0
    aspect_ratio_change: float = 1.0
    occlusion_ratio: float = 0.0


class MotionWindow:
    def __init__(self, config):
        self.c = config
        self.samples = deque()
        self.missing_times = deque()
        self.speed_history = deque()

    def reset(self):
        self.samples.clear()
        self.missing_times.clear()
        self.speed_history.clear()

    def record_missing(self, t):
        self.missing_times.append(t)
        while self.missing_times and t - self.missing_times[0] > self.c.window_s:
            self.missing_times.popleft()

    def update(self, t, f, posture):
        if self.samples and t <= self.samples[-1][0]:
            raise ValueError("Timestamps must strictly increase")
        effective_gap = max(self.c.max_gap_s, getattr(self.c, 'grace_period_s', 0.0))
        if self.samples and t - self.samples[-1][0] > effective_gap:
            self.reset()
        self.samples.append((t, f, posture))
        while self.samples and t - self.samples[0][0] > self.c.window_s:
            self.samples.popleft()
        while self.missing_times and t - self.missing_times[0] > self.c.window_s:
            self.missing_times.popleft()
        # Bound memory even for malformed high-frequency streams.
        while len(self.samples) > 1000:
            self.samples.popleft()
        if len(self.samples) < 2 or f is None:
            return Motion(lean_max=f.lean, aspect_min=f.aspect) if f is not None else Motion()
        # Net motion over a short real-time interval reduces frame-to-frame pose jitter.
        # Rapid fall signals below still use raw upright references, not this averaging.
        anchor = min(list(self.samples)[:-1], key=lambda item: abs((t - item[0]) - self.c.motion_speed_window_s))
        pt, pf, _ = anchor
        dt = t - pt
        scale = max(pf.torso, self.c.min_torso)
        speed = float(np.mean(np.linalg.norm(np.array(f.points) - np.array(pf.points), axis=1)) / scale / dt)
        inst_hip_v = float((f.hip_y - pf.hip_y) / scale / dt)
        self.speed_history.append((t, speed, inst_hip_v))
        while self.speed_history and t - self.speed_history[0][0] > self.c.window_s:
            self.speed_history.popleft()

        recent = [(st, sf, sp) for st, sf, sp in self.samples if t - st <= self.c.transition_s]
        upright = [(st, sf, sp) for st, sf, sp in recent[:-1] if sp in ("STANDING", "SITTING")]
        delta = drop = 0.0
        height_ratio = 1.0
        angle_speed = hip_speed = 0.0
        if upright:
            # Compare displacement and speed against the SAME upright reference.
            candidates = []
            for st, sf, _ in upright:
                d = (f.hip_y - sf.hip_y) / max(sf.torso, self.c.min_torso)
                a = f.lean - sf.lean
                elapsed = t - st
                ratio = f.body_height / max(sf.body_height, 1e-6) if f.coverage == sf.coverage and f.coverage != 'CORE_ONLY' else 1.0
                candidates.append((d, a, d / elapsed, a / elapsed, ratio))
            drop, delta, hip_speed, angle_speed, height_ratio = max(candidates, key=lambda x: x[0])

        # Rich spatio-temporal kinematics across the full sliding window (used by V2 ML features)
        win_samples = list(self.samples)
        prior_samples = win_samples[:-1]
        head_drop = head_down_speed = 0.0
        if prior_samples:
            # Peak kinematic drop across window (robust even if posture label briefly went UNKNOWN)
            best_head = max(
                (((f.head_y - sf.head_y) / max(sf.torso, self.c.min_torso),
                  ((f.head_y - sf.head_y) / max(sf.torso, self.c.min_torso)) / max(t - st, 1e-3))
                 for st, sf, _ in prior_samples if t - st <= 2.0),
                key=lambda x: x[0],
                default=(0.0, 0.0),
            )
            head_drop, head_down_speed = float(best_head[0]), float(best_head[1])
            if not upright and getattr(self.c, 'grace_period_s', 0.0) > 0:
                # Fallback kinematic delta relative to highest/most-upright prior pose in window
                kin_cands = []
                for st, sf, _ in prior_samples:
                    elapsed = t - st
                    if elapsed <= 0 or elapsed > 2.0:
                        continue
                    d = (f.hip_y - sf.hip_y) / max(sf.torso, self.c.min_torso)
                    a = f.lean - sf.lean
                    ratio = f.body_height / max(sf.body_height, 1e-6) if f.coverage == sf.coverage and f.coverage != 'CORE_ONLY' else 1.0
                    kin_cands.append((d, a, d / elapsed, a / elapsed, ratio))
                if kin_cands:
                    drop, delta, hip_speed, angle_speed, height_ratio = max(kin_cands, key=lambda x: x[0])

        # Downward hip acceleration & motion energy over recent 0.6s
        recent_v = [item for item in self.speed_history if t - item[0] <= 0.8]
        hip_down_accel = 0.0
        if len(recent_v) >= 2:
            accels = []
            for (t0, _, v0), (t1, _, v1) in zip(recent_v[:-1], recent_v[1:]):
                if t1 > t0:
                    accels.append((v1 - v0) / (t1 - t0))
            if accels:
                hip_down_accel = float(max(accels))
        motion_energy = float(np.sqrt(np.mean([v[1] ** 2 for v in recent_v]))) if recent_v else speed
        tail_v = [v[1] for v in self.speed_history if t - v[0] <= 0.35]
        post_drop_speed = float(np.mean(tail_v)) if tail_v else speed

        earlier = [sf for st, sf, _ in win_samples if 0.25 <= t - st <= 2.2]
        if earlier:
            upright_hits = sum(1 for sf in earlier if sf.lean < 42.0 and sf.aspect > 1.1)
            prior_upright_ratio = float(upright_hits / len(earlier))
        else:
            prior_upright_ratio = 0.0

        lean_max = float(max(sf.lean for _, sf, _ in win_samples))
        aspect_min = float(min(sf.aspect for _, sf, _ in win_samples))
        aspect_max = float(max(sf.aspect for _, sf, _ in win_samples))
        aspect_ratio_change = float(f.aspect / max(aspect_max, 1e-6))

        recent_valid_1s = sum(1 for st, _, _ in win_samples if t - st <= 1.0)
        recent_miss_1s = sum(1 for mt in self.missing_times if t - mt <= 1.0)
        occlusion_ratio = float(recent_miss_1s / max(recent_valid_1s + recent_miss_1s, 1))

        walking_samples = [(st, sf) for st, sf, sp in self.samples if t - st <= self.c.walking_window_s and sp == "STANDING" and sf.both_legs_visible]
        walking = False
        if len(walking_samples) >= 8 and walking_samples[-1][0] - walking_samples[0][0] >= self.c.walking_window_s * .8:
            ankles = np.array([sf.ankle_delta for _, sf in walking_samples])
            centered = ankles - np.median(ankles)
            # Require alternating legs, sustained interval, and nontrivial body motion.
            signs = np.sign(centered[np.abs(centered) > self.c.walking_ankle_range * .2])
            changes = int(np.sum(signs[1:] != signs[:-1]))
            walking = bool(changes >= 2 and np.ptp(ankles) >= self.c.walking_ankle_range and speed >= self.c.walking_min_speed)
        supported = len(upright) >= 2 and upright[-1][0] - upright[0][0] >= self.c.prior_support_s
        return Motion(
            speed, hip_speed, angle_speed, drop, delta, supported, walking,
            t - self.samples[0][0], height_ratio,
            hip_down_accel, head_drop, head_down_speed, motion_energy,
            post_drop_speed, prior_upright_ratio, lean_max, aspect_min,
            aspect_ratio_change, occlusion_ratio,
        )
