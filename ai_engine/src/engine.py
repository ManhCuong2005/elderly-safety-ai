from dataclasses import asdict
import math
from .config import Config
from .features import extract, extract_core
from .posture import classify, StablePosture
from .motion import Motion, MotionWindow
from .fall_detection import candidate
from .state_machine import Event, FallFSM
from .activity import ActivityTracker
from .ml import FallActivityClassifier, kinematic_risk_score
from .convulsion import ConvulsionDetector
from .state_machine import FLOOR_POSTURES


class Engine:
    def __init__(self, config=None, classifier=None):
        self.c = config or Config()
        self.posture = StablePosture(self.c)
        self.motion = MotionWindow(self.c)
        self.fsm = FallFSM(self.c)
        self.activity = ActivityTracker()
        self.classifier = classifier
        if self.classifier is None and getattr(self.c, "ml_model_path", ""):
            self.classifier = FallActivityClassifier(self.c.ml_model_path)
        self.last_t = self.last_seen = self.last_valid_t = None
        self.lying_since = self.quiet_since = None
        self.latches = set()
        self.last_posture = "UNKNOWN"
        self.ml_hits = 0
        self.convulsion = ConvulsionDetector(self.c)
        self.convulsion_latched = False

    def process(self, t, landmarks=None, width=640, height=480, reason="PERSON_NOT_DETECTED", world_landmarks=None,
                people_count=None):
        if not math.isfinite(t) or t < 0 or (self.last_t is not None and t <= self.last_t):
            raise ValueError("Timestamp must be finite, non-negative and strictly increasing")
        effective_gap = max(self.c.max_gap_s, getattr(self.c, "grace_period_s", 0.0))
        gap = self.last_t is not None and t - self.last_t > effective_gap
        self.last_t = t
        if reason == "REACQUIRED":
            # Target jumped or returned after long absence: reset temporal evidence so no fake drop fires.
            self.motion.reset()
            self.posture.reset()
            self.ml_hits = 0
            # Identity may now belong to a helper: an ALERT must not be cleared by this new target.
            self.fsm.break_upright_hold()
        full = extract(landmarks, width, height, self.c, world_landmarks=world_landmarks)
        f = full or extract_core(landmarks, width, height, self.c, world_landmarks=world_landmarks)
        grace_s = getattr(self.c, "grace_period_s", 0.0)
        within_grace = (
            grace_s > 0
            and f is None
            and not gap
            and self.last_valid_t is not None
            and (t - self.last_valid_t) <= grace_s
        )
        if gap or (f is None and not within_grace):
            self.motion.reset()
            self.posture.reset()
            self.lying_since = self.quiet_since = None
            self.latches.clear()
            self.ml_hits = 0
        elif within_grace:
            # Brief occlusion during a fall: keep sliding window intact and record occlusion marker.
            self.motion.record_missing(t)
        raw = classify(f, self.c)
        # Torso evidence can verify a rapid collapse even if legs are occluded.
        # UNKNOWN remains the public posture; this does not claim observed lying.
        fall_posture = raw
        if f and f.coverage == 'CORE_ONLY' and f.lean >= self.c.core_fall_lean and f.aspect <= self.c.core_fall_aspect:
            fall_posture = 'COLLAPSED_TORSO'
        elif f and f.coverage == 'FULL' and raw == 'UNKNOWN' and f.aspect <= self.c.collapsed_body_aspect and f.leg_vertical <= self.c.collapsed_body_leg_vertical:
            fall_posture = 'COLLAPSED_BODY'
        stable = self.posture.update(raw, t, f) if not within_grace else self.posture.value
        # Public label debounce must not erase a short, multi-frame upright precursor.
        motion = self.motion.update(t, f, raw) if f else Motion()
        if f is not None:
            self.last_valid_t = t

        if f is not None and getattr(self.c, "enable_slump_detection", False):
            # Bending forward over a desk/table with head dropped below shoulders while motionless
            # is a forward stroke slump, not an active brief item pickup.
            if fall_posture == "BENDING" and f.head_droop >= 0.0 and motion.speed < self.c.immobile_speed:
                fall_posture = "SLUMPED"
        ml_pred = None
        if self.classifier is not None and f is not None:
            ml_pred = self.classifier.predict(f, motion)
            fall_score = ml_pred["fall_prob"]
            threshold = self.c.ml_fall_threshold
            if fall_score >= threshold and stable not in ("STANDING", "WALKING"):
                self.ml_hits += 1
            else:
                self.ml_hits = 0
            is_candidate = self.ml_hits >= self.c.ml_min_consecutive
            # Allow FSM immobility verification when ML or active VERIFYING observes a collapsed/floor state
            collapsed_geom = (
                f.aspect <= 1.55
                or f.lean >= 42.0
                or f.z_lean_3d >= 42.0
                or f.hip_y >= 0.55
                or f.head_droop >= 0.0
                or f.torso_inverted
            )
            if fall_posture == "UNKNOWN" and collapsed_geom and (
                fall_score >= threshold * 0.7 or self.fsm.state in ("SUSPECTED_FALL", "VERIFYING")
            ):
                fall_posture = "COLLAPSED_BODY"
        else:
            fall_score = kinematic_risk_score(f, motion, fall_posture) if f is not None else 0.0
            is_candidate = candidate(f, motion, fall_posture, self.c)

        multiple = (people_count is not None and people_count > 1) or str(reason).startswith("MULTIPLE_PEOPLE")
        events = self.fsm.note_people(t, multiple)

        effective_fall_posture = stable if (fall_posture == "UNKNOWN" and stable in ("LYING", "SLUMPED")) else fall_posture
        on_floor = f is not None and (effective_fall_posture in FLOOR_POSTURES)
        conv = self.convulsion.update(t, landmarks, width, height, f.torso if f else None, on_floor)
        if within_grace:
            conv = self.convulsion.last
        if not on_floor and not within_grace:
            self.convulsion_latched = False
        elif conv.get("convulsing") and not self.convulsion_latched:
            self.convulsion_latched = True
            events.append(Event("CONVULSION_SUSPECTED", t, details=dict(conv)))

        events += self.fsm.update(
            t, is_candidate, effective_fall_posture, motion.speed, f is not None and not gap,
            within_grace=within_grace, convulsing=bool(conv.get("convulsing")),
        )
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
                if since is not None and t - since >= limit and kind not in self.latches:
                    self.latches.add(kind)
                    events.append(Event(kind, t, details={"duration_s": t - since}))
        elif not within_grace:
            self.lying_since = self.quiet_since = None
            self.latches.clear()
        if f:
            self.last_seen = t
        for event in events:
            event.details['pose_coverage'] = f.coverage if f else 'NONE'
            event.details['fall_score'] = round(float(fall_score), 4)
        label = "WALKING" if stable == "STANDING" and motion.walking else stable
        self.activity.update(t, label)
        if label != self.last_posture:
            events.append(Event("POSTURE_CHANGE", t, details={"from": self.last_posture, "to": label}))
            self.last_posture = label
        return {"timestamp_s": t, "posture": label, "raw_posture": raw,
                "person_status": "DETECTED" if f else reason,
                "fsm": self.fsm.state, "active_event_id": self.fsm.event_id,
                "alert_locked": self.fsm.alert_locked, "assisted": self.fsm.assisted,
                "alert_basis": self.fsm.alert_basis, "convulsion": conv,
                "last_seen_s": self.last_seen, "motion": asdict(motion),
                "features": asdict(f) if f else None,
                "pose_coverage": f.coverage if f else 'NONE',
                "smoothed_lean": self.posture.smooth,
                "fall_score": round(float(fall_score), 4),
                "ml_prediction": ml_pred,
                "activity_summary": self.activity.summary(),
                "algorithm_version": "2.0-ml" if self.classifier is not None else "1.4",
                "events": [asdict(e) for e in events]}
