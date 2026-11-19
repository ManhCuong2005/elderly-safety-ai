import numpy as np
import pytest
from src.camera import crop_rgbd,input_layout


def test_composite_crop_keeps_exact_rgb_pixels_and_original_height():
    frame=np.zeros((480,1280,3),dtype=np.uint8);frame[:,640:]=[12,34,56]
    rgb=crop_rgbd(frame)
    assert rgb.shape==(480,640,3)
    assert np.array_equal(rgb,frame[:,640:])


def test_normal_rgb_does_not_get_silently_cropped():
    assert input_layout('ordinary-video.mp4')=='rgb'
    assert input_layout(0)=='rgb'


def test_invalid_composite_dimensions_are_rejected():
    with pytest.raises(ValueError):crop_rgbd(np.zeros((480,640,3),dtype=np.uint8))


def test_legacy_composite_landmarks_cannot_be_reused_as_rgb_accuracy(tmp_path):
    import json
    from src.evaluation import replay
    from src.config import Config
    cache=tmp_path/'old.jsonl'
    cache.write_text(json.dumps({'t':0,'landmarks':None,'width':1280,'height':480,'reason':'PERSON_NOT_DETECTED'})+'\n')
    with pytest.raises(ValueError,match='composite'):
        replay({'input_layout':'ur-rgbd'},cache,Config())
