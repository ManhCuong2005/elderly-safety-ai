from dataclasses import asdict
import math
from .config import Config
from .features import extract, extract_core
from .posture import classify, StablePosture
from .motion import Motion, MotionWindow
from .fall_detection import candidate
from .state_machine import Event, FallFSM


class Engine:
    def __init__(self, config=None):
        self.c = config or Config()
        self.posture = StablePosture(self.c)
        self.motion = MotionWindow(self.c)
        self.fsm = FallFSM(self.c)
        self.last_t = self.last_seen = None
        self.lying_since = self.quiet_since = None
        self.latches = set()
        self.last_posture = "UNKNOWN"

    def process(self, t, landmarks=None, width=640, height=480, reason="PERSON_NOT_DETECTED"):
        if not math.isfinite(t) or t < 0 or (self.last_t is not None and t <= self.last_t):
            raise ValueError("Timestamp must be finite, non-negative and strictly increasing")
        gap = self.last_t is not None and t-self.last_t > self.c.max_gap_s
        self.last_t = t
        full = extract(landmarks, width, height, self.c)
        f = full or extract_core(landmarks,width,height,self.c)
        if gap or f is None:
            self.motion.reset()
            self.posture.reset()
            self.lying_since = self.quiet_since = None
            self.latches.clear()
        raw = classify(f, self.c)
        # Torso evidence can verify a rapid collapse even if legs are occluded.
        # UNKNOWN remains the public posture; this does not claim observed lying.
        fall_posture = raw
        if f and f.coverage=='CORE_ONLY' and f.lean>=self.c.core_fall_lean and f.aspect<=self.c.core_fall_aspect:
            fall_posture='COLLAPSED_TORSO'
        elif f and f.coverage=='FULL' and raw=='UNKNOWN' and f.aspect<=self.c.collapsed_body_aspect and f.leg_vertical<=self.c.collapsed_body_leg_vertical:
            fall_posture='COLLAPSED_BODY'
        stable = self.posture.update(raw, t, f)
        # Public label debounce must not erase a short, multi-frame upright precursor.
        motion = self.motion.update(t, f, raw) if f else Motion()
        events = self.fsm.update(t, candidate(f, motion, fall_posture, self.c), fall_posture, motion.speed, f is not None and not gap)
        if full:
            self.last_seen = t
            if stable == "LYING":
                if self.lying_since is None:
                    self.lying_since = t
            else:
                self.lying_since = None
                self.latches.discard("LYING_TOO_LONG")
            if motion.duration > 0 and motion.speed < self.c.immobile_speed:
                if self.quiet_since is None:
                    self.quiet_since = t
            else:
                self.quiet_since = None
                self.latches.discard("ABNORMAL_INACTIVITY")
            for kind, since, limit in [("LYING_TOO_LONG", self.lying_since, self.c.lying_long_s),
                                        ("ABNORMAL_INACTIVITY", self.quiet_since, self.c.inactivity_s)]:
                if since is not None and t-since >= limit and kind not in self.latches:
                    self.latches.add(kind)
                    events.append(Event(kind, t, details={"duration_s": t-since}))
        else:
            self.lying_since=self.quiet_since=None
            self.latches.clear()
        if f:
            self.last_seen=t
        for event in events:
            event.details['pose_coverage']=f.coverage if f else 'NONE'
        label = "WALKING" if stable == "STANDING" and motion.walking else stable
        if label != self.last_posture:
            events.append(Event("POSTURE_CHANGE", t, details={"from": self.last_posture, "to": label}))
            self.last_posture = label
        return {"timestamp_s": t, "posture": label, "raw_posture": raw,
                "person_status": "DETECTED" if f else reason,
                "fsm": self.fsm.state, "active_event_id": self.fsm.event_id,
                "last_seen_s": self.last_seen, "motion": asdict(motion),
                "features": asdict(f) if f else None,
                "pose_coverage": f.coverage if f else 'NONE',
                "smoothed_lean": self.posture.smooth,
                "events": [asdict(e) for e in events]}
