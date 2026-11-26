import math
import pytest
from src.config import Config
from src.convulsion import ConvulsionDetector
from src.engine import Engine
from src.state_machine import FallFSM
from tests.test_engine import skeleton


def lying_thrash(t, hz=4.0, amp=0.08, hip_drift=0.0):
    pts = skeleton('LYING')
    s = math.sin(2 * math.pi * hz * t)
    for i in (15, 16, 27, 28, 25, 26):
        pts[i] = [pts[i][0], pts[i][1] + amp * s * (1 if i % 2 else -1), 0, 1]
    pts[13] = [pts[13][0], pts[13][1] + amp * s, 0, 1]
    pts[14] = [pts[14][0], pts[14][1] - amp * s, 0, 1]
    if hip_drift:
        for i in (11, 12, 23, 24, 25, 26, 27, 28, 13, 14, 15, 16):
            pts[i] = [pts[i][0] + hip_drift * t, pts[i][1], 0, 1]
    return pts


def run_detector(frames, **kw):
    d = ConvulsionDetector(Config(**kw))
    out = None
    for i in range(frames):
        t = i * 0.05
        out = d.update(t, lying_thrash(t), 480, 480, 0.25, True)
    return out


def test_rhythmic_limb_oscillation_on_floor_is_convulsion():
    out = run_detector(80)
    assert out['convulsing'] and out['oscillating_joints'] >= 2
    assert 2.0 <= out['rate_hz'] <= 9.0


def test_still_or_slow_floor_movement_is_not_convulsion():
    d = ConvulsionDetector(Config())
    for i in range(80):
        t = i * 0.05
        out = d.update(t, skeleton('LYING'), 480, 480, 0.25, True)
    assert not out['convulsing']
    d = ConvulsionDetector(Config())
    for i in range(80):
        t = i * 0.05
        out = d.update(t, lying_thrash(t, hz=0.4, amp=0.08), 480, 480, 0.25, True)  # slow stretch/roll
    assert not out['convulsing']


def test_landmark_jitter_is_not_convulsion():
    d = ConvulsionDetector(Config())
    for i in range(80):
        t = i * 0.05
        out = d.update(t, lying_thrash(t, hz=4.0, amp=0.01), 480, 480, 0.25, True)
    assert not out['convulsing']


def test_not_grounded_never_convulsion():
    d = ConvulsionDetector(Config())
    for i in range(80):
        t = i * 0.05
        out = d.update(t, lying_thrash(t), 480, 480, 0.25, False)
    assert not out['convulsing']


def test_fsm_alerts_on_post_fall_convulsion_instead_of_cancelling():
    f = FallFSM(Config())
    f.update(0, True, 'LYING', 1, True)
    ev = []
    for i in range(1, 30):
        ev += f.update(i * 0.1, False, 'LYING', 2.0, True, convulsing=i > 10)  # moving fast: not immobile
    alerts = [e for e in ev if e.kind == 'POSSIBLE_FALL']
    assert alerts and alerts[0].details['basis'] == 'convulsion'
    assert f.state == 'ALERT'


def test_moving_on_floor_without_rising_becomes_entrapment_alert_not_timeout_cancel():
    f = FallFSM(Config(entrapment_s=8.0, verification_timeout_s=5.0))
    f.update(0, True, 'LYING', 1, True)
    kinds = []
    for i in range(1, 120):
        kinds += [(e.kind, e.details.get('basis')) for e in f.update(i * 0.1, False, 'LYING', 1.0, True)]
    assert ('UNVERIFIED_CANDIDATE', None) not in kinds
    assert ('POSSIBLE_FALL', 'unrecovered_on_floor') in kinds


def alert_fsm():
    f = FallFSM(Config(verification_s=0.3, recovery_hold_s=3.0))
    f.update(0, True, 'LYING', 1, True)
    f.update(0.1, False, 'LYING', 0, True)
    f.update(0.6, False, 'LYING', 0, True)
    assert f.state == 'ALERT'
    return f


def test_alert_not_cleared_by_occlusion_or_helpers_or_single_upright_frame():
    f = alert_fsm()
    f.note_people(1.0, True)
    assert f.assisted
    for t in (1.0, 5.0, 12.0, 30.0):                      # occluded / unreliable observations
        f.update(t, False, 'UNKNOWN', 0, False)
    assert f.state == 'ALERT'
    f.update(31.0, False, 'STANDING', 0, True)             # a single upright frame (maybe the helper)
    assert f.state == 'ALERT'
    f.update(31.2, False, 'LYING', 0, True)                # back down resets the hold
    f.update(32.0, False, 'STANDING', 0, True)
    f.update(34.5, False, 'STANDING', 0, True)
    assert f.state == 'ALERT'


def test_alert_clears_only_after_uninterrupted_upright_hold_or_caregiver_confirm():
    f = alert_fsm()
    for t in (10.0, 11.0, 12.0):
        f.update(t, False, 'STANDING', 0, True)
    assert f.state == 'ALERT'
    ev = f.update(13.1, False, 'STANDING', 0, True)
    assert f.state == 'RECOVERED' and ev[0].details['reason'] == 'observed_upright'
    g = alert_fsm()
    assert g.confirm_safe(2.0, g.event_id) and g.state == 'RECOVERED'


def test_identity_reacquisition_restarts_recovery_hold():
    f = alert_fsm()
    f.update(10.0, False, 'STANDING', 0, True)
    f.update(12.0, False, 'STANDING', 0, True)
    f.break_upright_hold()                                  # tracker re-acquired (maybe a helper now)
    f.update(13.5, False, 'STANDING', 0, True)
    assert f.state == 'ALERT'


