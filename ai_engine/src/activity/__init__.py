"""Daily/session activity monitoring: cumulative durations, sit-to-stand transitions, mobility level."""


class ActivityTracker:
    LABELS = ("STANDING", "WALKING", "SITTING", "BENDING", "LYING", "SLUMPED", "UNKNOWN")

    def __init__(self, max_step_s=1.0):
        self.max_step_s = max_step_s
        self.reset()

    def reset(self):
        self.durations_s = {label: 0.0 for label in self.LABELS}
        self.sit_to_stand_count = 0
        self.stand_to_sit_count = 0
        self.last_t = None
        self.last_label = "UNKNOWN"
        self.last_known_posture = None

    def update(self, t, label):
        if label not in self.durations_s:
            label = "UNKNOWN"
        if self.last_t is not None and t > self.last_t:
            dt = min(t - self.last_t, self.max_step_s)
            self.durations_s[self.last_label] += dt
        if label != "UNKNOWN":
            if self.last_known_posture == "SITTING" and label in ("STANDING", "WALKING"):
                self.sit_to_stand_count += 1
            elif self.last_known_posture in ("STANDING", "WALKING") and label == "SITTING":
                self.stand_to_sit_count += 1
            self.last_known_posture = label
        self.last_t = t
        self.last_label = label

    def summary(self):
        observed = sum(v for k, v in self.durations_s.items() if k != "UNKNOWN")
        active = self.durations_s["WALKING"] + self.durations_s["STANDING"] + self.durations_s["BENDING"]
        active_ratio = (active / observed) if observed > 0 else 0.0
        if observed < 2.0:
            level = "INSUFFICIENT_DATA"
        elif self.durations_s["WALKING"] / observed >= 0.25 or active_ratio >= 0.65:
            level = "ACTIVE"
        elif active_ratio >= 0.30:
            level = "MODERATE"
        else:
            level = "SEDENTARY"
        return {
            "durations_s": {k: round(v, 2) for k, v in self.durations_s.items()},
            "observed_s": round(observed, 2),
            "sit_to_stand_count": self.sit_to_stand_count,
            "stand_to_sit_count": self.stand_to_sit_count,
            "active_ratio": round(active_ratio, 3),
            "activity_level": level,
        }
