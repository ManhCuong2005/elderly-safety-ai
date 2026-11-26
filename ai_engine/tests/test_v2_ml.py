"""Unit & integration tests for V2 ML Engine, Bending ADL, Grace Period, Auto Re-acquisition, Filtering, and Activity Monitoring."""
from types import SimpleNamespace
import time
import numpy as np
import pytest
from pathlib import Path
from src.activity import ActivityTracker
from src.config import Config
from src.engine import Engine
from src.features import extract
from src.ml import FEATURE_NAMES, FallActivityClassifier, build_feature_vector, kinematic_risk_score
from src.pose import LandmarkSmoother, PoseTracker
from src.posture import classify

ENGINE_DIR = Path(__file__).resolve().parents[1]


def make_pose(kind="STANDING", dx=0.0, dy=0.0):
    points = [[0.5 + dx, 0.5 + dy, 0.0, 1.0] for _ in range(33)]
    if kind == "STANDING":
        coords = {
            0: (0.50, 0.12),
            11: (0.45, 0.22), 12: (0.55, 0.22),
            23: (0.45, 0.48), 24: (0.55, 0.48),
            25: (0.45, 0.70), 26: (0.55, 0.70),
            27: (0.45, 0.92), 28: (0.55, 0.92),
        }
    elif kind == "BENDING":
        # Forward hip bend (~55 deg torso lean), straight legs (knee ~170 deg), hip angle ~100 deg
        coords = {
            0: (0.20, 0.42),
            11: (0.28, 0.38), 12: (0.30, 0.40),
            23: (0.50, 0.50), 24: (0.52, 0.50),
            25: (0.50, 0.72), 26: (0.52, 0.72),
            27: (0.50, 0.94), 28: (0.52, 0.94),
        }
    elif kind == "SITTING":
        coords = {
            0: (0.50, 0.14),
            11: (0.45, 0.22), 12: (0.55, 0.22),
            23: (0.45, 0.46), 24: (0.55, 0.46),
            25: (0.65, 0.46), 26: (0.75, 0.46),
            27: (0.65, 0.72), 28: (0.75, 0.72),
        }
    else:  # LYING
        coords = {
            0: (0.14, 0.76),
            11: (0.22, 0.74), 12: (0.22, 0.80),
            23: (0.46, 0.74), 24: (0.46, 0.80),
            25: (0.66, 0.74), 26: (0.66, 0.80),
            27: (0.88, 0.74), 28: (0.88, 0.80),
        }
    for idx, (x, y) in coords.items():
        points[idx] = [x + dx, y + dy, 0.0, 1.0]
    return points


def test_bending_adl_is_classified_when_enabled():
    cfg_v1 = Config()
    cfg_v2 = Config(enable_bending=True)
    f = extract(make_pose("BENDING"), 640, 480, cfg_v2)
    assert f is not None
    assert classify(f, cfg_v1) == "UNKNOWN"
    assert classify(f, cfg_v2) == "BENDING"


def test_grace_period_preserves_motion_window_across_short_occlusion():
    cfg = Config(grace_period_s=0.45, visibility=0.5)
    engine = Engine(cfg)
    for i in range(6):
        engine.process(i * 0.1, make_pose("STANDING"), 640, 480)
    # 2 dropped frames (0.2s < grace_period_s=0.45s) must NOT clear MotionWindow
    r_miss1 = engine.process(0.6, None, 640, 480)
    r_miss2 = engine.process(0.7, None, 640, 480)
    assert r_miss1["person_status"] == "PERSON_NOT_DETECTED"
    assert len(engine.motion.samples) == 6
    # Person reappears collapsed on floor -> prior_upright & hip_drop survive!
    r_fall = engine.process(0.8, make_pose("LYING"), 640, 480)
    assert r_fall["motion"]["prior_upright"] is True
    assert r_fall["motion"]["hip_drop"] > 0.5
    assert r_fall["motion"]["occlusion_ratio"] > 0.0


