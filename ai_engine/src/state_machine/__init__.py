from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Event:
    kind: str
    timestamp: float
    event_id: str = field(default_factory=lambda: str(uuid4()))
    details: dict = field(default_factory=dict)


FLOOR_POSTURES = ("LYING", "COLLAPSED_TORSO", "COLLAPSED_BODY", "SLUMPED")


class FallFSM:
    def __init__(self, config):
        self.c = config
        self.state = "NORMAL"
        self.event_id = None
        self.started = self.quiet_since = None
        self.cooldown_until = -1.0
        self.history = []
        self.floor_since = self.last_floor_t = None   # observed continuous floor time
        self.upright_since = None                      # ALERT recovery hold
        self.assist_seen_t = None                      # last time >1 person was in view
        self.assisted = False                          # helpers seen during this event
        self.alert_basis = None
        self.last_upright_t = None                     # recent healthy upright observation
        self.slump_since = None                        # continuous slumped/slow-collapse immobile time
        self.slump_last_t = None                       # last slumped/collapsed frame (grace across brief dropouts)

    def transition(self, state, t):
        if state != self.state:
            self.history.append((t, self.state, state, self.event_id))
            self.history = self.history[-1000:]
            self.state = state

    @property
    def alert_locked(self):
        """True while an ALERT is latched: it only clears by caregiver confirm or observed upright hold."""
        return self.state == "ALERT"

    def note_people(self, t, multiple):
        """Engine tells the FSM that several people are in view (helper arriving / occluding)."""
        events = []
        if not multiple:
            return events
        self.assist_seen_t = t
        if self.state in ("SUSPECTED_FALL", "VERIFYING", "ALERT") and not self.assisted:
            self.assisted = True
            events.append(Event("ASSISTANCE_DETECTED", t, self.event_id, {"state": self.state}))
        return events

    def _alert(self, t, basis, events, extra=None):
        self.transition("ALERT", t)
        self.alert_basis = basis
        self.upright_since = None
        self.cooldown_until = t + self.c.cooldown_s
        details = {"candidate_at_s": self.started, "basis": basis}
        if self.quiet_since is not None:
            details["verified_quiet_s"] = t - self.quiet_since
        if self.floor_since is not None:
            details["floor_s"] = t - self.floor_since
        if extra:
            details.update(extra)
        events.append(Event("POSSIBLE_FALL", t, self.event_id, details))

    def update(self, t, candidate, posture, speed, reliable, within_grace=False, convulsing=False):
        events = []
        cancel_cd = min(self.c.cooldown_s, getattr(self.c, "cancel_cooldown_s", 1.5))
        if self.state == "RECOVERED":
            self.transition("NORMAL", t)
        if reliable and posture in ("STANDING", "WALKING", "SITTING"):
            self.last_upright_t = t
            self.slump_since = self.slump_last_t = None
        if self.state == "NORMAL" and reliable and t >= self.cooldown_until:
            if convulsing and posture in FLOOR_POSTURES:
                # Sustained convulsion/thrashing on the floor is an immediate emergency
                # even if the initial collapse was slow, occluded, or off a chair/hammock.
                self.event_id = str(uuid4())
                self.started, self.quiet_since = t, None
                self.floor_since = self.last_floor_t = t
                self.upright_since = None
                self.assisted = False
                self.alert_basis = None
                self._alert(t, "convulsion", events, {"convulsion": True})
            elif candidate:
                self.event_id = str(uuid4())
                self.started, self.quiet_since = t, None
                self.floor_since = t if posture in FLOOR_POSTURES else None
                self.last_floor_t = t if posture in FLOOR_POSTURES else None
                self.upright_since = None
                self.assisted = False
                self.alert_basis = None
                self.transition("SUSPECTED_FALL", t)
                events.append(Event("SUSPECTED_FALL", t, self.event_id))
            elif (
                getattr(self.c, "enable_slump_detection", False)
                and self.last_upright_t is not None
                and (t - self.last_upright_t) <= getattr(self.c, "slump_prior_window_s", 30.0)
                and posture in ("SLUMPED", "COLLAPSED_TORSO", "COLLAPSED_BODY")
                and speed < self.c.immobile_speed
            ):
                # Slow wall-slide / seated stroke slump without a high-speed fall transient.
                if self.slump_since is None:
                    self.slump_since = t
                self.slump_last_t = t
                if t - self.slump_since >= getattr(self.c, "slump_alert_s", 3.5):
                    self.event_id = str(uuid4())
                    self.started, self.quiet_since = self.slump_since, self.slump_since
                    self.floor_since = self.last_floor_t = self.slump_since
                    self.upright_since = None
                    self.assisted = False
                    self.alert_basis = None
                    basis = "stroke_slump" if posture == "SLUMPED" else "slow_collapse"
                    self._alert(t, basis, events, {"slump_posture": posture})
                    self.slump_since = self.slump_last_t = None
            else:
                if self.slump_last_t is not None and t - self.slump_last_t > max(getattr(self.c, "occlusion_hold_s", 2.0), 1.5):
                    self.slump_since = self.slump_last_t = None
        elif self.state == "NORMAL" and not reliable:
            if self.slump_last_t is not None and t - self.slump_last_t > max(getattr(self.c, "occlusion_hold_s", 2.0), 1.5):
                self.slump_since = self.slump_last_t = None
        elif self.state in ("SUSPECTED_FALL", "VERIFYING"):
            self.transition("VERIFYING", t)
            if not reliable:
                if not within_grace:
                    self.quiet_since = None
            elif posture in ("STANDING", "SITTING"):
                self.cooldown_until = t + cancel_cd
                self.floor_since = None
                self.transition("RECOVERED", t)
                events.append(Event("RECOVERED", t, self.event_id, {"reason": "upright_after_candidate"}))
            elif posture in FLOOR_POSTURES:
                self.last_floor_t = t
                if self.floor_since is None:
                    self.floor_since = t
                if convulsing:
                    # Rhythmic limb thrashing on the floor is never "safe movement".
                    self._alert(t, "convulsion", events, {"convulsion": True})
                elif speed < self.c.immobile_speed:
                    if self.quiet_since is None:
                        self.quiet_since = t
                    if t-self.quiet_since >= self.c.verification_s:
                        basis = "stroke_slump" if posture == "SLUMPED" else "immobile"
                        self._alert(t, basis, events)
                else:
                    self.quiet_since = None
                if self.state == "VERIFYING" and t - self.floor_since >= self.c.entrapment_s:
                    # Moving or not, they have not been able to get up.
                    self._alert(t, "unrecovered_on_floor", events)
            elif posture in ("BENDING", "WALKING"):
                self.floor_since = None
                self.quiet_since = None
            else:
                self.quiet_since = None
            if self.state == "VERIFYING" and t-self.started >= self.c.verification_timeout_s:
                still_on_floor = (self.last_floor_t is not None
                                  and t - self.last_floor_t <= getattr(self.c, "occlusion_hold_s", 0.0))
                helpers_here = (self.assist_seen_t is not None and t - self.assist_seen_t <= 3.0
                                and self.last_floor_t is not None
                                and t - self.started < getattr(self.c, "assist_hold_s", 0.0))
                if not still_on_floor and not helpers_here:
                    # Absence or ongoing movement never becomes a fall alert by timeout alone.
                    self.cooldown_until = t + cancel_cd
                    self.floor_since = None
                    self.transition("RECOVERED", t)
                    events.append(Event("UNVERIFIED_CANDIDATE", t, self.event_id))
        elif self.state == "ALERT":
            # Safety lock: only a *reliable, uninterrupted* upright hold clears an alert.
            # Occlusion, helpers entering the frame or identity re-acquisition never clear it.
            if reliable and posture == "STANDING":
                if self.upright_since is None:
                    self.upright_since = t
                if t - self.upright_since >= getattr(self.c, "recovery_hold_s", 0.0):
                    self.transition("RECOVERED", t)
                    self.floor_since = None
                    events.append(Event("RECOVERED", t, self.event_id, {"reason": "observed_upright"}))
            else:
                self.upright_since = None
        return events

    def break_upright_hold(self):
        """Identity became uncertain (re-acquired / helper swapped in): restart the recovery hold."""
        self.upright_since = None

    def confirm_safe(self, t, event_id):
        if event_id == self.event_id and self.state in ("SUSPECTED_FALL", "VERIFYING", "ALERT"):
            self.cooldown_until = t+self.c.cooldown_s
            self.floor_since = None
            self.transition("RECOVERED", t)
            return True
        return False
