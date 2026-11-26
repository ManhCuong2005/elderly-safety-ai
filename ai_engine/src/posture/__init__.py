import math


def classify(f, c):
    if f is None or f.coverage=='CORE_ONLY':
        return "UNKNOWN"
    if getattr(f, 'torso_inverted', False):
        return "LYING"
    if f.lean >= c.lying_lean and f.aspect <= c.lying_aspect and f.leg_vertical <= c.lying_leg_vertical:
        return "LYING"
    head_droop = getattr(f, 'head_droop', -0.35)
    straight=f.knee>=c.standing_knee and f.hip_angle>=c.standing_knee
    extended=f.leg_vertical>=c.standing_leg_vertical and f.thigh_vertical>=c.standing_thigh_vertical and f.hip_angle>=c.standing_hip
    if f.lean <= c.standing_lean and head_droop <= 0.05 and (straight or extended):
        return "STANDING"
    if getattr(c, 'enable_bending', False):
        if (c.bending_lean_min <= f.lean <= c.bending_lean_max
                and f.hip_angle <= c.bending_hip_max
                and f.knee >= c.bending_knee_min
                and f.leg_vertical >= c.bending_leg_vertical_min):
            return "BENDING"
    if f.lean <= c.standing_lean + 15 and f.knee <= c.sitting_knee and f.hip_angle <= c.sitting_hip:
        if getattr(c, 'enable_slump_detection', False):
            if head_droop >= c.slump_head_droop and (f.z_lean_3d >= c.slump_lean_3d or head_droop >= 0.0):
                return "SLUMPED"
        return "SITTING"
    # High-angle / diagonal CCTV views stretch 2D leg_vertical while 3D torso lean is clearly horizontal.
    if f.z_lean_3d >= c.lying_lean and f.lean >= 38.0 and f.aspect <= 1.55:
        return "LYING"
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
