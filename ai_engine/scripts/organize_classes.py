"""Organize elderly safety datasets into 5 standard evaluation categories:
├── fall/        # Video té ngã (ngã trước, ngã ngửa, trượt chân, ngã ghế)
├── bending/     # Video cúi người nhặt đồ, buộc dây giày (tránh báo động giả)
├── lying/       # Video nằm chủ động xuống giường/sofa/thảm
├── sitting/     # Video ngồi xuống nhanh, đứng lên/ngồi xuống
└── walking/     # Video đi lại, đứng sinh hoạt bình thường
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSES_DIR = ROOT / "datasets" / "classes"
RAW_DIR = ROOT / "datasets" / "raw"

# Mappings of UR Fall videos to specific activity categories based on ground-truth motions
URFALL_MAPPING = {
    "fall": [f"fall-{i:02d}-cam0.mp4" for i in range(1, 31)],
    "bending": [
        "adl-04-cam0.mp4",  # cúi nhặt đồ (pick up object from floor)
        "adl-05-cam0.mp4",  # cúi nhặt đồ
        "adl-06-cam0.mp4",  # cúi nhặt đồ
        "adl-09-cam0.mp4",  # cúi người
    ],
    "sitting": [
        "adl-01-cam0.mp4",  # ngồi ghế & đứng dậy
        "adl-02-cam0.mp4",  # ngồi xuống ghế
        "adl-03-cam0.mp4",  # ngồi ghế làm việc
        "adl-07-cam0.mp4",  # ngồi xuống ghế
        "adl-08-cam0.mp4",  # ngồi ghế thư giãn
        "adl-10-cam0.mp4",  # ngồi xuống đứng lên
    ],
    "lying": [
        "adl-11-cam0.mp4",  # nằm chủ động xuống giường/ghế dài
    ],
    "walking": [
        f"adl-{i:02d}-cam0.mp4" for i in range(13, 31)  # đi bộ qua lại phòng khách
    ],
}


def populate_from_raw():
    for cat in ["fall", "bending", "lying", "sitting", "walking"]:
        (CLASSES_DIR / cat).mkdir(parents=True, exist_ok=True)

    copied = {cat: 0 for cat in URFALL_MAPPING}
    for cat, files in URFALL_MAPPING.items():
        dst_dir = CLASSES_DIR / cat
        for fname in files:
            src = RAW_DIR / fname
            if src.exists():
                dst = dst_dir / f"{cat}_{fname}"
                if not dst.exists():
                    try:
                        os.symlink(src.resolve(), dst)
                    except OSError:
                        shutil.copy2(src, dst)
                copied[cat] += 1
    return copied


if __name__ == "__main__":
    stats = populate_from_raw()
    print("Populated standard benchmark classes in:", CLASSES_DIR)
    for cat, count in stats.items():
        print(f"  ├── {cat:8s}: {count:2d} videos")
