"""Extract MediaPipe 2D+3D landmarks (RGB-corrected) and 25 kinematic ML features for UR Fall.

Phase 1 (Task 1.2 & 1.3):
- Runs MediaPipe Pose Landmarker (full model) in parallel across all 60 verified UR Fall
  sequences with proper right-panel RGB cropping for composite MP4 clips.
- Caches landmarks + 3D world_landmarks + real throughput FPS in processed/<cache-tag>/.
- Aligns every frame with official human-annotated UR Fall frame labels
  (urfall-cam0-falls.csv & urfall-cam0-adls.csv) and computes the canonical 25-feature
  spatio-temporal kinematic vector shared verbatim with runtime Engine.
- Exports dataset_features.csv for Phase 2 ML model training and GroupKFold evaluation.
"""
import argparse
import concurrent.futures
import csv
import json
from pathlib import Path
import sys
import time

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT = ENGINE_DIR.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from src.camera import Source
from src.config import Config
from src.engine import Engine
from src.ml.features import FEATURE_NAMES, build_feature_dict
from src.pose import PoseTracker

DATA = ENGINE_DIR / "datasets"
META = DATA / "metadata"


def load_ur_ground_truth():
    """Load official UR Fall per-frame annotations: video_id -> dict[frame_idx_1based, int_label]."""
    gt = {}
    for fname in ("urfall-cam0-falls.csv", "urfall-cam0-adls.csv"):
        path = META / fname
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 3:
                    gt.setdefault(row[0], {})[int(row[1])] = int(row[2])
    return gt


def _extract_single_video(args_tuple):
    record, model_path, out_dir_str, config_dict = args_tuple
    out_dir = Path(out_dir_str)
    vid = record["video_id"]
    cache_path = out_dir / f"{vid}.landmarks.jsonl"
    perf_path = out_dir / f"{vid}.performance.json"
    if cache_path.exists() and perf_path.exists():
        perf = json.loads(perf_path.read_text(encoding="utf-8"))
        if perf.get("has_world_landmarks") and perf.get("input_layout") == record.get("input_layout", "rgb"):
            return f"CACHE {vid} ({perf['frames']}f, {perf['throughput_fps']:.1f} FPS)"

    config = Config(**config_dict)
    source = Source(
        str(ROOT / record["path"]),
        str(ROOT / record["sync_path"]),
        layout=record.get("input_layout", "auto"),
    )
    tracker = PoseTracker(model_path, config)
    start = time.perf_counter()
    count = 0
    temp = cache_path.with_suffix(".partial")
    try:
        with temp.open("w", encoding="utf-8") as out:
            for t, frame in source:
                pose, reason = tracker.process(frame, t)
                h, w = frame.shape[:2]
                out.write(json.dumps({
                    "t": t,
                    "landmarks": pose,
                    "world_landmarks": tracker.last_world_landmarks,
                    "reason": reason,
                    "width": w,
                    "height": h,
                }) + "\n")
                count += 1
        temp.rename(cache_path)
        elapsed = time.perf_counter() - start
        fps = count / max(elapsed, 1e-6)
        perf_path.write_text(json.dumps({
            "video_id": vid,
            "frames": count,
            "processing_seconds": round(elapsed, 4),
            "throughput_fps": round(fps, 2),
            "avg_ms_per_frame": round(elapsed * 1000.0 / max(count, 1), 2),
            "includes_decode_and_inference": True,
            "input_layout": source.layout,
            "has_world_landmarks": True,
        }, indent=2), encoding="utf-8")
        return f"OK {vid} ({count}f, {fps:.1f} FPS, layout={source.layout})"
    finally:
        source.close()
        tracker.close()
        temp.unlink(missing_ok=True)


