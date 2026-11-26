"""Self-recording helper for collecting custom labeled webcam videos (Task 1.1).

Usage:
    python ai_engine/scripts/record_samples.py --label BENDING --subject sv01 --duration 8
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
import cv2

LABELS = ("STANDING", "SITTING", "WALKING", "BENDING", "LYING", "FALL")
OUT_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "custom"


def main():
    p = argparse.ArgumentParser(description="Record labeled webcam clips for custom dataset extension.")
    p.add_argument("--camera", type=int, default=0, help="Webcam index (default: 0)")
    p.add_argument("--label", choices=LABELS, required=True, help="Activity / fall label")
    p.add_argument("--subject", default="subject01", help="Participant ID for subject-independent split")
    p.add_argument("--duration", type=float, default=8.0, help="Clip duration in seconds")
    p.add_argument("--countdown", type=int, default=3, help="Seconds before recording starts")
    p.add_argument("--fps", type=int, default=20)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    args = p.parse_args()

    out_dir = OUT_ROOT / args.label.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clip_id = f"custom-{args.label.lower()}-{args.subject}-{stamp}"
    video_path = out_dir / f"{clip_id}.mp4"
    meta_path = out_dir / f"{clip_id}.json"

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = None
    timestamps = []
    try:
        t0 = time.monotonic()
        while time.monotonic() - t0 < args.countdown:
            ok, frame = cap.read()
            if not ok:
                break
            rem = max(0.0, args.countdown - (time.monotonic() - t0))
            cv2.putText(frame, f"READY [{args.label}] in {rem:.1f}s (Q to cancel)",
                        (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
            cv2.imshow("An Tam - Dataset Recorder", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                return

        ok, first = cap.read()
        if not ok:
            raise RuntimeError("Failed to read from webcam")
        h, w = first.shape[:2]
        writer = cv2.VideoWriter(str(video_path), fourcc, args.fps, (w, h))
        rec_start = time.monotonic()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            elapsed = time.monotonic() - rec_start
            if elapsed >= args.duration:
                break
            writer.write(frame)
            timestamps.append(round(elapsed, 4))
            vis = frame.copy()
            cv2.putText(vis, f"REC [{args.label}] {elapsed:.1f}/{args.duration:.1f}s (Q stop)",
                        (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 240), 2)
            cv2.imshow("An Tam - Dataset Recorder", vis)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        if writer:
            writer.release()
        cv2.destroyAllWindows()

    if timestamps:
        meta = {
            "video_id": clip_id,
            "label": "FALL" if args.label == "FALL" else "NON_FALL",
            "activity": args.label,
            "subject_id": args.subject,
            "path": str(video_path),
            "frame_count": len(timestamps),
            "duration_s": timestamps[-1],
            "timestamps_s": timestamps,
            "input_layout": "rgb",
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"Saved {len(timestamps)} frames -> {video_path}")
        print(f"Metadata -> {meta_path}")


if __name__ == "__main__":
    main()
