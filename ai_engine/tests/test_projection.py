from dataclasses import replace
import pytest
from src.config import Config
from src.features import Features
from src.motion import Motion
from src.fall_detection import candidate


def evidence():
    f=Features(.5,.6,.2,40,120,90,1.0,.7,0,((0,0),)*4,1,True,'FULL',.3,.3)
    m=Motion(hip_down_speed=1.4,hip_drop=.8,angle_delta=20,angle_speed=60,prior_upright=True,height_ratio=.5)
    return f,m


def test_foreshortened_collapse_can_warn_without_inventing_horizontal_posture():
    f,m=evidence()
    assert candidate(f,m,'COLLAPSED_BODY',Config())


@pytest.mark.parametrize('changes',[{'height_ratio':.9},{'angle_delta':5},{'hip_down_speed':.1},{'hip_drop':.1},{'prior_upright':False}])
def test_sitting_or_bending_without_joint_collapse_evidence_is_not_a_fall(changes):
    f,m=evidence()
    assert not candidate(f,replace(m,**changes),'COLLAPSED_BODY',Config())


def test_projection_rule_requires_full_observed_limbs():
    f,m=evidence()
    assert not candidate(replace(f,coverage='CORE_ONLY'),m,'COLLAPSED_BODY',Config())


def test_invalid_core_confidence_threshold_is_rejected():
    with pytest.raises(ValueError):Config(core_visibility=2)
