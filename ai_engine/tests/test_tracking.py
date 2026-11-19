from types import SimpleNamespace
import numpy as np
from src.config import Config
from src.pose import PoseTracker


def person(x=.5):
    points=[SimpleNamespace(x=x,y=.5,z=0,visibility=1,presence=1) for _ in range(33)]
    for j in [11,12]:points[j].y=.25
    for j in [23,24]:points[j].y=.5
    return points


def tracker():
    result=object.__new__(PoseTracker)
    result.c=Config()
    result.last_ms=-1
    result.reset_identity()
    result.poses=[]
    result.detector=SimpleNamespace(detect_for_video=lambda image,ms:SimpleNamespace(pose_landmarks=result.poses))
    return result


def test_one_ambiguous_frame_does_not_permanently_lock_tracking():
    t=tracker();frame=np.zeros((100,100,3),dtype=np.uint8)
    t.poses=[person()];assert t.process(frame,0)[0] is not None
    t.poses=[person(),person(.52)];assert t.process(frame,.1)[0] is None
    assert not t.locked
    t.poses=[person()];assert t.process(frame,.2)[0] is not None


def test_multiple_people_before_initial_target_are_not_silently_selected():
    t=tracker();t.poses=[person(.2),person(.8)]
    assert t.process(np.zeros((100,100,3),dtype=np.uint8),0)[0] is None
    assert t.center is None


def test_only_one_continuity_match_can_be_selected_among_distant_people():
    t=tracker();frame=np.zeros((100,100,3),dtype=np.uint8)
    t.poses=[person(.2)];t.process(frame,0)
    t.poses=[person(.21),person(.9)]
    assert t.process(frame,.1)[0][23][0]==.21


def test_long_absence_requires_explicit_reacquisition():
    t=tracker();frame=np.zeros((100,100,3),dtype=np.uint8)
    t.poses=[person()];t.process(frame,0)
    t.poses=[];t.process(frame,4)
    t.poses=[person()];pose,reason=t.process(frame,4.1)
    assert pose is None and reason=='IDENTITY_RESET_REQUIRED'
    t.reset_identity();assert t.process(frame,4.2)[0] is not None
