"""Social Media / Public Video Collector & V2 AI Analyzer for Elderly Safety Dataset.

Supports:
1. `download`: Download public videos via yt-dlp (YouTube, TikTok, Facebook Reels,
   Pexels, Vimeo, etc.) from a single URL or batch CSV list, optionally trim to
   [start_s, end_s], normalize resolution (<=640px) via ffmpeg while preserving
   real 1x playback speed, and store under ai_engine/datasets/custom/<label>/.
2. `analyze`: Run MediaPipe 2D/3D Pose + V2 ML Engine over one video or the
   entire custom dataset folder. Produces:
   - Data Quality Gate verdict (USABLE / REVIEW_NEEDED / REJECT_LOW_QUALITY)
   - AI V2 analysis (max_fall_score, alerts, FSM, activity distribution, match vs label)
   - Optional annotated MP4 video with skeleton + Fall Risk bar (`--render-video`)
   - Ready-to-train 25-feature CSV (`custom_features.csv`) matching UR Fall schema
   - Summary reports (`analysis_report.json` & `analysis_report.csv`)

Usage examples:
  # 1. Download a single public video clip (trim seconds 4..12) and analyze immediately:
  PYTHONPATH=ai_engine .venv/bin/python ai_engine/scripts/collect_and_analyze.py download \
      --url "https://www.youtube.com/watch?v=..." --label FALL --start 4 --end 12 --analyze --render-video

  # 2. Batch download from CSV file:
  PYTHONPATH=ai_engine .venv/bin/python ai_engine/scripts/collect_and_analyze.py download \
      --list ai_engine/datasets/custom/sources.csv --analyze

  # 3. Analyze any local MP4 file or the whole custom/ folder:
  PYTHONPATH=ai_engine .venv/bin/python ai_engine/scripts/collect_and_analyze.py analyze \
      --input ai_engine/datasets/custom/ --render-video
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import cv2

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT = ENGINE_DIR.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from src.camera import Source
from src.config import Config
from src.engine import Engine
from src.features import Features
from src.ml.features import FEATURE_NAMES, build_feature_dict
from src.motion import Motion
from src.pose import PoseTracker

CUSTOM_ROOT = ENGINE_DIR / "datasets" / "custom"
CLASSES_ROOT = ENGINE_DIR / "datasets" / "classes"
VALID_ACTIVITIES = ("FALL", "BENDING", "LYING", "SITTING", "WALKING", "STANDING", "OTHER")
SUPPORTED_PLATFORMS = ("youtube", "tiktok", "facebook", "instagram", "dailymotion", "vimeo", "pexels")

NEGATIVE_KEYWORDS = [
    "funny", "meme", "prank", "comedy", "epic", "fail army", "queen",
    "laugh", "humor", "compilation", "viral reel", "hilarious", "joke", "troll", "tik tok dance"
]

CATEGORY_PRESETS = {
    "fall": {
        "queries": [
            "elderly fall simulation indoor CCTV",
            "elderly slip and fall backward indoor",
            "fall from chair elderly simulation",
            "elderly trip and fall home",
        ],
        "label": "FALL",
        "description": "Video té ngã (ngã trước, ngã ngửa, trượt chân, ngã ghế)",
    },
    "bending": {
        "queries": [
            "picking up object from floor CCTV indoor",
            "elderly bending down pick up keys floor",
            "tying shoes elderly floor bending indoor",
        ],
        "label": "BENDING",
        "description": "Video cúi người nhặt đồ, buộc dây giày (tránh báo động giả)",
    },
    "lying": {
        "queries": [
            "elderly lying down on sofa bed indoor",
            "senior resting lying on bed bedroom",
            "person lying down yoga mat floor indoor",
        ],
        "label": "LYING",
        "description": "Video nằm chủ động xuống giường/sofa/thảm",
    },
    "sitting": {
        "queries": [
            "elderly sitting down chair living room",
            "sit to stand test elderly indoor",
            "senior citizen sitting on sofa living room",
        ],
        "label": "SITTING",
        "description": "Video ngồi xuống nhanh, đứng lên/ngồi xuống",
    },
    "walking": {
        "queries": [
            "elderly walking indoor living room CCTV",
            "senior walking with cane hallway indoor",
            "elderly indoor walking test room",
        ],
        "label": "WALKING",
        "description": "Video đi lại, đứng sinh hoạt bình thường",
    },
}


def search_platform(platform, query, limit=3):
    """Discover public video URLs on a given social media / video platform."""
    platform = platform.strip().lower()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform '{platform}'. Choose from: {', '.join(SUPPORTED_PLATFORMS)}")
    results = []
    if platform == "youtube":
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "socket_timeout": 15}) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False) or {}
            for entry in (info.get("entries") or [])[:limit]:
                title = entry.get("title") or ""
                if any(neg in title.lower() for neg in NEGATIVE_KEYWORDS):
                    continue
                url = entry.get("url") or entry.get("webpage_url")
                if url and not url.startswith("http"):
                    url = f"https://www.youtube.com/watch?v={url}"
                if url:
                    results.append({
                        "platform": "youtube",
                        "title": title,
                        "url": url,
                        "duration_s": entry.get("duration"),
                    })
        return results

    if platform == "dailymotion":
        import requests
        resp = requests.get(
            "https://api.dailymotion.com/videos",
            params={"search": query, "limit": limit, "fields": "id,title,url,duration"},
            timeout=15,
        )
        resp.raise_for_status()
        for item in (resp.json().get("list") or [])[:limit]:
            results.append({
                "platform": "dailymotion",
                "title": item.get("title") or "",
                "url": item.get("url"),
                "duration_s": item.get("duration"),
            })
        return results

    # Multi-platform social discovery via DuckDuckGo public index (TikTok, Facebook, Instagram, Vimeo, Pexels)
    from ddgs import DDGS
    site_filter = {
        "tiktok": "site:tiktok.com",
        "facebook": "site:facebook.com",
        "instagram": "site:instagram.com",
        "vimeo": "site:vimeo.com",
        "pexels": "site:pexels.com",
    }[platform]
    with DDGS() as ddgs:
        hits = []
        for q_variant in (f"{site_filter} {query}", f"{platform} video {query}"):
            try:
                hits.extend(list(ddgs.text(q_variant, max_results=max(limit * 4, 8))))
            except Exception:
                pass
            if len(hits) >= limit * 2:
                break
    seen = set()
    for hit in hits:
        url = (hit.get("href") or "").strip()
        if not url or url in seen:
            continue
        if platform == "tiktok" and "/video/" not in url:
            continue
        if platform == "facebook" and (
            "developers.facebook.com" in url
            or not any(k in url for k in ("/videos/", "/reel/", "/watch", "fb.watch"))
        ):
            continue
        if platform == "instagram" and not any(k in url for k in ("/reel/", "/p/")):
            continue
        if platform == "vimeo" and not re.search(r"vimeo\.com/\d+", url):
            continue
        if platform == "pexels" and "/video/" not in url:
            continue
        title = (hit.get("title") or "").strip()
        if any(neg in title.lower() for neg in NEGATIVE_KEYWORDS):
            continue
        seen.add(url)
        results.append({
            "platform": platform,
            "title": title,
            "url": url,
            "duration_s": None,
        })
        if len(results) >= limit:
            break
    return results


def search_multi_platform(query, platforms, limit_per_platform=3):
    all_hits = []
    for plat in platforms:
        try:
            hits = search_platform(plat, query, limit=limit_per_platform)
            all_hits.extend(hits)
        except Exception as exc:
            print(f"[WARN] Search on {plat} failed: {exc}", file=sys.stderr, flush=True)
    return all_hits


def normalize_activity(label):
    cleaned = re.sub(r"[^A-Za-z_]", "", (label or "").strip().upper())
    if cleaned in ("NON_FALL", "ADL", "NORMAL"):
        return "OTHER"
    if cleaned not in VALID_ACTIVITIES:
        raise ValueError(f"Unsupported label '{label}'. Choose one of: {', '.join(VALID_ACTIVITIES)}")
    return cleaned


def _safe_slug(text, max_len=36):
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "clip")).strip("_").lower()
    return (slug[:max_len] or "clip")


def _trim_and_normalize(src_path, dst_path, start_s=None, end_s=None, max_height=480):
    """Use ffmpeg to trim segment and normalize codec/size without altering 1x speed."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.copy2(src_path, dst_path)
        return
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if start_s is not None and start_s > 0:
        cmd += ["-ss", f"{start_s:.3f}"]
    cmd += ["-i", str(src_path)]
    if end_s is not None and end_s > 0:
        if start_s is not None and start_s > 0:
            dur = max(0.5, end_s - start_s)
            cmd += ["-t", f"{dur:.3f}"]
        else:
            cmd += ["-to", f"{end_s:.3f}"]
    cmd += [
        "-vf", f"scale=-2:min({max_height}\\,ih)",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an",
        str(dst_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()}")


def download_one(url, activity, out_root=CUSTOM_ROOT, start_s=None, end_s=None, note="", max_height=480):
    """Download one public video via yt-dlp, normalize to MP4, and save metadata JSON."""
    import yt_dlp

    activity = normalize_activity(activity)
    out_dir = Path(out_root) / activity.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(out_root) / ".tmp_dl"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.sha1(f"{url}|{start_s}|{end_s}".encode("utf-8")).hexdigest()[:10]
    tmp_template = str(tmp_dir / f"{url_hash}.%(ext)s")
    ydl_opts = {
        "format": "mp4/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "outtmpl": tmp_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = Path(ydl.prepare_filename(info))
        if not downloaded.exists():
            # yt-dlp may have merged into .mp4
            alt = downloaded.with_suffix(".mp4")
            if alt.exists():
                downloaded = alt
            else:
                matches = list(tmp_dir.glob(f"{url_hash}.*"))
                if not matches:
                    raise FileNotFoundError(f"Downloaded file not found for {url}")
                downloaded = matches[0]

    platform = _safe_slug(info.get("extractor_key") or info.get("extractor") or "web", 20)
    title_slug = _safe_slug(info.get("title") or info.get("id") or "video", 28)
    clip_id = f"{activity.lower()}-{platform}-{title_slug}-{url_hash[:6]}"
    final_mp4 = out_dir / f"{clip_id}.mp4"
    meta_json = out_dir / f"{clip_id}.json"

    try:
        _trim_and_normalize(downloaded, final_mp4, start_s=start_s, end_s=end_s, max_height=max_height)
    finally:
        downloaded.unlink(missing_ok=True)

    cap = cv2.VideoCapture(str(final_mp4))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()

    meta = {
        "video_id": clip_id,
        "source_url": url,
        "platform": info.get("extractor_key") or info.get("extractor"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "license": info.get("license"),
        "label": "FALL" if activity == "FALL" else "NON_FALL",
        "activity": activity,
        "trim_start_s": start_s,
        "trim_end_s": end_s,
        "note": note,
        "path": str(final_mp4),
        "input_layout": "rgb",
        "width": w,
        "height": h,
        "fps": round(fps, 2),
        "frame_count": frames,
        "duration_s": round(frames / fps, 2) if fps > 0 else 0.0,
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
    }
    meta_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def load_sources_csv(csv_path):
    """Parse batch URL list CSV: columns url,label[,start_s,end_s,note]."""
    rows = []
    with Path(csv_path).open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            url = (raw.get("url") or "").strip()
            if not url or url.startswith("#"):
                continue
            label = raw.get("label") or raw.get("activity") or "OTHER"
            start_s = float(raw["start_s"]) if (raw.get("start_s") or "").strip() else None
            end_s = float(raw["end_s"]) if (raw.get("end_s") or "").strip() else None
            note = (raw.get("note") or "").strip()
            rows.append({"url": url, "label": normalize_activity(label), "start_s": start_s, "end_s": end_s, "note": note})
    return rows


def _draw_overlay(frame, tracker, pose, res, video_id):
    vis = frame.copy()
    tracker.draw(vis, pose)
    h, w = vis.shape[:2]
    score = float(res.get("fall_score", 0.0))
    bar_w = int(min(220, w * 0.45))
    bx, by = 14, h - 28
    cv2.rectangle(vis, (bx, by), (bx + bar_w, by + 14), (40, 40, 40), -1)
    fill_color = (40, 40, 230) if score >= 0.75 else (0, 165, 255) if score >= 0.35 else (90, 200, 120)
    cv2.rectangle(vis, (bx, by), (bx + int(bar_w * min(1.0, max(0.0, score))), by + 14), fill_color, -1)
    cv2.putText(vis, f"Fall Risk {int(round(score * 100))}%", (bx + bar_w + 8, by + 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    lines = [
        f"{video_id} | {res['posture']} | FSM {res['fsm']}",
        f"Pose: {res['pose_coverage']} | Status: {res['person_status']}",
    ]
    for i, text in enumerate(lines):
        cv2.putText(vis, text, (14, 24 + i * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (15, 15, 15), 3, cv2.LINE_AA)
        cv2.putText(vis, text, (14, 24 + i * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
    return vis


def analyze_video(
    video_path,
    config,
    model_path,
    expected_activity=None,
    input_layout="auto",
    render_dir=None,
):
    """Run full V2 AI analysis on a single video and extract 25-feature rows."""
    video_path = Path(video_path)
    meta_path = video_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    vid = meta.get("video_id") or video_path.stem

    if expected_activity is None:
        if meta.get("activity"):
            expected_activity = normalize_activity(meta["activity"])
        elif video_path.parent.name.upper() in VALID_ACTIVITIES:
            expected_activity = video_path.parent.name.upper()
        else:
            expected_activity = "OTHER"
    expected_binary = "FALL" if expected_activity == "FALL" else "NON_FALL"

    source = Source(str(video_path), layout=meta.get("input_layout", input_layout))
    tracker = PoseTracker(model_path, config)
    engine = Engine(config)

    writer = None
    rendered_path = None
    if render_dir is not None:
        render_dir = Path(render_dir)
        render_dir.mkdir(parents=True, exist_ok=True)
        rendered_path = render_dir / f"{vid}_analyzed.mp4"

    total = 0
    valid_pose = 0
    multi_person = 0
    max_fall_score = 0.0
    events = []
    feature_rows = []
    t_start = time.perf_counter()

    try:
        for t, frame in source:
            pose, reason = tracker.process(frame, t)
            h, w = frame.shape[:2]
            res = engine.process(t, pose, w, h, reason, world_landmarks=tracker.last_world_landmarks, people_count=tracker.last_people_count)
            total += 1
            if res["features"]:
                valid_pose += 1
            if "MULTIPLE_PEOPLE" in str(res["person_status"]):
                multi_person += 1
            score = float(res.get("fall_score", 0.0))
            if score > max_fall_score:
                max_fall_score = score
            events.extend(res["events"])

            if res["features"]:
                f_d = res["features"]
                m_d = res["motion"]
                f_obj = Features(
                    f_d["hip_x"], f_d["hip_y"], f_d["torso"], f_d["lean"],
                    f_d["knee"], f_d["hip_angle"], f_d["aspect"], f_d["leg_vertical"],
                    f_d["ankle_delta"], tuple(map(tuple, f_d["points"])),
                    f_d["confidence"], f_d["both_legs_visible"], f_d["coverage"],
                    f_d["body_height"], f_d["body_width"], f_d["thigh_vertical"],
                    f_d["head_y"], f_d["shoulder_y"], f_d["head_below_hip"], f_d["z_lean_3d"],
                )
                kin = build_feature_dict(f_obj, Motion(**m_d))
                row = {
                    "video_id": vid,
                    "video_label": expected_binary,
                    "activity": expected_activity,
                    "frame_idx": total,
                    "timestamp_s": round(t, 4),
                    "posture_rule": res["posture"],
                    "fall_score": round(score, 4),
                }
                row.update({k: round(v, 5) for k, v in kin.items()})
                feature_rows.append(row)

            if rendered_path is not None:
                if writer is None:
                    fps = source.fps if (getattr(source, "fps", 0) and source.fps > 1) else 20.0
                    writer = cv2.VideoWriter(str(rendered_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                writer.write(_draw_overlay(frame, tracker, pose, res, vid))
    finally:
        source.close()
        tracker.close()
        if writer is not None:
            writer.release()

    elapsed = time.perf_counter() - t_start
    valid_ratio = round(valid_pose / max(total, 1), 3)
    multi_ratio = round(multi_person / max(total, 1), 3)

    alerts = [e for e in events if e["kind"] in ("SUSPECTED_FALL", "POSSIBLE_FALL")]
    verified = [e for e in events if e["kind"] == "POSSIBLE_FALL"]
    other_anomalies = [e for e in events if e["kind"] in ("LYING_TOO_LONG", "ABNORMAL_INACTIVITY")]
    predicted_binary = "FALL" if alerts else "NON_FALL"

    issues = []
    if total < 15:
        issues.append("TOO_SHORT")
    if valid_ratio < 0.45:
        issues.append("LOW_POSE_VISIBILITY")
    if multi_ratio > 0.20:
        issues.append("MULTIPLE_PEOPLE_SCENE")

    if "TOO_SHORT" in issues or valid_ratio < 0.25:
        quality = "REJECT_LOW_QUALITY"
    elif issues:
        quality = "REVIEW_NEEDED"
    else:
        quality = "USABLE"

    act = engine.activity.summary()
    dominant_posture = max(act["durations_s"].items(), key=lambda kv: kv[1])[0] if act["durations_s"] else "UNKNOWN"

    report = {
        "video_id": vid,
        "path": str(video_path),
        "source_url": meta.get("source_url"),
        "platform": meta.get("platform"),
        "expected_activity": expected_activity,
        "expected_label": expected_binary,
        "predicted_label": predicted_binary,
        "match_expected": predicted_binary == expected_binary,
        "quality_verdict": quality,
        "quality_issues": issues,
        "frame_count": total,
        "valid_pose_ratio": valid_ratio,
        "multi_person_ratio": multi_ratio,
        "processing_fps": round(total / max(elapsed, 1e-6), 2),
        "max_fall_score": round(max_fall_score, 4),
        "first_alert_s": round(alerts[0]["timestamp"], 3) if alerts else None,
        "verified_fall": bool(verified),
        "dominant_posture": dominant_posture,
        "activity_summary": act,
        "anomaly_events": [
            {"kind": e["kind"], "timestamp_s": round(e["timestamp"], 3)}
            for e in (alerts + other_anomalies)
        ],
        "rendered_video": str(rendered_path) if rendered_path else None,
    }
    return report, feature_rows


def collect_videos_in_path(target_path):
    target = Path(target_path)
    if target.is_file():
        return [target]
    exts = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    vids = []
    for p in sorted(target.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        if "annotated" in p.parts or ".tmp_dl" in p.parts:
            continue
        vids.append(p)
    return vids


def save_analysis_outputs(reports, all_features, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "analysis_report.json"
    csv_path = out_dir / "analysis_report.csv"
    feat_path = out_dir / "custom_features.csv"

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(reports),
        "usable_videos": sum(1 for r in reports if r["quality_verdict"] == "USABLE"),
        "review_needed": sum(1 for r in reports if r["quality_verdict"] == "REVIEW_NEEDED"),
        "rejected_low_quality": sum(1 for r in reports if r["quality_verdict"] == "REJECT_LOW_QUALITY"),
        "matched_expected": sum(1 for r in reports if r["match_expected"]),
        "total_feature_frames": len(all_features),
        "videos": reports,
    }
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_cols = [
        "video_id", "expected_activity", "expected_label", "predicted_label", "match_expected",
        "quality_verdict", "quality_issues", "frame_count", "valid_pose_ratio", "multi_person_ratio",
        "processing_fps", "max_fall_score", "first_alert_s", "verified_fall", "dominant_posture",
        "platform", "source_url", "rendered_video",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols)
        w.writeheader()
        for r in reports:
            row = {k: r.get(k) for k in csv_cols}
            row["quality_issues"] = ";".join(r.get("quality_issues") or [])
            w.writerow(row)

    feat_cols = ["video_id", "video_label", "activity", "frame_idx", "timestamp_s", "posture_rule", "fall_score"] + FEATURE_NAMES
    with feat_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=feat_cols)
        w.writeheader()
        w.writerows(all_features)

    return json_path, csv_path, feat_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_dl = sub.add_parser("download", help="Download public videos from social media / web via yt-dlp")
    p_dl.add_argument("--url", help="Single public video URL (YouTube, TikTok, Facebook, Pexels, etc.)")
    p_dl.add_argument("--label", default="OTHER", help="Label: FALL, BENDING, LYING, SITTING, WALKING, STANDING, OTHER")
    p_dl.add_argument("--start", type=float, help="Optional trim start time in seconds")
    p_dl.add_argument("--end", type=float, help="Optional trim end time in seconds")
    p_dl.add_argument("--note", default="", help="Optional description note")
    p_dl.add_argument("--list", help="CSV file with batch URLs (columns: url,label,start_s,end_s,note)")
    p_dl.add_argument("--out", default=str(CUSTOM_ROOT), help="Output dataset directory")
    p_dl.add_argument("--max-height", type=int, default=480, help="Max video height in px (default: 480)")
    p_dl.add_argument("--analyze", action="store_true", help="Immediately run V2 AI analysis after downloading")
    p_dl.add_argument("--render-video", action="store_true", help="Render annotated MP4 with skeleton & risk meter")
    p_dl.add_argument("--config", default=str(ENGINE_DIR / "configs/v2_ml.json"))
    p_dl.add_argument("--model", default=str(ENGINE_DIR / "models/pose_landmarker_full.task"))

    p_an = sub.add_parser("analyze", help="Analyze local MP4 video(s) with V2 AI Engine & Data Quality Gate")
    p_an.add_argument("--input", default=str(CUSTOM_ROOT), help="Single video file or folder to analyze")
    p_an.add_argument("--label", help="Override expected activity label for single video")
    p_an.add_argument("--input-layout", choices=["auto", "rgb", "ur-rgbd"], default="auto")
    p_an.add_argument("--out", default=str(CUSTOM_ROOT), help="Directory for analysis_report & custom_features.csv")
    p_an.add_argument("--render-video", action="store_true", help="Export annotated MP4 videos")
    p_an.add_argument("--config", default=str(ENGINE_DIR / "configs/v2_ml.json"))
    p_an.add_argument("--model", default=str(ENGINE_DIR / "models/pose_landmarker_full.task"))

    p_sr = sub.add_parser("search", help="Search public videos across social media (TikTok, Facebook, Instagram, YouTube, Dailymotion, Vimeo, Pexels)")
    p_sr.add_argument("--category", choices=list(CATEGORY_PRESETS.keys()),
                      help="Targeted activity preset: fall (té ngã), bending (cúi người), lying (nằm), sitting (ngồi), walking (đi lại)")
    p_sr.add_argument("--query", default=None, help="Custom search keywords (optional if --category is provided)")
    p_sr.add_argument("--platforms", default="youtube,vimeo,dailymotion,pexels",
                      help=f"Comma-separated platforms from: {','.join(SUPPORTED_PLATFORMS)}")
    p_sr.add_argument("--limit", type=int, default=3, help="Max results per platform (default: 3)")
    p_sr.add_argument("--label", default=None, help="Expected activity label for found videos (defaults to category label)")
    p_sr.add_argument("--save-list", default=None,
                      help="Save discovered URLs to CSV (defaults to ai_engine/datasets/custom/discovered_<cat>.csv)")
    p_sr.add_argument("--download", action="store_true", help="Automatically download discovered public videos")
    p_sr.add_argument("--max-duration", type=float, default=45.0,
                      help="Trim downloaded clips to at most N seconds when --download is set (default: 45s)")
    p_sr.add_argument("--analyze", action="store_true", help="Run V2 AI analysis after downloading")
    p_sr.add_argument("--render-video", action="store_true", help="Export annotated MP4 videos")
    p_sr.add_argument("--out", default=str(CUSTOM_ROOT), help="Output directory")
    p_sr.add_argument("--config", default=str(ENGINE_DIR / "configs/v2_ml.json"))
    p_sr.add_argument("--model", default=str(ENGINE_DIR / "models/pose_landmarker_full.task"))

    p_kg = sub.add_parser("kaggle", help="Download Kaggle benchmark fall & activity video datasets")
    p_kg.add_argument("--dataset", choices=["caucafall", "le2i", "fall-video"], default="caucafall",
                      help="Kaggle dataset to download: caucafall (indoor falls+ADL), le2i (IMViA multi-room), fall-video")
    p_kg.add_argument("--out", default=str(ENGINE_DIR / "datasets/kaggle"), help="Destination directory")

    args = parser.parse_args()

    if args.command == "download":
        downloaded_paths = []
        if args.list:
            items = load_sources_csv(args.list)
        elif args.url:
            items = [{"url": args.url, "label": normalize_activity(args.label),
                      "start_s": args.start, "end_s": args.end, "note": args.note}]
        else:
            parser.error("Provide either --url or --list <sources.csv>")

        for item in items:
            try:
                meta = download_one(
                    item["url"], item["label"], out_root=args.out,
                    start_s=item["start_s"], end_s=item["end_s"],
                    note=item["note"], max_height=args.max_height,
                )
                print(f"[DOWNLOADED] {meta['video_id']} ({meta['duration_s']}s, {meta['width']}x{meta['height']}@{meta['fps']}fps) -> {meta['path']}", flush=True)
                downloaded_paths.append(Path(meta["path"]))
            except Exception as exc:
                print(f"[ERROR] Failed {item['url']}: {exc}", file=sys.stderr, flush=True)

        if args.analyze and downloaded_paths:
            cfg = Config.load(args.config)
            render_dir = Path(args.out) / "annotated" if args.render_video else None
            reports, all_feats = [], []
            for vp in downloaded_paths:
                rep, feats = analyze_video(vp, cfg, args.model, render_dir=render_dir)
                reports.append(rep)
                all_feats.extend(feats)
                print(f"[ANALYZED] {rep['video_id']} | quality={rep['quality_verdict']} | pred={rep['predicted_label']} (expected={rep['expected_label']}) | max_risk={rep['max_fall_score']:.2f} | posture={rep['dominant_posture']}", flush=True)
            j_p, c_p, f_p = save_analysis_outputs(reports, all_feats, args.out)
            print(f"Reports saved -> {j_p}\nExcel CSV     -> {c_p}\nML Features   -> {f_p}")

    elif args.command == "analyze":
        cfg = Config.load(args.config)
        videos = collect_videos_in_path(args.input)
        if not videos:
            print(f"No videos found in {args.input}")
            return
        render_dir = Path(args.out) / "annotated" if args.render_video else None
        reports, all_feats = [], []
        for vp in videos:
            rep, feats = analyze_video(
                vp, cfg, args.model,
                expected_activity=normalize_activity(args.label) if args.label else None,
                input_layout=args.input_layout,
                render_dir=render_dir,
            )
            reports.append(rep)
            all_feats.extend(feats)
            print(f"[ANALYZED] {rep['video_id']} | quality={rep['quality_verdict']} | pred={rep['predicted_label']} (expected={rep['expected_label']}) | max_risk={rep['max_fall_score']:.2f} | posture={rep['dominant_posture']} | {rep['processing_fps']} FPS", flush=True)
        j_p, c_p, f_p = save_analysis_outputs(reports, all_feats, args.out)
        print(f"Reports saved -> {j_p}\nExcel CSV     -> {c_p}\nML Features   -> {f_p}")

    elif args.command == "search":
        if not args.query and not args.category:
            parser.error("Specify either --category {fall,bending,lying,sitting,walking} or --query '<keywords>'")
        
        query = args.query
        label = args.label
        if args.category:
            preset = CATEGORY_PRESETS[args.category]
            if not query:
                query = preset["queries"][0]
            if not label:
                label = preset["label"]
            print(f"[CATEGORY PRESET] '{args.category.upper()}' -> {preset['description']}")
        
        label = normalize_activity(label or "OTHER")
        platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
        print(f"Searching academic/indoor queries: '{query}' across: {', '.join(platforms)} (limit={args.limit}/platform)...", flush=True)
        hits = search_multi_platform(query, platforms, limit_per_platform=args.limit)
        if not hits:
            print("No public videos found for query.")
            return
        
        save_path_str = args.save_list or str(CUSTOM_ROOT / f"discovered_{args.category or 'custom'}.csv")
        save_path = Path(save_path_str)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["url", "label", "start_s", "end_s", "note"])
            w.writeheader()
            for h in hits:
                w.writerow({
                    "url": h["url"],
                    "label": label,
                    "start_s": "",
                    "end_s": args.max_duration if args.max_duration else "",
                    "note": f"[{h['platform']}] {h['title'][:80]}",
                })
        for i, h in enumerate(hits, start=1):
            print(f"  {i:2d}. [{h['platform']:11s}] {h['title'][:58]:58s} | {h['url']}")
        print(f"\nSaved {len(hits)} discovered URLs -> {save_path}")

        if args.download:
            downloaded_paths = []
            target_out = Path(args.out) / (args.category or "")
            for h in hits:
                try:
                    meta = download_one(
                        h["url"], label, out_root=target_out,
                        start_s=0.0, end_s=args.max_duration,
                        note=f"[{h['platform']}] {h['title'][:80]}",
                    )
                    print(f"[DOWNLOADED] {meta['video_id']} ({meta['duration_s']}s) -> {meta['path']}", flush=True)
                    downloaded_paths.append(Path(meta["path"]))
                except Exception as exc:
                    print(f"[SKIP] {h['platform']} {h['url']}: {exc}", file=sys.stderr, flush=True)
            if args.analyze and downloaded_paths:
                cfg = Config.load(args.config)
                render_dir = target_out / "annotated" if args.render_video else None
                reports, all_feats = [], []
                for vp in downloaded_paths:
                    rep, feats = analyze_video(vp, cfg, args.model, render_dir=render_dir)
                    reports.append(rep)
                    all_feats.extend(feats)
                    print(f"[ANALYZED] {rep['video_id']} | quality={rep['quality_verdict']} | pred={rep['predicted_label']} | max_risk={rep['max_fall_score']:.2f} | posture={rep['dominant_posture']}", flush=True)
                j_p, c_p, f_p = save_analysis_outputs(reports, all_feats, target_out)
                print(f"Reports saved -> {j_p}\nExcel CSV     -> {c_p}\nML Features   -> {f_p}")

    elif args.command == "kaggle":
        KAGGLE_MAP = {
            "caucafall": ("caucat/caucafall", "CAUCAFall - Multi-camera home falls and ADLs (walking, sitting, bending, lying)"),
            "le2i": ("uttejkumarkolla/le2i-fall-dataset", "Le2i IMViA - 191 multi-room surveillance falls & ADL"),
            "fall-video": ("600360-ปยุต-เจริญศรี/fall-video-dataset", "Fall Video Dataset - Pre-clipped falls and daily living activities"),
        }
        dataset_slug, desc = KAGGLE_MAP[args.dataset]
        out_dir = Path(args.out) / args.dataset
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"[KAGGLE] Target dataset: {dataset_slug}")
        print(f"         Description:    {desc}")
        print(f"         Destination:    {out_dir}")
        print("\nChecking Kaggle authentication...")
        res = subprocess.run([sys.executable, "-m", "kaggle", "datasets", "download", "-d", dataset_slug, "--unzip", "-p", str(out_dir)], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"[SUCCESS] Downloaded and extracted {dataset_slug} to {out_dir}")
        else:
            print("\n[NOTE] Kaggle API requires authentication.")
            print(f"You can login via Kaggle CLI:")
            print(f"  1. Run: .venv/bin/kaggle auth login   (or export KAGGLE_API_TOKEN=xxx)")
            print(f"  2. Or download directly via web browser from:\n     https://www.kaggle.com/datasets/{dataset_slug}")
            print(f"     and extract the zip file to: {out_dir}")


if __name__ == "__main__":
    main()
