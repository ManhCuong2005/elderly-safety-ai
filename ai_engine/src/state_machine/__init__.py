from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Event:
    kind: str
    timestamp: float
    event_id: str = field(default_factory=lambda: str(uuid4()))
    details: dict = field(default_factory=dict)


class FallFSM:
    def __init__(self, config):
        self.c = config
        self.state = "NORMAL"
        self.event_id = None
        self.started = self.quiet_since = None
        self.cooldown_until = -1.0
        self.history = []

    def transition(self, state, t):
        if state != self.state:
            self.history.append((t, self.state, state, self.event_id))
            self.history = self.history[-1000:]
            self.state = state

    def update(self, t, candidate, posture, speed, reliable):
        events = []
        if self.state == "RECOVERED":
            self.transition("NORMAL", t)
        if self.state == "NORMAL" and reliable and candidate and t >= self.cooldown_until:
            self.event_id = str(uuid4())
            self.started, self.quiet_since = t, None
            self.transition("SUSPECTED_FALL", t)
            events.append(Event("SUSPECTED_FALL", t, self.event_id))
        elif self.state in ("SUSPECTED_FALL", "VERIFYING"):
            self.transition("VERIFYING", t)
            if not reliable:
                self.quiet_since = None
            elif posture in ("STANDING", "SITTING"):
                self.cooldown_until = t+self.c.cooldown_s
                self.transition("RECOVERED", t)
                events.append(Event("RECOVERED", t, self.event_id, {"reason": "upright_after_candidate"}))
            elif posture in ("LYING", "COLLAPSED_TORSO", "COLLAPSED_BODY") and speed < self.c.immobile_speed:
                if self.quiet_since is None:
                    self.quiet_since = t
                if t-self.quiet_since >= self.c.verification_s:
                    self.transition("ALERT", t)
                    self.cooldown_until = t+self.c.cooldown_s
                    events.append(Event("POSSIBLE_FALL", t, self.event_id,
                                        {"candidate_at_s": self.started, "verified_quiet_s": t-self.quiet_since}))
            else:
                self.quiet_since = None
            if self.state == "VERIFYING" and t-self.started >= self.c.verification_timeout_s:
                # Absence or ongoing movement never becomes a fall alert by timeout alone.
                self.cooldown_until = t+self.c.cooldown_s
                self.transition("RECOVERED", t)
                events.append(Event("UNVERIFIED_CANDIDATE", t, self.event_id))
        elif self.state == "ALERT" and reliable and posture == "STANDING":
            self.transition("RECOVERED", t)
            events.append(Event("RECOVERED", t, self.event_id, {"reason": "observed_upright"}))
        return events

    def confirm_safe(self, t, event_id):
        if event_id == self.event_id and self.state in ("SUSPECTED_FALL", "VERIFYING", "ALERT"):
            self.cooldown_until = t+self.c.cooldown_s
            self.transition("RECOVERED", t)
            return True
        return False