def test_engine_reports_lock_and_convulsion_fields_end_to_end():
    e = Engine(Config(verification_s=0.3, ml_model_path=''))
    t = 0.0
    for _ in range(12):
        e.process(t, skeleton(), 480, 480)
        t += 0.05
    last = None
    for _ in range(120):
        last = e.process(t, lying_thrash(t), 480, 480, people_count=1)
        t += 0.05
    assert 'convulsion' in last and 'alert_locked' in last
    assert last['convulsion']['oscillating_joints'] >= 2
    assert last['fsm'] in ('ALERT', 'VERIFYING', 'SUSPECTED_FALL', 'NORMAL')
    if last['fsm'] == 'ALERT':
        # now helpers swarm in and fully occlude: ALERT must stay latched
        for _ in range(100):
            last = e.process(t, None, 480, 480, 'MULTIPLE_PEOPLE_WAITING', people_count=3)
            t += 0.05
        assert last['fsm'] == 'ALERT' and last['alert_locked'] and last['assisted']


def test_convulsion_on_floor_from_normal_state_escalates_directly_to_alert():
    """Stroke/seizure without a fast standing-to-floor drop must still escalate NORMAL -> ALERT."""
    f = FallFSM(Config())
    ev = f.update(9.64, False, 'COLLAPSED_BODY', 1.8, True, convulsing=True)
    assert f.state == 'ALERT'
    assert f.alert_locked
    assert f.alert_basis == 'convulsion'
    assert any(e.kind == 'POSSIBLE_FALL' and e.details.get('basis') == 'convulsion' for e in ev)


def test_cancelled_sitting_candidate_does_not_blackout_real_fall_for_30s():
    """A brief SITTING cancellation (e.g. slumping off hammock/chair) must not blind the FSM for 30s."""
    f = FallFSM(Config(verification_s=0.3, cooldown_s=30.0, cancel_cooldown_s=1.5))
    f.update(1.0, True, 'LYING', 1.0, True)
    rec = f.update(1.2, False, 'SITTING', 0.2, True)
    assert rec[0].kind == 'RECOVERED'
    # Transition RECOVERED -> NORMAL at t=1.3
    f.update(1.3, False, 'SITTING', 0.2, True)
    assert f.state == 'NORMAL'
    # At t=3.5 (only 2.3s later, well inside 30s), real stroke collapse happens:
    ev = f.update(3.5, True, 'COLLAPSED_BODY', 0.5, True)
    assert f.state == 'SUSPECTED_FALL' and ev[0].kind == 'SUSPECTED_FALL'
    f.update(3.6, False, 'COLLAPSED_BODY', 0.05, True)
    alert = f.update(4.0, False, 'COLLAPSED_BODY', 0.05, True)
    assert f.state == 'ALERT' and alert[0].kind == 'POSSIBLE_FALL'


def test_angled_cctv_diagonal_lying_uses_3d_lean_instead_of_unknown():
    """High-angle CCTV diagonal lying has large 2D leg_vertical but horizontal 3D lean."""
    from dataclasses import replace
    from src.posture import classify
    from tests.test_engine import feature
    f = replace(feature('LYING'), lean=48.0, z_lean_3d=76.0, aspect=1.25, leg_vertical=1.3)
    assert classify(f, Config()) == 'LYING'


def test_inverted_torso_and_head_below_shoulders_never_classify_as_standing():
    """Backward fall off a chair facing a high-angle camera must not flicker to STANDING."""
    from dataclasses import replace
    from src.posture import classify
    from tests.test_engine import feature
    inverted = replace(feature('STANDING'), torso_inverted=True)
    assert classify(inverted, Config()) == 'LYING'
    head_down = replace(feature('STANDING'), head_droop=0.18)
    assert classify(head_down, Config()) != 'STANDING'


def test_slumped_seated_head_droop_triggers_stroke_slump_alert_after_upright():
    """Wall-slide or seated stroke slump (chin to chest + immobile) alerts without a fast drop."""
    f = FallFSM(Config(slump_alert_s=3.5))
    # Previously observed upright walking/standing
    f.update(1.0, False, 'STANDING', 0.4, True)
    # Slowly slides into SLUMPED immobile posture (no rapid fall candidate)
    alerts = []
    for i in range(45):
        t = 2.0 + i * 0.1
        alerts += [e for e in f.update(t, False, 'SLUMPED', 0.08, True) if e.kind == 'POSSIBLE_FALL']
    assert f.state == 'ALERT'
    assert f.alert_basis == 'stroke_slump'
    assert alerts and alerts[0].details.get('basis') == 'stroke_slump'


def test_slow_wall_slide_collapsed_torso_triggers_slow_collapse_alert():
    """Slow wall-slide ending in immobile COLLAPSED_TORSO after upright triggers slow_collapse."""
    f = FallFSM(Config(slump_alert_s=3.5))
    f.update(1.0, False, 'STANDING', 0.5, True)
    alerts = []
    for i in range(45):
        t = 5.0 + i * 0.1
        alerts += [e for e in f.update(t, False, 'COLLAPSED_TORSO', 0.10, True) if e.kind == 'POSSIBLE_FALL']
    assert f.state == 'ALERT'
    assert f.alert_basis == 'slow_collapse'
    assert alerts and alerts[0].details.get('basis') == 'slow_collapse'


