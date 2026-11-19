from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import numpy as np
import pytest
from src.config import Config
from src.features import angle, extract, Features
from src.posture import classify, StablePosture
from src.motion import MotionWindow
from src.fall_detection import candidate
from src.state_machine import FallFSM
from src.engine import Engine
from src.evaluation import metrics
from src.firebase import validate_id


def skeleton(posture='STANDING', dx=0, dy=0):
    points = [[.5,.5,0,1] for _ in range(33)]
    if posture == 'STANDING':
        coords = {11:(.45,.2),12:(.55,.2),23:(.45,.45),24:(.55,.45),25:(.45,.65),26:(.55,.65),27:(.45,.9),28:(.55,.9)}
    elif posture == 'SITTING':
        coords = {11:(.45,.2),12:(.55,.2),23:(.45,.45),24:(.55,.45),25:(.65,.45),26:(.75,.45),27:(.65,.7),28:(.75,.7)}
    else:
        coords = {11:(.2,.7),12:(.2,.8),23:(.45,.7),24:(.45,.8),25:(.65,.7),26:(.65,.8),27:(.9,.7),28:(.9,.8)}
    for i,(x,y) in coords.items():
        points[i] = [x+dx,y+dy,0,1]
    return points


def feature(posture='STANDING', dx=0,dy=0):
    return extract(skeleton(posture,dx,dy), 480,480,Config())


@pytest.mark.parametrize('a,b,c,expected', [([1,0],[0,0],[0,1],90),([1,0],[0,0],[-1,0],180),([1,0],[0,0],[2,0],0)])
def test_angles(a,b,c,expected):
    assert angle(a,b,c)==pytest.approx(expected)


def test_zero_length_angle():
    assert angle([0,0],[0,0],[1,0]) is None


@pytest.mark.parametrize('posture',['STANDING','SITTING','LYING'])
def test_posture_geometry(posture):
    assert classify(feature(posture), Config())==posture


def test_lying_requires_multiple_signals():
    assert classify(replace(feature('STANDING'),lean=85),Config())=='UNKNOWN'


def test_extended_leg_geometry_supports_upright_when_projected_knee_is_bent():
    f=replace(feature('STANDING'),knee=135)
    assert classify(f,Config())=='STANDING'
    assert classify(replace(f,leg_vertical=.7,thigh_vertical=0,hip_angle=120),Config())=='SITTING'


def test_upright_precursor_requires_multiple_frames_over_real_time():
    w=MotionWindow(Config())
    w.update(0,feature(),'STANDING')
    w.update(.04,feature(),'STANDING')
    assert not w.update(.2,feature('LYING'),'LYING').prior_upright


def test_motion_uses_raw_precursor_while_public_label_is_debouncing():
    e=Engine(Config(posture_debounce_s=.5))
    for i in range(3):e.process(i*.1,skeleton(),480,480)
    r=e.process(.3,skeleton('LYING'),480,480)
    assert r['posture']=='UNKNOWN'
    assert any(v['kind']=='SUSPECTED_FALL' for v in r['events'])


def test_aspect_correction():
    p = skeleton('LYING')
    for row in p: row[0] *= .75
    corrected=extract(p,640,480,Config())
    assert corrected.lean==pytest.approx(feature('LYING').lean)
    assert corrected.torso==pytest.approx(feature('LYING').torso)


@pytest.mark.parametrize('bad',[None,[],[[0,0,0,1]]*32,[[math.nan,0,0,1]]*33,[[0,0,0,1]]*33])
def test_missing_invalid_geometry(bad):
    assert extract(bad,640,480,Config()) is None


def test_visibility_gate():
    p=skeleton();p[27][3]=.2;p[28][3]=.2
    assert extract(p,640,480,Config()) is None


def test_one_visible_leg_is_sufficient_without_inventing_missing_joints():
    p=skeleton();p[27][3]=.2
    f=extract(p,480,480,Config())
    assert f is not None and classify(f,Config())=='STANDING'
    assert len(f.points)==4


def test_debounce_and_smoothing():
    stable=StablePosture(Config())
    assert stable.update('STANDING',0,feature())=='UNKNOWN'
    assert stable.update('STANDING',.3,feature())=='STANDING'
    assert stable.update('LYING',.35,feature('LYING'))=='STANDING'
    assert 0 < stable.smooth < 90
    assert stable.update('UNKNOWN',.4,None)=='UNKNOWN'


def test_timestamp_normalized_velocity_and_window():
    c=Config()
    window=MotionWindow(c)
    window.update(0,feature(), 'STANDING')
    m=window.update(.1,feature(dy=.025),'STANDING')
    assert m.speed==pytest.approx(1)
    for i in range(2,40):window.update(i*.1,feature(),'STANDING')
    assert window.samples[0][0]>=3.9-c.window_s-.001


