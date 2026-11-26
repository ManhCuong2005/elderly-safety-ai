"""Post-fall convulsion / thrashing detector.

A person who is on the floor and *moves* is not necessarily safe: seizures and
stroke-related convulsions produce sustained, rhythmic limb oscillation (~2-9 Hz)
while the body centre barely travels. Rather than treating "speed >= immobile"
as "fine", this module measures limb oscillation relative to the hip:

  * limb joints (elbows, wrists, knees, ankles) in hip-relative, torso-normalised units
  * direction reversals per second of each joint (frequency proxy)
  * oscillation amplitude (peak-to-peak) well above landmark jitter
  * hip drift small (not crawling / walking / being dragged)

Only fed while the person is observed on the floor; history is discarded otherwise.
"""
from collections import deque
import numpy as np

LIMB_IDS = (13, 14, 15, 16, 25, 26, 27, 28)
MIN_LIMB_VIS = 0.3
MIN_SAMPLES = 10
MIN_FPS = 8.0


class ConvulsionDetector:
    def __init__(self, config):
        self.c = config
        self.reset()

    def reset(self):
        self.samples = deque()  # (t, hip_xy, rel[K,2] with nan for hidden joints, torso)
        self.since = None
        self.last = self._result(False, 0.0, 0.0, 0.0, 0)

    @staticmethod
    def _result(convulsing, rate_hz, amplitude, score, joints):
        return {"convulsing": bool(convulsing), "rate_hz": round(float(rate_hz), 2),
                "amplitude": round(float(amplitude), 3), "score": round(float(score), 3),
                "oscillating_joints": int(joints)}

    def update(self, t, landmarks, width, height, torso, grounded):
        """Feed one frame. Returns dict with `convulsing` True once oscillation is sustained."""
        if not getattr(self.c, "enable_convulsion", False) or not grounded or landmarks is None or torso is None:
            self.reset()
            return self.last
        data = np.asarray(landmarks, dtype=float)
        if data.shape != (33, 4) or not np.isfinite(data).all() or width <= 0 or height <= 0 or torso <= 0:
            return self.last
        xy = data[:, :2].copy()
        xy[:, 0] *= width / height
        hip = (xy[23] + xy[24]) / 2
        rel = (xy[list(LIMB_IDS)] - hip) / max(torso, self.c.min_torso)
        vis = data[list(LIMB_IDS), 3] >= MIN_LIMB_VIS
        rel[~vis] = np.nan
        if self.samples and t <= self.samples[-1][0]:
            return self.last
        self.samples.append((t, hip, rel, max(torso, self.c.min_torso)))
        while self.samples and t - self.samples[0][0] > self.c.convulsion_window_s:
            self.samples.popleft()
        self.last = self._evaluate(t)
        if self.last["convulsing"]:
            if self.since is None:
                self.since = t
        else:
            self.since = None
        sustained = self.since is not None and t - self.since >= self.c.convulsion_sustain_s
        self.last = dict(self.last, convulsing=bool(sustained), candidate=bool(self.since is not None))
        return self.last

    def _evaluate(self, t):
        n = len(self.samples)
        span = self.samples[-1][0] - self.samples[0][0]
        if n < MIN_SAMPLES or span < self.c.convulsion_window_s * 0.7 or (n - 1) / max(span, 1e-6) < MIN_FPS:
            return self._result(False, 0.0, 0.0, 0.0, 0)
        times = np.array([s[0] for s in self.samples])
        hips = np.array([s[1] for s in self.samples])
        drift = float(np.max(np.ptp(hips, axis=0)) / np.median([s[3] for s in self.samples]))  # torso units
        rel_all = np.stack([s[2] for s in self.samples])  # [n, K, 2]
        osc_joints, rates, amps = 0, [], []
        for k in range(rel_all.shape[1]):
            series = rel_all[:, k, :]
            valid = np.isfinite(series).all(axis=1)
            if valid.sum() < 0.8 * n:
                continue
            tt, ss = times[valid], series[valid]
            best_rate, best_amp, ok = 0.0, 0.0, False
            for axis in (0, 1):
                x = ss[:, axis]
                amp = float(np.ptp(x))
                if amp < self.c.convulsion_amp:
                    continue
                v = np.diff(x) / np.maximum(np.diff(tt), 1e-3)
                vthr = self.c.convulsion_amp * self.c.convulsion_min_hz * 0.8  # torso-units / s
                strong = np.abs(v) >= vthr * 0.5
                signs = np.sign(v)
                rev = 0
                last_sign = 0
                for s_, st in zip(signs, strong):
                    if s_ == 0 or not st:
                        continue
                    if last_sign != 0 and s_ != last_sign:
                        rev += 1
                    last_sign = s_
                seg = float(tt[-1] - tt[0])
                rate_hz = rev / 2.0 / max(seg, 1e-6)
                if self.c.convulsion_min_hz <= rate_hz <= self.c.convulsion_max_hz and amp > best_amp:
                    best_rate, best_amp, ok = rate_hz, amp, True
            if ok:
                osc_joints += 1
                rates.append(best_rate)
                amps.append(best_amp)
        drift_ok = drift <= self.c.convulsion_max_drift
        hit = osc_joints >= 2 and drift_ok
        score = min(1.0, osc_joints / 4.0)
        return self._result(hit, float(np.median(rates)) if rates else 0.0,
                            float(np.median(amps)) if amps else 0.0, score if hit else score * 0.5, osc_joints)
