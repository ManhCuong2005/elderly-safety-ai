import argparse
import hashlib
import io
import json
from collections import Counter
from importlib.metadata import version

import numpy as np

from .pose import CACHE_SCHEMA, CONFIG, MODEL, Observation, Pose, video_frames
from .review import VIDEOS, rotation_for
from .storage import ROOT, atomic, rows, safe, sha, write_rows


def metadata(video, cfg):
    return {"schema": CACHE_SCHEMA, "video_sha256": video["sha256"], "pose_sha256": MODEL["sha256"],
            "sample_hz": cfg["sample_hz"], "confidence": cfg["confidence"],
            "rotation_override_ccw": rotation_for(video),
            "av": version("av"), "Pillow": version("Pillow"), "litert": version("ai-edge-litert")}


def observe_video(video, cfg, pose):
    path = safe(video["relative_path"])
    for t, frame in video_frames(path, cfg["sample_hz"], rotation_for(video)):
        yield pose.observe(t, frame)


def get_keypoints(video, cfg, pose=None, verify=True):
    path = safe(video["relative_path"])
    if verify and sha(path) != video["sha256"]:
        raise ValueError(f"Checksum video đã đổi: {video['video_id']}")
    meta = json.dumps(metadata(video, cfg), sort_keys=True)
    key = hashlib.sha256(meta.encode()).hexdigest()[:20]
    cache = safe(f"data/processed/{video['video_id'].replace('/', '_')}_{key}.npz")
    if cache.exists():
        with np.load(cache, allow_pickle=False) as archive:
            if str(archive["metadata"]) != meta:
                raise ValueError("Cache keypoint có metadata khác")
            return [Observation(float(t), int(w), int(h), points)
                    for t, w, h, points in zip(archive["t"], archive["width"], archive["height"], archive["joints"])]
    if pose is None:
        pose = Pose()
    observations = list(observe_video(video, cfg, pose))
    if not observations:
        raise ValueError(f"Không có frame có timestamp: {video['video_id']}")
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer, metadata=meta, t=[o.t for o in observations], width=[o.width for o in observations],
        height=[o.height for o in observations], joints=[o.points for o in observations],
        observation=[o.state(cfg["confidence"]) for o in observations],
    )
    atomic(cache, buffer.getvalue())
    return observations


def extract(include_review):
    pose = Pose()
    clips = [v for v in rows(VIDEOS) if v["duration_s"]
             and (v["status"] == "keep" or (include_review and v["status"] == "review"))]
    if not clips:
        raise ValueError("Chưa có video đủ điều kiện. Chạy Inventory hoặc Confirm trước.")
    stats_path = ROOT / "data/review/pose_coverage.csv"
    stats = {row["video_id"]: row for row in rows(stats_path)}
    for video in clips:
        observations = get_keypoints(video, CONFIG, pose)
        counts = Counter(o.state(CONFIG["confidence"]) for o in observations)
        status = {key: counts[key] for key in ("visible", "partial", "absent")}
        stats[video["video_id"]] = {"video_id": video["video_id"], "sha256": video["sha256"],
                                   "frames": len(observations), **status}
        write_rows(stats_path, list(stats.values()))
        print(f"{video['video_id']}: {len(observations)} frame, {counts['visible']} thấy vai/hông", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-review", action="store_true")
    extract(parser.parse_args().include_review)
