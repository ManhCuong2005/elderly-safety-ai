"""Full VARISHTA-MM50 (up to 450 clips) training pipeline for CameraAI.

Extends the pilot training (which only used 48 manually confirmed clips / 2 train falls)
to all valid VARISHTA-MM50 RGB clips across all 9 activity groups while keeping:
  * strict subject-level train/validation/test isolation (connected_people, seed=37)
  * exact 13-feature SCHEMA compatibility with src.inference.Engine & src.server
  * human-confirmed onset/impact annotations preserved verbatim from confirmed.json
  * automatic kinematic peak-drop annotation for unreviewed Fall clips
  * comparison across Logistic Regression, Random Forest, and MLP Neural Network

Usage on Linux:
  1. Download all 450 VARISHTA clips (if not already in data/raw/varishta/):
       .venv/bin/python -m src.dataset download --all
  2. Run full training & evaluation:
       .venv/bin/python scripts/train_varishta_full.py
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.inference import Engine, SCHEMA
from src.keypoints import get_keypoints, metadata
from src.pose import CONFIG, MODEL, Pose
from src.review import ANNOTATIONS, VIDEOS, annotation
from src.storage import atomic, read_json, rows, safe, sha, write_json, write_rows
from src.train import (
    ARTIFACT,
    FALSE_ALARMS_TARGET,
    MODEL_INFO,
    SPLIT,
    assign_splits,
    compare_validation,
    evaluation,
    make_windows,
    rank,
    related_videos,
    replay,
    training_snapshot,
)

FALL_GROUPS = {"Trip_n_Fall", "Sit_n_Fall", "Walk_n_Fall"}
NO_FALL_GROUPS = {"Walking", "Standing", "Sitting", "Jogging", "Stair_Climbing", "Stair_Descending"}


def auto_annotate_fall(observations, duration_s, cfg):
    """Estimate (onset_s, impact_s) from peak downward hip/shoulder drop + angle change."""
    frames = replay(observations, cfg)
    scored = []
    for row in frames:
        feats = row["features"]
        if feats is None:
            continue
        # SCHEMA: 0=hip_drop, 1=shoulder_drop, 4=hip_peak_down_speed, 6=trunk_angle_change
        hip_drop = float(np.nan_to_num(feats[0], nan=0.0))
        sh_drop = float(np.nan_to_num(feats[1], nan=0.0))
        peak_v = float(np.nan_to_num(feats[4], nan=0.0))
        ang_ch = float(np.nan_to_num(feats[6], nan=0.0))
        score = max(0.0, hip_drop) + max(0.0, sh_drop) + 0.35 * max(0.0, peak_v) + 1.5 * max(0.0, ang_ch)
        scored.append((score, row["t"]))
    if not scored:
        return None
    best_score, impact_t = max(scored, key=lambda x: x[0])
    if best_score < 0.8:
        return None
    onset_t = max(0.5, impact_t - 1.2)
    impact_t = min(duration_s - 0.1, max(onset_t + 0.25, impact_t))
    neg = [[0.0, round(onset_t - 0.5, 3)]] if onset_t >= 2.6 else []
    return {"label": "Fall", "onset_s": round(onset_t, 3), "impact_s": round(impact_t, 3), "negative": neg}


def build_full_clips(max_clips=None):
    confirmed = read_json(ANNOTATIONS, {})
    raw_videos = rows(VIDEOS)
    present = []
    for v in raw_videos:
        if v["status"] == "exclude" or v["subject_id"] == "unknown" or not v["duration_s"]:
            continue
        path = safe(v["relative_path"])
        if not path.is_file():
            continue
        present.append(v)
    if not present:
        raise SystemExit(
            "Chưa tìm thấy video VARISHTA trong data/raw/varishta/.\n"
            "Hãy tải bộ 450 clip trước bằng lệnh:\n"
            "  .venv/bin/python -m src.dataset download --all\n"
            "(hoặc giải nén các gói ZIP từ GitHub Release varishta-mm50-v5 vào data/raw/varishta/)."
        )
    if max_clips:
        present = present[:max_clips]

    pose = Pose()
    clips = []
    cache = {}
    auto_fall_count = 0
    for idx, v in enumerate(present, start=1):
        vid = v["video_id"]
        dur = float(v["duration_s"])
        mark = confirmed.get(vid)
        try:
            obs = get_keypoints(v, CONFIG, pose, verify=False)
        except Exception as exc:
            print(f"[SKIP] {vid}: {exc}", flush=True)
            continue
        if mark and mark.get("video_sha256") == v["sha256"] and mark.get("label") in {"Fall", "No_Fall"}:
            ann = annotation(mark, dur)
        elif v["original_label"] in NO_FALL_GROUPS:
            ann = {"label": "No_Fall", "onset_s": None, "impact_s": None, "negative": [[0.0, round(dur, 3)]]}
        elif v["original_label"] in FALL_GROUPS:
            ann = auto_annotate_fall(obs, dur, CONFIG)
            if ann is None:
                continue
            auto_fall_count += 1
        else:
            continue
        clips.append({**v, **ann})
        cache[vid] = obs
        if idx % 25 == 0 or idx == len(present):
            print(f"[EXTRACT] {idx}/{len(present)} clips processed ({len(clips)} usable, {auto_fall_count} auto-fall)", flush=True)
    return clips, cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-clips", type=int, default=None, help="Optional cap for quick dry-run")
    args = parser.parse_args()

    clips, cache = build_full_clips(max_clips=args.max_clips)
    related = related_videos()
    assignment = assign_splits(clips, CONFIG["seed"], related=related)
    for c in clips:
        c["split"] = assignment[c["subject_id"]]

    split_fields = ["video_id", "subject_id", "recording_id", "sha256", "original_label",
                    "relative_path", "label", "split", "seed"]
    write_rows(SPLIT, [{**{k: c[k] for k in split_fields[:-1]}, "seed": CONFIG["seed"]} for c in clips], split_fields)

    training = [c for c in clips if c["split"] == "train"]
    validation = [c for c in clips if c["split"] == "validation"]
    testing = [c for c in clips if c["split"] == "test"]
    print(f"Split complete: train={len(training)} | val={len(validation)} | test={len(testing)}", flush=True)

    x, y, counts = make_windows(training, CONFIG, cache)
    print(f"Train windows: Fall={int(y.sum())} | No_Fall={int(len(y) - y.sum())}", flush=True)

    candidates = {
        "Logistic Regression": make_pipeline(
            SimpleImputer(keep_empty_features=True), StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=500, random_state=CONFIG["seed"]),
        ),
        "Random Forest": make_pipeline(
            SimpleImputer(keep_empty_features=True),
            RandomForestClassifier(n_estimators=160, min_samples_leaf=3, class_weight="balanced", random_state=CONFIG["seed"]),
        ),
        "MLP NeuralNet": make_pipeline(
            SimpleImputer(keep_empty_features=True), StandardScaler(),
            MLPClassifier(hidden_layer_sizes=(64, 32), max_iter=300, early_stopping=True, random_state=CONFIG["seed"]),
        ),
    }
    for name, mdl in candidates.items():
        mdl.fit(x, y)
        print(f"Fitted {name}", flush=True)

    results = compare_validation(validation, cache, CONFIG, candidates)
    allowed = int(FALSE_ALARMS_TARGET * results[0]["negative_s"] / 3600)
    if not any(r["detected"] and r["false_alarms"] <= allowed for r in results):
        allowed = min((r["false_alarms"] for r in results if r["detected"]),
                      default=min(r["false_alarms"] for r in results))
    within = [r for r in results if r["false_alarms"] <= allowed]
    selected = min(within, key=rank)
    chosen = selected["classifier"]
    threshold = selected["threshold"]
    test_stats = evaluation(testing, cache, CONFIG, candidates[chosen], threshold)

    buffer = io.BytesIO()
    joblib.dump(candidates[chosen], buffer, compress=3)
    atomic(ARTIFACT, buffer.getvalue())
    digest = sha(ARTIFACT)
    run = {
        "model_id": f"varishta-full-{digest[:12]}",
        "classifier": chosen,
        "threshold": threshold,
        "artifact_sha256": digest,
        "feature_schema": SCHEMA,
        "config": CONFIG,
        "movenet": MODEL,
        "keypoint_runtime": metadata(training[0], CONFIG),
        "split_sha256": sha(SPLIT),
        "training_snapshot": training_snapshot(clips),
        "trained_utc": datetime.now(timezone.utc).isoformat(),
        "train_windows": {"Fall": int(y.sum()), "No_Fall": int(len(y) - y.sum())},
        "train_videos": len(training),
        "train_people": len({c["subject_id"] for c in training}),
        "train_events": sum(v["Fall"] > 0 for v in counts.values()),
        "validation_target_false_per_hour": FALSE_ALARMS_TARGET,
        "validation_detected": selected["detected"],
        "validation_events": selected["events"],
        "test_detected": test_stats["detected"],
        "test_events": test_stats["events"],
        "test_false_alarms": test_stats["false_alarms"],
    }
    write_json(MODEL_INFO, run)
    report = (
        f"# Đánh giá huấn luyện mở rộng VARISHTA-MM50\n\n"
        f"- Model chốt: **{chosen}** · ngưỡng `{threshold}` · `{run['model_id']}`\n"
        f"- Tổng clip sử dụng: **{len(clips)}** (Train: {len(training)}, Val: {len(validation)}, Test: {len(testing)})\n"
        f"- Cửa sổ train: **{int(y.sum())} Fall**, **{int(len(y) - y.sum())} No_Fall**\n"
        f"- Validation: bắt **{selected['detected']}/{selected['events']}** ca, báo giả **{selected['false_alarms']}**\n"
        f"- Test độc lập: bắt **{test_stats['detected']}/{test_stats['events']}** ca "
        f"(Recall `{(test_stats['recall'] or 0)*100:.1f}%`), báo giả **{test_stats['false_alarms']}** "
        f"trên `{test_stats['negative_s']/60:.2f}` phút ADL.\n"
    )
    atomic(ROOT / "reports/full_varishta_evaluation.md", report.encode("utf-8"))
    print("\n" + report, flush=True)


if __name__ == "__main__":
    main()
