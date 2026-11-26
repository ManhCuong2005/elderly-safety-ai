"""Trained scikit-learn classifier wrapper + continuous kinematic risk score."""
from pathlib import Path
import joblib
import numpy as np
from .features import FEATURE_NAMES, build_feature_vector

ENGINE_ROOT = Path(__file__).resolve().parents[2]


def _clamp01(v):
    return float(max(0.0, min(1.0, v)))


def kinematic_risk_score(features, motion, raw_posture="UNKNOWN"):
    """Interpretable continuous fallback risk score in [0, 1] when no ML model is loaded."""
    if features is None or motion is None:
        return 0.0
    lean_term = _clamp01((max(features.lean, features.z_lean_3d) - 25.0) / 50.0)
    drop_term = _clamp01((max(motion.hip_drop, motion.head_drop * 0.7) - 0.15) / 1.1)
    speed_term = _clamp01((max(motion.hip_down_speed, motion.head_down_speed * 0.7) - 0.2) / 1.5)
    aspect_term = _clamp01((1.6 - features.aspect) / 1.1)
    height_term = _clamp01((0.9 - motion.height_ratio) / 0.5)
    posture_bonus = 0.2 if raw_posture in ("LYING", "COLLAPSED_TORSO", "COLLAPSED_BODY") else 0.0
    score = 0.25 * lean_term + 0.25 * drop_term + 0.20 * speed_term + 0.15 * aspect_term + 0.15 * height_term + posture_bonus
    if raw_posture == "BENDING":
        score *= 0.45
    return round(_clamp01(score), 4)


class FallActivityClassifier:
    """Loads a serialized scikit-learn pipeline bundle and scores live kinematic vectors."""

    def __init__(self, model_path):
        path = Path(model_path)
        if not path.is_absolute():
            path = (ENGINE_ROOT / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"ML classifier bundle missing: {path}")
        bundle = joblib.load(path)
        self.path = path
        self.model = bundle["model"]
        self.feature_names = list(bundle["feature_names"])
        if self.feature_names != FEATURE_NAMES:
            raise ValueError("Feature schema mismatch between ML bundle and runtime features")
        self.model_name = bundle.get("model_name", type(self.model).__name__)
        self.threshold = float(bundle.get("threshold", 0.55))
        self.classes = list(bundle.get("classes", [0, 1]))
        self.fall_class_index = self.classes.index(1) if 1 in self.classes else len(self.classes) - 1
        self.metadata = bundle.get("metadata", {})

    def predict(self, features, motion):
        vec = build_feature_vector(features, motion)
        if vec is None:
            return None
        proba = self.model.predict_proba(vec.reshape(1, -1))[0]
        fall_prob = float(proba[self.fall_class_index])
        return {
            "fall_prob": round(fall_prob, 4),
            "is_fall_frame": fall_prob >= self.threshold,
            "model_name": self.model_name,
            "threshold": self.threshold,
        }