def build_feature_dataset(records, cache_dir, gt_map, config, out_csv):
    """Replay cached RGB landmarks through V2 kinematic pipeline and export CSV dataset."""
    fieldnames = [
        "video_id", "split", "dataset_partition", "video_label",
        "frame_idx", "timestamp_s", "gt_raw", "target_fall", "activity_class",
        "posture_rule", "pose_coverage", "fall_onset_s",
    ] + FEATURE_NAMES

    rows_written = 0
    fall_pos = 0
    adl_neg = 0
    pre_neg = 0
    onset_map = {}

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for rec in records:
            vid = rec["video_id"]
            num = int(vid.split("-")[1])
            # Strictly video-grouped partition: 01..20 -> train_cv (40 videos), 21..30 -> test_holdout (20 videos)
            partition = "train_cv" if num <= 20 else "test_holdout"
            cache = cache_dir / f"{vid}.landmarks.jsonl"
            if not cache.exists():
                raise FileNotFoundError(f"Missing landmark cache: {cache}")

            vid_gt = gt_map.get(vid, {})
            lines = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()]

            # Find exact official fall transition start/end timestamps (gt == 0) for FALL videos
            fall_start_t = None
            fall_end_t = None
            if rec["label"] == "FALL":
                for idx_1, row in enumerate(lines, start=1):
                    g = vid_gt.get(idx_1)
                    if g == 0:
                        if fall_start_t is None:
                            fall_start_t = row["t"]
                        fall_end_t = row["t"]
                onset_map[vid] = round(fall_start_t, 4) if fall_start_t is not None else None

            engine = Engine(config)
            for idx_1, row in enumerate(lines, start=1):
                t = row["t"]
                res = engine.process(
                    t, row["landmarks"], row["width"], row["height"],
                    row["reason"], world_landmarks=row.get("world_landmarks"),
                )
                feat_obj = engine.motion.samples[-1][1] if (res["features"] and engine.motion.samples) else None
                if feat_obj is None:
                    continue
                # Reconstruct exact Motion object values via engine output / build_feature_dict
                from src.features import Features
                from src.motion import Motion
                f_dict = res["features"]
                m_dict = res["motion"]
                feat_inst = Features(
                    f_dict["hip_x"], f_dict["hip_y"], f_dict["torso"], f_dict["lean"],
                    f_dict["knee"], f_dict["hip_angle"], f_dict["aspect"], f_dict["leg_vertical"],
                    f_dict["ankle_delta"], tuple(map(tuple, f_dict["points"])),
                    f_dict["confidence"], f_dict["both_legs_visible"], f_dict["coverage"],
                    f_dict["body_height"], f_dict["body_width"], f_dict["thigh_vertical"],
                    f_dict["head_y"], f_dict["shoulder_y"], f_dict["head_below_hip"], f_dict["z_lean_3d"],
                )
                mot_inst = Motion(**m_dict)
                kin = build_feature_dict(feat_inst, mot_inst)

                g = vid_gt.get(idx_1, -1)
                if rec["label"] == "FALL":
                    if g == -1:
                        target = 0
                        act_cls = "UPRIGHT_PRE_FALL"
                        pre_neg += 1
                    elif g == 0:
                        target = 1
                        act_cls = "FALL_TRANSITION"
                        fall_pos += 1
                    else:  # g == 1 (lying on floor after fall)
                        # Within 1.5s after fall impact, sliding window retains transition kinematics -> positive
                        after_impact = (t - fall_end_t) if fall_end_t is not None else 0.0
                        if after_impact <= 1.5:
                            target = 1
                            act_cls = "POST_FALL_IMPACT"
                            fall_pos += 1
                        else:
                            target = -1  # static late post-fall lying: excluded from transition training
                            act_cls = "POST_FALL_STATIC"
                else:
                    target = 0
                    adl_neg += 1
                    if g == -1:
                        act_cls = res["posture"] if res["posture"] != "UNKNOWN" else "ADL_UPRIGHT"
                    elif g == 0:
                        act_cls = "ADL_LOWERING_OR_BENDING"
                    else:
                        act_cls = "ADL_DELIBERATE_LYING"

                out_row = {
                    "video_id": vid,
                    "split": rec["split"],
                    "dataset_partition": partition,
                    "video_label": rec["label"],
                    "frame_idx": idx_1,
                    "timestamp_s": round(t, 4),
                    "gt_raw": g,
                    "target_fall": target,
                    "activity_class": act_cls,
                    "posture_rule": res["posture"],
                    "pose_coverage": res["pose_coverage"],
                    "fall_onset_s": onset_map.get(vid, ""),
                }
                out_row.update({k: round(v, 5) for k, v in kin.items()})
                writer.writerow(out_row)
                rows_written += 1

    onset_path = cache_dir / "fall_onsets.json"
    onset_path.write_text(json.dumps(onset_map, indent=2), encoding="utf-8")
    return {
        "rows_written": rows_written,
        "fall_positive_frames": fall_pos,
        "pre_fall_negative_frames": pre_neg,
        "adl_negative_frames": adl_neg,
        "csv_path": str(out_csv),
        "onsets_count": len(onset_map),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", default=str(ENGINE_DIR / "models/pose_landmarker_full.task"))
    p.add_argument("--cache-tag", default="rgb_v2")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--skip-pose", action="store_true", help="Reuse cached landmarks and only regenerate feature CSV")
    args = p.parse_args()

    records = json.loads((META / "manifest.json").read_text(encoding="utf-8"))
    out_dir = DATA / "processed" / args.cache_tag
    out_dir.mkdir(parents=True, exist_ok=True)

    # Extract poses with auto_reacquire=True, landmark smoothing=0.06s, visibility=0.5
    extract_cfg = Config(
        visibility=0.5,
        lying_lean=55.0,
        grace_period_s=0.45,
        auto_reacquire=True,
        enable_bending=True,
        landmark_smooth_tau_s=0.06,
    )
    from dataclasses import asdict

    if not args.skip_pose:
        print(f"Extracting MediaPipe 2D+3D poses for {len(records)} UR Fall videos with {args.workers} workers...", flush=True)
        t0 = time.perf_counter()
        tasks = [(rec, args.model, str(out_dir), asdict(extract_cfg)) for rec in records]
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as ex:
            for msg in ex.map(_extract_single_video, tasks):
                print(msg, flush=True)
        print(f"Pose extraction finished in {time.perf_counter() - t0:.1f}s", flush=True)

    gt_map = load_ur_ground_truth()
    csv_path = out_dir / "dataset_features.csv"
    summary = build_feature_dataset(records, out_dir, gt_map, extract_cfg, csv_path)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
