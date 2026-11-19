import math


def classify(f, c):
    if f is None or f.coverage=='CORE_ONLY':
        return "UNKNOWN"
    if f.lean >= c.lying_lean and f.aspect <= c.lying_aspect and f.leg_vertical <= c.lying_leg_vertical:
        return "LYING"
    straight=f.knee>=c.standing_knee and f.hip_angle>=c.standing_knee
    extended=f.leg_vertical>=c.standing_leg_vertical and f.thigh_vertical>=c.standing_thigh_vertical and f.hip_angle>=c.standing_hip
    if f.lean <= c.standing_lean and (straight or extended):
        return "STANDING"
    if f.lean <= c.standing_lean + 15 and f.knee <= c.sitting_knee and f.hip_angle <= c.sitting_hip:
        return "SITTING"
    return "UNKNOWN"


class StablePosture:
    def __init__(self, config):
        self.config = config
        self.reset()

    def reset(self):
        self.value, self.candidate, self.since = "UNKNOWN", None, None
        self.smooth, self.last_t = None, None

    def update(self, raw, t, features):
        # EMA is telemetry only: fall transients always use unsmoothed features.
        if features is not None:
            alpha = 1 if self.last_t is None else 1-math.exp(-(t-self.last_t)/self.config.smoothing_tau_s)
            self.smooth = features.lean if self.smooth is None else self.smooth + alpha*(features.lean-self.smooth)
        self.last_t = t
        if raw == "UNKNOWN":
            self.value, self.candidate, self.since = raw, None, None
        elif raw != self.candidate:
            self.candidate, self.since = raw, t
        elif t-self.since >= self.config.posture_debounce_s:
            self.value = raw
        return self.value
