from collections import deque
from dataclasses import dataclass

import numpy as np

from .convulsion import ConvulsionDetector
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

ALARM_LABELS = {
    "fall": "Nghi té ngã",
    "convulsion": "Nghi co giật / giãy giụa",
    "stroke_slump": "Nghi đột quỵ / ngồi gục bất động",
    "slow_collapse": "Trượt ngã chậm / nằm gục bất động",
}


def _head_droop(obs, xy, shoulder, scale, confidence):
    """Compute (head_y - shoulder_y) / torso using MoveNet head joints (0..4)."""
    head_ids = [i for i in (0, 1, 2, 3, 4) if obs.points[i, 2] >= confidence]
    if not head_ids:
        return -0.35
    pts = xy[head_ids]
    spread = float(np.max(np.ptp(pts, axis=0))) if len(head_ids) > 1 else 0.0
    if len(head_ids) > 1 and spread < 1e-4:
        return -0.35
    if 0 in head_ids and spread > 0.6 * scale:
        head_y = float(xy[0, 1])
    else:
        head_y = float(np.mean(pts[:, 1]))
    return float((head_y - shoulder[1]) / scale)


@dataclass
class Body:
    t: float
    hip: np.ndarray
    shoulder: np.ndarray
    scale: float
    angle: float
    extent: float
    coverage: float
    head_droop: float = -0.35
    torso_inverted: bool = False
    lying: bool = False
    slumped: bool = False
    upright: bool = True

    @classmethod
    def from_pose(cls, obs, confidence, slump_head_droop=-0.10, slump_lean_deg=25.0):
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
        head_droop = _head_droop(obs, xy, shoulder, scale, confidence)
        torso_inverted = bool(shoulder[1] >= hip[1] + 0.05 * scale)
        lying = bool(torso_inverted or angle >= 55.0)
        slumped = bool(
            not lying
            and head_droop >= slump_head_droop
            and (angle >= slump_lean_deg or head_droop >= 0.02)
        )
        upright = bool(not torso_inverted and angle < 35.0 and head_droop < -0.15)
        return cls(
            obs.t, hip, shoulder, scale, angle, extent, float(good.mean()),
            head_droop, torso_inverted, lying, slumped, upright,
        )


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
        self.convulsion = ConvulsionDetector(config)
        self.alert_locked = False
        self.alarm_reason = None
        self.upright_since = None
        self.last_upright_t = None
        self.slump_since = None
        self.slump_last_t = None

    def confirm_safe(self, t=None):
        """Caregiver manually clears a locked alert."""
        if not self.alert_locked and not self.active:
            return False
        self.alert_locked = False
        self.active = False
        self.alarm_reason = None
        self.upright_since = None
        self.slump_since = self.slump_last_t = None
        self.streak = 0
        self.convulsion.reset()
        if t is not None and np.isfinite(t):
            self.last_alarm = max(self.last_alarm, float(t))
        self.state = TRACKING if not self.missing_body else NO_PERSON
        return True

    def _instant_speed(self, t, body):
        if not self.history or body is None:
            return 0.0
        anchor = min(self.history, key=lambda b: abs((t - b.t) - 0.3))
        dt = t - anchor.t
        if dt <= 1e-4:
            return 0.0
        scale = max(anchor.scale, body.scale, 0.018)
        hip_v = float(np.linalg.norm(body.hip - anchor.hip) / scale / dt)
        sh_v = float(np.linalg.norm(body.shoulder - anchor.shoulder) / scale / dt)
        return max(hip_v, sh_v)

    def features(self, t):
        span = self.cfg["window_s"]
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

    def _trigger_alert(self, t, reason):
        self.last_alarm = t
        self.active = True
        self.alarm_reason = reason
        if self.cfg.get("alert_lock_enabled", True):
            self.alert_locked = True
            self.upright_since = None

    def step(self, obs):
        t = obs.t
        if not np.isfinite(t) or (self.last is not None and t <= self.last):
            raise ValueError("Timestamp phải tăng dần")
        gap = self.last is not None and t - self.last > self.cfg["max_gap_s"]
        self.last = t
        view = obs.state(self.cfg["confidence"])
        slump_droop = float(self.cfg.get("slump_head_droop", -0.10))
        slump_lean = float(self.cfg.get("slump_lean_deg", 25.0))
        body = (Body.from_pose(obs, self.cfg["confidence"], slump_droop, slump_lean)
                if view == "visible" else None)
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
                self.upright_since = None
        if gap or body is None:
            self.streak = 0
            if not self.alert_locked:
                self.active = False
            self.below_since = None
            self.score = None
            self.upright_since = None
        self.missing_body = body is None
        alarm = False
        features = None
        conv = self.convulsion.last
        can_alert = (self.classifier is not None or self.probabilities is not None)

        if body is None:
            if self.slump_last_t is not None and t - self.slump_last_t > 2.0:
                self.slump_since = self.slump_last_t = None
            if not short_gap:
                self.convulsion.reset()
                conv = self.convulsion.last
            if self.alert_locked:
                self.state = FALL_WARNING
            else:
                outside = self.last_seen is None or t - self.last_seen >= self.cfg["absent_s"]
                self.state = NO_PERSON if view == "absent" and outside else UNCLEAR
        else:
            speed = self._instant_speed(t, body)
            self.history.append(body)
            if body.upright:
                self.last_upright_t = t
                self.slump_since = self.slump_last_t = None

            if self.clock.due(t):
                features = self.features(t)
                if features is not None and can_alert:
                    self.score = (self.probabilities[t] if self.probabilities is not None
                                  else float(self.classifier.predict_proba(features[None])[0, 1]))
                    alarm = self.update_alarm(t, self.score)
                    if alarm:
                        self._trigger_alert(t, "fall")

            grounded = bool(body.lying or body.slumped)
            conv = self.convulsion.update(obs, body, grounded)
            cooldown = float(self.cfg.get("cooldown_s", 3.0))
            if (can_alert and not alarm and not self.alert_locked
                    and conv.get("convulsing") and grounded and (t - self.last_alarm >= cooldown)):
                alarm = True
                self._trigger_alert(t, "convulsion")

            enable_slump = bool(self.cfg.get("enable_slump_detection", True))
            immobile_speed = float(self.cfg.get("immobile_speed", 0.35))
            prior_window = float(self.cfg.get("slump_prior_window_s", 30.0))
            slump_alert_s = float(self.cfg.get("slump_alert_s", 3.5))
            has_prior = (
                (self.last_upright_t is not None and (t - self.last_upright_t) <= prior_window)
                or (self.score is not None and self.score >= 0.70)
            )
            if enable_slump and grounded and speed < immobile_speed and has_prior:
                if self.slump_since is None:
                    self.slump_since = t
                self.slump_last_t = t
                if (can_alert and not alarm and not self.alert_locked
                        and (t - self.slump_since) >= slump_alert_s
                        and (t - self.last_alarm >= cooldown)):
                    alarm = True
                    self._trigger_alert(t, "stroke_slump" if body.slumped else "slow_collapse")
                    self.slump_since = self.slump_last_t = None
            elif self.slump_last_t is not None and (t - self.slump_last_t) > 2.0:
                self.slump_since = self.slump_last_t = None

            if self.alert_locked:
                if body.upright:
                    if self.upright_since is None:
                        self.upright_since = t
                    if (t - self.upright_since) >= float(self.cfg.get("recovery_hold_s", 3.0)):
                        self.alert_locked = False
                        self.active = False
                        self.alarm_reason = None
                        self.upright_since = None
                else:
                    self.upright_since = None

            self.state = FALL_WARNING if (self.active or self.alert_locked) else TRACKING

        return {
            "t": t,
            "state": self.state,
            "score": self.score,
            "alarm": alarm,
            "alarm_reason": self.alarm_reason if (alarm or self.alert_locked or self.active) else None,
            "alert_locked": self.alert_locked,
            "convulsion": conv,
            "features": features,
            "warming": self.score is None and self.state == TRACKING,
        }

    def update_alarm(self, t, score):
        if score < self.threshold:
            self.streak = 0
            if self.below_since is None:
                self.below_since = t
            if not self.alert_locked and t - self.below_since >= self.cfg["rearm_s"]:
                self.active = False
                self.alarm_reason = None
            return False
        self.below_since = None
        self.streak += 1
        if self.active or self.alert_locked or self.streak < self.cfg["alarm_streak"]:
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
