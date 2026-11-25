from collections import deque
from dataclasses import dataclass

import numpy as np

from .pose import Cadence

SCHEMA = [
    "hip_drop", "shoulder_drop", "hip_down_speed", "shoulder_down_speed",
    "hip_peak_down_speed", "shoulder_peak_down_speed", "trunk_angle_change",
    "trunk_angle_end", "apparent_height_drop", "apparent_height_end",
    "apparent_height_missing", "visible_joint_ratio", "hip_horizontal_shift",
]

NO_PERSON = "Chưa thấy người"
TRACKING = "Đang theo dõi"
UNCLEAR = "Không nhìn rõ"
FALL_WARNING = "Nghi té ngã"


@dataclass
class Body:
    t: float
    hip: np.ndarray
    shoulder: np.ndarray
    scale: float
    angle: float
    extent: float
    coverage: float

    @classmethod
    def from_pose(cls, obs, confidence):
        good = obs.points[:, 2] >= confidence
        xy = obs.points[:, :2] / max(obs.width, obs.height)
        shoulder = xy[[5, 6]].mean(axis=0)
        hip = xy[[11, 12]].mean(axis=0)
        dx, dy = hip - shoulder
        scale = float(np.hypot(dx, dy))
        if scale < 0.018:
            return None
        angle = float(np.degrees(np.arctan2(abs(dx), max(abs(dy), 1e-7))))
        extent = float(np.ptp(xy[good, 1])) if good[:5].any() and good[13:].all() else np.nan
        return cls(obs.t, hip, shoulder, scale, angle, extent, float(good.mean()))


class Engine:
    def __init__(self, config, classifier=None, threshold=None, probabilities=None):
        self.cfg = config
        self.classifier = classifier
        self.threshold = threshold
        self.probabilities = probabilities
        self.history = deque()
        self.clock = Cadence(config["step_s"])
        self.last = None
        self.last_seen = None
        self.last_alarm = -np.inf
        self.below_since = None
        self.streak = 0
        self.active = False
        self.missing_body = False
        self.state = NO_PERSON
        self.score = None

    def features(self, t):
        span = self.cfg["window_s"]
        # Keep one observation immediately before the boundary to check window coverage.
        while len(self.history) > 1 and self.history[1].t <= t - span:
            self.history.popleft()
        elapsed = t - self.history[0].t
        if elapsed + 1e-8 < span:
            return None
        samples = [body for body in self.history if t - span - 1e-8 <= body.t <= t]
        if len(samples) < 3:
            return None
        early = samples[:3]
        late = samples[-3:]
        first, last = early[0], late[-1]
        duration = last.t - first.t
        scale = float(np.median([b.scale for b in early]))
        hip = np.array([b.hip for b in samples])
        shoulder = np.array([b.shoulder for b in samples])
        times = np.array([b.t for b in samples])
        dt = (times[2:] - times[:-2]) * scale
        hip_drop = (np.median(hip[-3:, 1]) - np.median(hip[:3, 1])) / scale
        shoulder_drop = (np.median(shoulder[-3:, 1]) - np.median(shoulder[:3, 1])) / scale
        extent_missing = not (np.isfinite(first.extent) and np.isfinite(last.extent))
        coverage = np.mean([b.coverage for b in samples])
        if self.cfg.get("bridge_small_gaps"):
            coverage *= min(1, len(samples) / (span * self.cfg["sample_hz"]))
        return np.array([
            hip_drop, shoulder_drop, hip_drop / duration, shoulder_drop / duration,
            np.percentile((hip[2:, 1] - hip[:-2, 1]) / dt, 90),
            np.percentile((shoulder[2:, 1] - shoulder[:-2, 1]) / dt, 90),
            (np.median([b.angle for b in late]) - np.median([b.angle for b in early])) / 90,
            last.angle / 90,
            np.nan if extent_missing else (first.extent - last.extent) / scale,
            last.extent / scale, float(extent_missing),
            coverage, (last.hip[0] - first.hip[0]) / scale,
        ], dtype=np.float64)

    def step(self, obs):
        t = obs.t
        if not np.isfinite(t) or (self.last is not None and t <= self.last):
            raise ValueError("Timestamp phải tăng dần")
        gap = self.last is not None and t - self.last > self.cfg["max_gap_s"]
        self.last = t
        view = obs.state(self.cfg["confidence"])
        body = Body.from_pose(obs, self.cfg["confidence"]) if view == "visible" else None
        if view != "absent":
            self.last_seen = t
        short_gap = self.history and t - self.history[-1].t <= self.cfg["max_gap_s"] + 1e-8
        bridge = self.cfg.get("bridge_small_gaps") and short_gap
        if gap or (body is None and not bridge):
            self.history.clear()
        if body is not None and self.history and self.missing_body:
            previous = self.history[-1]
            shift = max(np.linalg.norm(body.hip - previous.hip), np.linalg.norm(body.shoulder - previous.shoulder))
            if not bridge or shift > 0.9 * max(previous.scale, body.scale):
                self.history.clear()
        if gap or body is None:
            self.streak = 0
            self.active = False
            self.below_since = None
            self.score = None
        self.missing_body = body is None
        alarm = False
        features = None
        if body is None:
            outside = self.last_seen is None or t - self.last_seen >= self.cfg["absent_s"]
            self.state = NO_PERSON if view == "absent" and outside else UNCLEAR
        else:
            self.history.append(body)
            if self.clock.due(t):
                features = self.features(t)
                if features is not None and (self.classifier is not None or self.probabilities is not None):
                    self.score = (self.probabilities[t] if self.probabilities is not None
                                  else float(self.classifier.predict_proba(features[None])[0, 1]))
                    alarm = self.update_alarm(t, self.score)
            self.state = FALL_WARNING if self.active else TRACKING
        return {"t": t, "state": self.state, "score": self.score, "alarm": alarm,
                "features": features, "warming": self.score is None and self.state == TRACKING}

    def update_alarm(self, t, score):
        if score < self.threshold:
            self.streak = 0
            if self.below_since is None:
                self.below_since = t
            if t - self.below_since >= self.cfg["rearm_s"]:
                self.active = False
            return False
        self.below_since = None
        self.streak += 1
        if self.active or self.streak < self.cfg["alarm_streak"]:
            return False
        if t - self.last_alarm < self.cfg["cooldown_s"]:
            return False
        self.last_alarm, self.active = t, True
        return True


def points_for_web(obs, confidence):
    return [[round(float(x / obs.width), 5), round(float(y / obs.height), 5)]
            if c >= confidence else None for x, y, c in obs.points]


def web_result(engine, obs):
    result = engine.step(obs)
    result.pop("features")
    result["points"] = points_for_web(obs, engine.cfg["confidence"])
    return result
