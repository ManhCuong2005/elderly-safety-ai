import pytest
from src.config import Config
from src.features import extract, extract_core
from src.posture import classify
from src.engine import Engine


def pose(lying=False, confidence=1):
    points=[[.5,.5,0,confidence] for _ in range(33)]
    xy={11:(.45,.2),12:(.55,.2),23:(.45,.45),24:(.55,.45),25:(.45,.65),26:(.55,.65),27:(.45,.9),28:(.55,.9)}
    if lying:xy={11:(.2,.7),12:(.2,.8),23:(.45,.7),24:(.45,.8),25:(.65,.7),26:(.65,.8),27:(.9,.7),28:(.9,.8)}
    for i,(x,y) in xy.items():points[i]=[x,y,0,confidence]
    return points


def hide_legs(p):
    for i in [25,26,27,28]:p[i][3]=.1
    return p


def test_occluded_legs_do_not_invent_a_lying_posture():
    p=hide_legs(pose(True))
    assert extract(p,480,480,Config()) is None
    core=extract_core(p,480,480,Config())
    assert core.coverage=='CORE_ONLY' and not core.both_legs_visible
    assert classify(core,Config())=='UNKNOWN'


def test_partial_torso_needs_stronger_confidence_and_must_be_inside_frame():
    p=hide_legs(pose(True,.7))
    assert extract_core(p,480,480,Config()) is None
    p=hide_legs(pose(True));p[11][1]=1.1
    assert extract_core(p,480,480,Config()) is None


def test_collapsed_torso_requires_prior_motion_and_verification():
    c=Config(verification_s=.3)
    engine=Engine(c)
    for i in range(5):engine.process(i*.1,pose(),480,480)
    events=[]
    for i in range(5,15):events+=engine.process(i*.1,hide_legs(pose(True)),480,480)['events']
    alerts=[e for e in events if e['kind']=='POSSIBLE_FALL']
    assert len(alerts)==1
    assert alerts[0]['details']['pose_coverage']=='CORE_ONLY'


def test_static_partial_torso_never_becomes_fall_or_inactivity_by_itself():
    engine=Engine(Config(lying_long_s=.3,inactivity_s=.3))
    for i in range(30):
        r=engine.process(i*.1,hide_legs(pose(True)),480,480)
        assert r['posture']=='UNKNOWN'
        assert not any(e['kind'] in ['POSSIBLE_FALL','ABNORMAL_INACTIVITY','LYING_TOO_LONG'] for e in r['events'])


def test_caregiver_can_confirm_safety_while_warning_is_still_verifying():
    from src.state_machine import FallFSM
    fsm=FallFSM(Config())
    event=fsm.update(0,True,'COLLAPSED_TORSO',1,True)[0]
    assert fsm.confirm_safe(.1,event.event_id)
    assert fsm.state=='RECOVERED'