def test_long_absence_beyond_grace_period_still_resets_motion():
    cfg = Config(grace_period_s=0.45, visibility=0.5)
    engine = Engine(cfg)
    engine.process(0.0, make_pose("STANDING"), 640, 480)
    engine.process(0.1, make_pose("STANDING"), 640, 480)
    engine.process(0.8, None, 640, 480)
    assert len(engine.motion.samples) == 0


def test_auto_reacquire_recovers_without_manual_reset_and_avoids_fake_fall():
    cfg = Config(auto_reacquire=True, identity_loss_s=1.0)
    t = object.__new__(PoseTracker)
    t.c = cfg
    t.last_ms = -1
    t.reset_identity()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    def ns_person(x=0.5):
        pts = [SimpleNamespace(x=x, y=0.5, z=0.0, visibility=1.0, presence=1.0) for _ in range(33)]
        for j in (11, 12):
            pts[j].y = 0.25
        for j in (23, 24):
            pts[j].y = 0.50
        return pts

    t.poses = [ns_person(0.2)]
    t.detector = SimpleNamespace(detect_for_video=lambda img, ms: SimpleNamespace(pose_landmarks=t.poses, pose_world_landmarks=[]))
    assert t.process(frame, 0.0)[0] is not None
    t.poses = []
    assert t.process(frame, 2.0)[0] is None
    assert not t.locked
    t.poses = [ns_person(0.8)]
    pose, reason = t.process(frame, 2.1)
    assert pose is not None and reason == "REACQUIRED"


def test_landmark_smoother_reduces_jitter():
    smoother = LandmarkSmoother(tau_s=0.1)
    p0 = make_pose("STANDING", dx=0.0)
    p1 = make_pose("STANDING", dx=0.05)
    out0 = smoother.update(p0, 0.0)
    out1 = smoother.update(p1, 0.03)
    assert out0[23][0] == pytest.approx(p0[23][0])
    # Smoothed x must lie strictly between p0 and p1
    assert p0[23][0] < out1[23][0] < p1[23][0]


def test_activity_tracker_counts_durations_and_sit_to_stand():
    tracker = ActivityTracker()
    tracker.update(0.0, "SITTING")
    tracker.update(1.0, "SITTING")
    tracker.update(2.0, "STANDING")
    tracker.update(3.0, "WALKING")
    tracker.update(4.0, "SITTING")
    s = tracker.summary()
    assert s["sit_to_stand_count"] == 1
    assert s["stand_to_sit_count"] == 1
    assert s["durations_s"]["SITTING"] == pytest.approx(2.0)
    assert s["durations_s"]["STANDING"] == pytest.approx(1.0)
    assert s["durations_s"]["WALKING"] == pytest.approx(1.0)
    assert s["activity_level"] in ("ACTIVE", "MODERATE")


def test_kinematic_feature_vector_and_trained_ml_bundle_end_to_end():
    v2_cfg_path = ENGINE_DIR / "configs" / "v2_ml.json"
    model_path = ENGINE_DIR / "trained_models" / "fall_activity_model.joblib"
    assert v2_cfg_path.is_file() and model_path.is_file()
    cfg = Config.load(v2_cfg_path)
    clf = FallActivityClassifier(model_path)
    assert clf.feature_names == FEATURE_NAMES

    engine = Engine(cfg)
    for i in range(6):
        res = engine.process(i * 0.1, make_pose("STANDING"), 640, 480)
    assert res["algorithm_version"] == "2.0-ml"
    assert 0.0 <= res["fall_score"] <= 1.0
    assert res["ml_prediction"] is not None
    assert "activity_summary" in res

    # Verify fast inference (< 10 ms per frame)
    f = extract(make_pose("LYING"), 640, 480, cfg)
    vec = build_feature_vector(f, engine.motion.update(0.7, f, "LYING"))
    assert vec.shape == (len(FEATURE_NAMES),)
    assert np.isfinite(vec).all()
    t0 = time.perf_counter()
    pred = clf.predict(f, engine.motion.samples[-1][1] and engine.motion.update(0.8, f, "LYING"))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert 0.0 <= pred["fall_prob"] <= 1.0
    assert elapsed_ms < 25.0
    assert 0.0 <= kinematic_risk_score(f, engine.motion.update(0.9, f, "LYING"), "LYING") <= 1.0
