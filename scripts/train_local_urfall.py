"""Train CameraAI's fall classifier on the 54 local UR Fall videos using MoveNet Thunder (256x256).

Zero extra dataset download required — uses data/raw/saved_local_videos/urfall_raw/
with strict video-level train/val/test isolation:
  * Train:      fall-04..20 + adl-04..20 (34 clips)
  * Validation: fall-21..25 + adl-21..25 (10 clips)
  * Test:       fall-26..30 + adl-26..30 (10 clips)

Exports drop-in models/classifier.joblib and models/classifier.json compatible with
src.server and src.train.load_model().
"""
from datetime import datetime, timezone
import glob
import io
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import av
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.inference import SCHEMA
from src.pose import CONFIG, MODEL, Pose, sample_frames
from src.storage import atomic, safe, sha, write_json
from src.train import (
    ARTIFACT,
    FALSE_ALARMS_TARGET,
    MODEL_INFO,
    SPLIT,
    compare_validation,
    evaluation,
    make_windows,
    rank,
    replay,
)


def extract_urfall_observations(vp, pose, hz):
    obs = []
    dur = 0.0
    with av.open(str(vp)) as container:
        for t, img in sample_frames(container, hz, limit_s=90):
            if img.width >= 1000:
                img = img.crop((img.width // 2, 0, img.width, img.height))
            obs.append(pose.observe(t, img))
            dur = t
    return obs, max(dur, 0.1)


def auto_fall_span(observations, dur, cfg):
    frames = replay(observations, cfg)
    best_score, impact_t = -1.0, None
    for row in frames:
        f = row["features"]
        if f is None:
            continue
        hip_drop = float(np.nan_to_num(f[0], nan=0.0))
        sh_drop = float(np.nan_to_num(f[1], nan=0.0))
        peak_v = float(np.nan_to_num(f[4], nan=0.0))
        ang_ch = float(np.nan_to_num(f[6], nan=0.0))
        score = max(0.0, hip_drop) + max(0.0, sh_drop) + 0.35 * max(0.0, peak_v) + 1.5 * max(0.0, ang_ch)
        if score > best_score:
            best_score, impact_t = score, row["t"]
    if impact_t is None or best_score < 0.5:
        impact_t = dur * 0.6
    onset_t = max(0.3, impact_t - 1.1)
    impact_t = min(dur - 0.05, max(onset_t + 0.25, impact_t))
    neg = [[0.0, round(onset_t - 0.4, 3)]] if onset_t >= 2.5 else []
    return round(onset_t, 3), round(impact_t, 3), neg


def main():
    raw_dir = ROOT / "data/raw/saved_local_videos/urfall_raw"
    files = sorted(glob.glob(str(raw_dir / "*-cam0.mp4")))
    if not files:
        raise SystemExit(f"Không tìm thấy video UR Fall trong {raw_dir}")

    # UR Fall clips are 1.8s-3.5s long; a 1.0s window (10 frames @ 10 Hz) captures the full fall transient cleanly.
    serve_cfg = {**CONFIG, "window_s": 1.0, "step_s": 0.2}
    train_cfg = {**serve_cfg, "alert_lock_enabled": False, "enable_slump_detection": False, "enable_convulsion": False}
    cache_file = ROOT / ".cache/urfall_thunder_obs.joblib"
    if cache_file.is_file():
        saved = joblib.load(cache_file)
        clips, cache = saved["clips"], saved["cache"]
        print(f"Loaded cached MoveNet Thunder keypoints for {len(clips)} UR Fall clips.", flush=True)
    else:
        pose = Pose()
        clips, cache = [], {}
        print(f"Extracting MoveNet Thunder ({pose.size}x{pose.size}) keypoints for {len(files)} UR Fall clips...", flush=True)
        for idx, vp in enumerate(files, start=1):
            name = Path(vp).stem  # e.g. fall-04-cam0 or adl-12-cam0
            m = re.match(r"^(fall|adl)-(\d+)-cam0$", name)
            if not m:
                continue
            kind, num = m.group(1), int(m.group(2))
            split = "train" if num <= 20 else ("validation" if num <= 25 else "test")
            obs, dur = extract_urfall_observations(vp, pose, serve_cfg["sample_hz"])
            if kind == "fall":
                onset, impact, neg = auto_fall_span(obs, dur, train_cfg)
                label = "Fall"
            else:
                onset, impact, neg = None, None, [[0.0, round(dur, 3)]]
                label = "No_Fall"
            clip = {
                "video_id": name,
                "subject_id": f"urfall_{num:02d}",
                "relative_path": str(Path(vp).relative_to(ROOT)),
                "label": label,
                "split": split,
                "duration_s": round(dur, 3),
                "onset_s": onset,
                "impact_s": impact,
                "negative": neg,
            }
            clips.append(clip)
            cache[name] = obs
            if idx % 10 == 0 or idx == len(files):
                print(f"  [{idx:2d}/{len(files)}] {name} ({split}, {label}, {dur:.1f}s)", flush=True)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"clips": clips, "cache": cache}, cache_file, compress=3)

    training = [c for c in clips if c["split"] == "train"]
    validation = [c for c in clips if c["split"] == "validation"]
    testing = [c for c in clips if c["split"] == "test"]

    x, y, counts = make_windows(training, train_cfg, cache)
    print(f"\nTrain windows: Fall={int(y.sum())} | No_Fall={int(len(y) - y.sum())} across {len(training)} clips", flush=True)

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
            MLPClassifier(hidden_layer_sizes=(64, 32), alpha=0.1, max_iter=500, random_state=CONFIG["seed"]),
        ),
    }
    for name, mdl in candidates.items():
        mdl.fit(x, y)

    results = compare_validation(validation, cache, train_cfg, candidates)
    allowed = 0
    if not any(r["detected"] and r["false_alarms"] <= allowed for r in results):
        allowed = min((r["false_alarms"] for r in results if r["detected"]), default=0)
    within = [r for r in results if r["false_alarms"] <= allowed and r["threshold"] >= 0.70]
    if not within:
        within = [r for r in results if r["false_alarms"] <= allowed]
    selected = min(within, key=rank)
    chosen = selected["classifier"]
    threshold = selected["threshold"]
    test_stats = evaluation(testing, cache, train_cfg, candidates[chosen], threshold)
    all_adl_stats = evaluation([c for c in clips if c["label"] == "No_Fall"], cache, train_cfg, candidates[chosen], threshold)

    print(f"\nSelected: {chosen} @ threshold={threshold}")
    print(f"  Validation: {selected['detected']}/{selected['events']} falls, {selected['false_alarms']} FP")
    print(f"  Holdout Test (26..30): {test_stats['detected']}/{test_stats['events']} falls, {test_stats['false_alarms']} FP")
    print(f"  All 27 UR Fall ADLs: {all_adl_stats['false_alarms']} FP")

    buffer = io.BytesIO()
    joblib.dump(candidates[chosen], buffer, compress=3)
    atomic(ARTIFACT, buffer.getvalue())
    digest = sha(ARTIFACT)
    run = {
        "model_id": f"urfall-thunder-{digest[:12]}",
        "classifier": chosen,
        "threshold": threshold,
        "artifact_sha256": digest,
        "feature_schema": SCHEMA,
        "config": serve_cfg,
        "movenet": MODEL,
        "split_sha256": sha(SPLIT) if SPLIT.is_file() else "",
        "trained_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": "UR Fall (54 local RGB clips, MoveNet SinglePose Thunder 256x256)",
        "train_windows": {"Fall": int(y.sum()), "No_Fall": int(len(y) - y.sum())},
        "train_videos": len(training),
        "train_events": sum(v["Fall"] > 0 for v in counts.values()),
        "validation_target_false_per_hour": FALSE_ALARMS_TARGET,
        "validation_detected": selected["detected"],
        "validation_events": selected["events"],
        "validation_false_alarms": selected["false_alarms"],
        "test_detected": test_stats["detected"],
        "test_events": test_stats["events"],
        "test_false_alarms": test_stats["false_alarms"],
    }
    write_json(MODEL_INFO, run)

    report = (
        f"# Đánh giá model CameraAI (MoveNet Thunder 256×256 + 54 clip UR Fall)\n\n"
        f"- Pose backbone: **MoveNet SinglePose Thunder v4 (256×256, float16)**\n"
        f"- Classifier chốt: **{chosen}** · ngưỡng `{threshold}` · `{run['model_id']}`\n"
        f"- Tập dữ liệu (chia độc lập theo mã chuỗi video, không rò rỉ):\n"
        f"  - Train (`04..20`): **{len(training)} clip** ({int(y.sum())} cửa sổ Fall, {int(len(y)-y.sum())} cửa sổ No_Fall)\n"
        f"  - Validation (`21..25`): bắt **{selected['detected']}/{selected['events']}** ca ngã, báo giả **{selected['false_alarms']}**\n"
        f"  - Holdout Test độc lập (`26..30`): bắt **{test_stats['detected']}/{test_stats['events']}** ca ngã "
        f"(Recall `{(test_stats['recall'] or 0)*100:.1f}%`), báo giả **{test_stats['false_alarms']}**\n"
        f"- Toàn bộ 27 clip ADL UR Fall (`adl-04..30`): tổng báo giả **{all_adl_stats['false_alarms']}**\n"
    )
    atomic(ROOT / "reports/local_thunder_evaluation.md", report.encode("utf-8"))
    print("\nSaved -> models/classifier.joblib, models/classifier.json, reports/local_thunder_evaluation.md")


if __name__ == "__main__":
    main()
