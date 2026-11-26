"""Post-fall convulsion / thrashing detector for MoveNet 17-keypoint poses.

Measures rhythmic limb oscillation (2-9 Hz) relative to the hip in torso-normalised
units while the subject is grounded or slumped, rejecting jitter and crawling/walking.
"""
from collections import deque
import numpy as np

# MoveNet 17-keypoint limb indices: L/R elbow, L/R wrist, L/R knee, L/R ankle
LIMB_IDS = (7, 8, 9, 10, 13, 14, 15, 16)
MIN_SAMPLES = 10
MIN_FPS = 6.0


class ConvulsionDetector:
    def __init__(self, config):
        self.window_s = float(config.get("convulsion_window_s", 2.0))
        self.min_hz = float(config.get("convulsion_min_hz", 2.0))
        self.max_hz = float(config.get("convulsion_max_hz", 9.0))
        self.min_amp = float(config.get("convulsion_amp", 0.14))
        self.max_drift = float(config.get("convulsion_max_drift", 1.2))
        self.sustain_s = float(config.get("convulsion_sustain_s", 1.0))
        self.confidence = float(config.get("confidence", 0.3))
        self.enabled = bool(config.get("enable_convulsion", True))
        self.reset()

    def reset(self):
        self.samples = deque()  # (t, hip_xy, rel[8, 2], torso_scale)
        self.since = None
        self.last = self._result(False, 0.0, 0.0, 0.0, 0)

    @staticmethod
    def _result(convulsing, rate_hz, amplitude, score, joints):
        return {
            "convulsing": bool(convulsing),
            "rate_hz": round(float(rate_hz), 2),
            "amplitude": round(float(amplitude), 3),
            "score": round(float(score), 3),
            "oscillating_joints": int(joints),
        }

    def update(self, obs, body, grounded):
        """Feed one MoveNet Observation + Body. Returns convulsion telemetry dict."""
        if not self.enabled or not grounded or obs is None or body is None:
            self.reset()
            return self.last
        xy = obs.points[:, :2].astype(float) / max(obs.width, obs.height)
        rel = (xy[list(LIMB_IDS)] - body.hip) / max(body.scale, 0.018)
        vis = obs.points[list(LIMB_IDS), 2] >= self.confidence
        rel[~vis] = np.nan
        t = float(obs.t)
        if self.samples and t <= self.samples[-1][0]:
            return self.last
        self.samples.append((t, body.hip.copy(), rel, max(body.scale, 0.018)))
        while self.samples and t - self.samples[0][0] > self.window_s:
            self.samples.popleft()
        raw = self._evaluate()
        if raw["convulsing"]:
            if self.since is None:
                self.since = t
        else:
            self.since = None
        sustained = self.since is not None and (t - self.since) >= self.sustain_s
        self.last = {**raw, "convulsing": bool(sustained), "candidate": bool(self.since is not None)}
        return self.last

    def _evaluate(self):
        n = len(self.samples)
        span = self.samples[-1][0] - self.samples[0][0]
        if n < MIN_SAMPLES or span < self.window_s * 0.7 or (n - 1) / max(span, 1e-6) < MIN_FPS:
            return self._result(False, 0.0, 0.0, 0.0, 0)
        times = np.array([s[0] for s in self.samples])
        hips = np.array([s[1] for s in self.samples])
        med_scale = float(np.median([s[3] for s in self.samples]))
        drift = float(np.max(np.ptp(hips, axis=0)) / max(med_scale, 0.018))
        rel_all = np.stack([s[2] for s in self.samples])  # [n, 8, 2]
        osc_joints, rates, amps = 0, [], []
        for k in range(rel_all.shape[1]):
            series = rel_all[:, k, :]
            valid = np.isfinite(series).all(axis=1)
            if valid.sum() < 0.75 * n:
                continue
            tt, ss = times[valid], series[valid]
            best_rate, best_amp, ok = 0.0, 0.0, False
            for axis in (0, 1):
                x = ss[:, axis]
                amp = float(np.ptp(x))
                if amp < self.min_amp:
                    continue
                v = np.diff(x) / np.maximum(np.diff(tt), 1e-3)
                vthr = self.min_amp * self.min_hz * 0.4
                strong = np.abs(v) >= vthr
                signs = np.sign(v)
                rev, last_sign = 0, 0
                for s_, st in zip(signs, strong):
                    if s_ == 0 or not st:
                        continue
                    if last_sign != 0 and s_ != last_sign:
                        rev += 1
                    last_sign = s_
                seg = float(tt[-1] - tt[0])
                rate_hz = rev / 2.0 / max(seg, 1e-6)
                if self.min_hz <= rate_hz <= self.max_hz and amp > best_amp:
                    best_rate, best_amp, ok = rate_hz, amp, True
            if ok:
                osc_joints += 1
                rates.append(best_rate)
                amps.append(best_amp)
        hit = osc_joints >= 2 and drift <= self.max_drift
        score = min(1.0, osc_joints / 4.0)
        return self._result(
            hit,
            float(np.median(rates)) if rates else 0.0,
            float(np.median(amps)) if amps else 0.0,
            score if hit else score * 0.5,
            osc_joints,
        )