def test_gap_discards_velocity():
    window=MotionWindow(Config())
    window.update(0,feature(),'STANDING')
    assert window.update(2,feature(dy=.3),'LYING').speed==0


def test_standing_sway_is_not_walking():
    w=MotionWindow(Config())
    for i in range(40):m=w.update(i*.05,feature(dx=.005*math.sin(i)), 'STANDING')
    assert not m.walking


def test_walking_requires_alternation_over_time():
    w=MotionWindow(Config())
    for i in range(50):
        f=replace(feature(dx=i*.002),ankle_delta=.3*math.sin(i*.5))
        m=w.update(i*.05,f,'STANDING')
    assert m.walking


def test_fall_candidate_requires_prior_upright_and_combined_signals():
    w=MotionWindow(Config())
    w.update(0,feature(),'STANDING')
    w.update(.1,feature(),'STANDING')
    f=feature('LYING')
    m=w.update(.3,f,'LYING')
    assert candidate(f,m,'LYING',Config())
    assert not candidate(f,replace(m,prior_upright=False),'LYING',Config())
    assert not candidate(f,m,'SITTING',Config())
    assert not candidate(f,replace(m,hip_drop=0),'LYING',Config())


def test_fsm_verifies_once_and_deduplicates():
    f=FallFSM(Config(verification_s=.3))
    events=f.update(0,True,'LYING',1,True)
    event_id=events[0].event_id
    assert f.state=='SUSPECTED_FALL'
    f.update(.1,False,'LYING',0,True)
    assert f.state=='VERIFYING'
    alert=f.update(.5,False,'LYING',0,True)
    assert f.state=='ALERT' and alert[0].kind=='POSSIBLE_FALL'
    assert alert[0].event_id==event_id
    assert f.update(.6,True,'LYING',0,True)==[]
    assert not f.confirm_safe(.7,'wrong-id')
    assert f.confirm_safe(.7,event_id)
    assert f.state=='RECOVERED'
    assert f.update(.8,True,'LYING',0,True)==[]
    assert f.state=='NORMAL'  # cooldown blocks immediate second candidate


def test_missing_observations_never_confirm_fall():
    f=FallFSM(Config())
    f.update(0,True,'LYING',1,True)
    f.update(.1,False,'LYING',0,True)
    for t in [1,2,3,4,6]:
        events=f.update(t,False,'UNKNOWN',0,False)
        assert all(e.kind!='POSSIBLE_FALL' for e in events)
    assert f.state=='RECOVERED'


def test_upright_recovery_cancels_candidate():
    f=FallFSM(Config());f.update(0,True,'LYING',1,True)
    assert f.update(.2,False,'SITTING',0,True)[0].kind=='RECOVERED'


def test_continuity_gap_resets_verification():
    e=Engine(Config(verification_s=.3))
    for i in range(5):e.process(i*.1,skeleton(),480,480)
    e.process(.5,skeleton('LYING'),480,480)
    e.process(.6,skeleton('LYING'),480,480)
    r=e.process(2,skeleton('LYING'),480,480)
    assert not any(v['kind']=='POSSIBLE_FALL' for v in r['events'])


def test_lying_and_inactivity_alert_latches_and_absence_reset():
    e=Engine(Config(lying_long_s=.4,inactivity_s=.4,posture_debounce_s=.1))
    kinds=[]
    for i in range(15):kinds += [x['kind'] for x in e.process(i*.1,skeleton('LYING'),480,480)['events']]
    assert kinds.count('LYING_TOO_LONG')==1 and kinds.count('ABNORMAL_INACTIVITY')==1
    for i in range(15,30):
        r=e.process(i*.1)
        assert r['person_status']=='PERSON_NOT_DETECTED'
        assert not any(v['kind'] in ['LYING_TOO_LONG','ABNORMAL_INACTIVITY','POSSIBLE_FALL'] for v in r['events'])


@pytest.mark.parametrize('t',[0,-1,float('nan'),float('inf')])
def test_invalid_timestamps(t):
    e=Engine();e.process(0)
    with pytest.raises(ValueError):e.process(t)


@pytest.mark.parametrize('kwargs',[{'visibility':2},{'cooldown_s':0},{'max_gap_s':float('nan')},{'window_s':.1},{'verification_s':10}])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):Config(**kwargs)


def test_video_metrics():
    m=metrics([{'label':'FALL','detected':True},{'label':'FALL','detected':False},{'label':'NON_FALL','detected':True},{'label':'NON_FALL','detected':False}])
    assert [m[k] for k in ['tp','fp','fn','tn']]==[1,1,1,1]
    assert m['precision']==m['recall']==m['f1']==.5


@pytest.mark.parametrize('profile',['','a/b','../users','x'*101])
def test_admin_path_validation(profile):
    with pytest.raises(ValueError):validate_id(profile)
