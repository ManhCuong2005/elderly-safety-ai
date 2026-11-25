import argparse
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import av
from PIL import Image, ImageDraw, ImageOps

from .dataset import CATALOG, FALL, MANIFEST, MEDIA_NAME, NORMAL, RAW
from .pose import CONFIG, video_frames, video_info
from .storage import ROOT, atomic, read_json, rows, safe, sha, write_json, write_rows

VIDEOS = ROOT / "data/manifests/videos.csv"
ANNOTATIONS = ROOT / "data/annotations/confirmed.json"
OVERRIDES = ROOT / "data/review/overrides.json"


def annotation(value, duration):
    label = value.get("label")
    reason = str(value.get("note", "")).strip()[:500]
    if label not in {"Fall", "No_Fall", "unknown"} or not reason:
        raise ValueError("Chọn nhãn và ghi căn cứ quan sát")

    def seconds(number):
        if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= duration:
            raise ValueError("Thời điểm phải nằm trong video (giây)")
        return round(number, 3)

    intervals = value.get("negative", [])
    if not isinstance(intervals, list) or len(intervals) > 100:
        raise ValueError("Danh sách khoảng No_Fall không hợp lệ")
    negative = []
    for interval in intervals:
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError("Mỗi khoảng No_Fall cần hai mốc")
        start, end = map(seconds, interval)
        if start >= end or (negative and start < negative[-1][1]):
            raise ValueError("Khoảng No_Fall phải theo thứ tự và không chồng nhau")
        negative.append([start, end])
    if label == "Fall":
        onset, impact = seconds(value.get("onset_s")), seconds(value.get("impact_s"))
        if onset >= impact or any(end > onset and start < impact for start, end in negative):
            raise ValueError("Mốc mất thăng bằng phải trước mốc chạm, ngoài khoảng No_Fall")
    else:
        onset = impact = None
    if label == "No_Fall" and not negative:
        raise ValueError("Đánh dấu ít nhất một khoảng No_Fall")
    if label == "unknown":
        negative = []
    return {"label": label, "onset_s": onset, "impact_s": impact, "negative": negative, "note": reason}


def save_annotation(video, value, reviewer):
    if video["status"] == "exclude" or not video["duration_s"]:
        raise ValueError("Clip không thể gán nhãn")
    if sha(safe(video["relative_path"])) != video["sha256"]:
        raise ValueError("Video đã thay đổi. Kiểm kê lại trước khi gán nhãn.")
    data = read_json(ANNOTATIONS, {})
    data[video["video_id"]] = {
        **annotation(value, float(video["duration_s"])),
        "video_id": video["video_id"], "subject_id": video["subject_id"],
        "original_label": video["original_label"], "video_sha256": video["sha256"],
        "confirmed_by": reviewer,
    }
    write_json(ANNOTATIONS, data)
    return data[video["video_id"]]


def inspect(item, subject_map, people, overrides):
    path = safe(item["relative_path"])
    if not path.is_relative_to(RAW):
        raise ValueError("File ngoài dữ liệu gốc")
    group, folder, filename = path.relative_to(RAW).parts
    match = MEDIA_NAME.fullmatch(filename)
    person = match[1] if match else "unknown"
    video_id = f"{group}/{folder}"
    override = overrides.get(video_id, {})
    map_row = subject_map.get((person, group))
    meta_file = path.with_name(f"{person}_Metadata.csv")
    metadata = rows(safe(meta_file.relative_to(ROOT).as_posix()))
    meta = metadata[0] if len(metadata) == 1 else {}
    known = (person in people and map_row and meta.get("person_id") == person
             and meta.get("activity") == group and meta.get("sensor_file") == map_row["sensor_file"]
             and meta.get("batch_num") == people[person]["batch_num"])
    digest = sha(path)
    result = {
        "video_id": video_id, "relative_path": item["relative_path"], "source": item["source"],
        "sha256": digest, "dataset_version": item["dataset_version"],
        "source_subject_id": person, "source_folder_id": folder,
        "subject_id": person if known and not override.get("subject_unknown") else "unknown",
        "recording_id": map_row["sensor_file"] if known else "unknown",
        "original_label": group, "expected_label": "Fall" if group in FALL else "No_Fall",
        "duration_s": "", "fps": "", "width": "", "height": "", "rotation_ccw": "",
        "rotation_override_ccw": override.get("rotation_ccw", ""), "codec": "",
        "status": "review", "reason": "Chờ xem và xác nhận mốc", "duplicate_of": "",
    }
    if digest != item["sha256"]:
        return {**result, "status": "exclude", "reason": "Checksum khác manifest tải"}
    if not known:
        result["reason"] = "Mã người/lượt quay thiếu hoặc không khớp bảng nguồn"
    elif folder != person:
        result["reason"] += f". Tên file và metadata xác nhận {person} trong thư mục {folder}"
    if override.get("subject_unknown"):
        result["reason"] = override["subject_unknown"]
    try:
        result.update(video_info(path))
        corrected = override.get("rotation_ccw")
        if corrected is not None and (corrected - result["rotation_ccw"]) % 180:
            result["width"], result["height"] = result["height"], result["width"]
    except (av.FFmpegError, ValueError, StopIteration, IndexError):
        try:
            next(video_frames(path, CONFIG["sample_hz"]))
        except (av.FFmpegError, ValueError, StopIteration, IndexError):
            result.update(status="exclude", reason="Không giải mã được sau lần đọc lại")
        else:
            result["reason"] = "Giải mã được nhưng cần xác minh metadata video"
    return result


def inventory():
    source = rows(MANIFEST)
    people = {row["person"]: row for row in rows(safe("final_person_list_with_batch.csv", RAW))}
    mapping = {(row["person_id"], row["activity"]): row for row in rows(safe("age_to_person_map.csv", RAW))}
    annotations = read_json(ANNOTATIONS, {})
    overrides = read_json(OVERRIDES, {})
    videos = [item for item in source if item["original_name"].lower().endswith(".mp4")]
    with ThreadPoolExecutor(max_workers=3) as pool:
        clips = list(pool.map(lambda item: inspect(item, mapping, people, overrides), videos))
    hashes = {}
    def priority(row):
        mark = annotations.get(row["video_id"], {})
        confirmed = mark.get("video_sha256") == row["sha256"] and mark.get("label") in {"Fall", "No_Fall"}
        return row["subject_id"] == "unknown", not confirmed

    for clip in sorted(clips, key=priority):
        if clip["status"] == "exclude":
            continue
        duplicate = hashes.get(clip["sha256"])
        if duplicate:
            clip.update(status="exclude", reason="Trùng byte với bản giữ lại", duplicate_of=duplicate)
            continue
        hashes[clip["sha256"]] = clip["video_id"]
        mark = annotations.get(clip["video_id"], {})
        if mark.get("video_sha256") == clip["sha256"] and mark.get("label") in {"Fall", "No_Fall"}:
            if clip["subject_id"] != "unknown" and mark.get("subject_id") == clip["subject_id"]:
                clip.update(status="keep", reason="Đã xác nhận nhãn thời gian")
        elif mark.get("label") == "unknown":
            clip["reason"] += " | " + mark["note"]
    if clips:
        write_rows(VIDEOS, clips)
    full = Counter(row["name"].split("/")[0] for row in rows(CATALOG) if row["name"].endswith(".mp4"))
    groups = defaultdict(Counter)
    for clip in clips:
        groups[clip["original_label"]][clip["status"]] += 1
    people_count = len({clip["subject_id"] for clip in clips} - {"unknown"})
    kept_labels = Counter(annotations[c["video_id"]]["label"] for c in clips if c["status"] == "keep")
    summary = [
        "# Kiểm kê VARISHTA-MM50", "",
        f"- Video trong danh mục v5: {sum(full.values())}.",
        f"- Video lưu tại project: {len(clips)}. Trong đó do pipeline tải: "
        f"{sum(item['project_download'] == 'yes' and item['original_name'].endswith('.mp4') for item in source)}.",
        f"- Mã người đối chiếu được: {people_count}. Clip chưa rõ người: "
        f"{sum(c['subject_id'] == 'unknown' for c in clips)}.",
        f"- Nhãn thư mục: {sum(c['expected_label'] == 'Fall' for c in clips)} Fall, "
        f"{sum(c['expected_label'] == 'No_Fall' for c in clips)} No_Fall.",
        f"- Đã xác nhận và đạt điều kiện nhãn: {kept_labels['Fall']} Fall, {kept_labels['No_Fall']} No_Fall.",
        "", "| Nhóm gốc | Danh mục | Video tại project | Keep | Review | Exclude |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in sorted(FALL | NORMAL):
        counts = groups[group]
        summary.append(f"| {group} | {full[group]} | {sum(counts.values())} | "
                       f"{counts['keep']} | {counts['review']} | {counts['exclude']} |")
    summary.extend(["", "Nguồn mã người và lượt quay: Metadata.csv, age_to_person_map.csv, "
                    "final_person_list_with_batch.csv. Báo cáo dựa trên danh mục API v5 và file đã lưu.",
                    "Mã người đếm theo metadata đã đối chiếu. Kiểm kê ghi bản trùng và mâu thuẫn đã phát hiện.",
                    "Kiểm kê đọc metadata và khung hình đầu. Các clip chưa có mốc xác nhận tiếp tục ở trạng thái review.",
                    "Các file gốc được giữ để đối chiếu."])
    atomic(safe("reports/dataset_summary.md"), ("\n".join(summary) + "\n").encode())
    print(f"{len(clips)} video, {people_count} mã người, {dict(Counter(c['status'] for c in clips))}")
    return clips


def rotation_for(clip):
    value = clip.get("rotation_override_ccw", "")
    return int(value) if value != "" else None


def sheet(clip, hz, start=0, end=None, tag=""):
    path = safe(clip["relative_path"])
    thumb = (240, 135)
    samples = []
    for t, image in video_frames(path, hz, rotation_for(clip)):
        if end is not None and t > end:
            break
        if t >= start:
            samples.append((t, ImageOps.contain(image, thumb)))
    if not samples:
        raise ValueError(f"Không có khung hình trong khoảng chọn: {clip['video_id']}")
    cols = 4
    width, height = thumb[0], thumb[1] + 20
    canvas = Image.new("RGB", (cols * width, math.ceil(len(samples) / cols) * height), "#13212c")
    font = ImageDraw.Draw(canvas)
    for i, (t, image) in enumerate(samples):
        x, y = i % cols * width, i // cols * height
        canvas.paste(image, (x + (width - image.width) // 2, y + (thumb[1] - image.height) // 2))
        font.text((x + 6, y + thumb[1] + 2), f"{t:.2f} s", fill="white")
    name = clip["video_id"].replace("/", "_")
    target = safe(f"data/review/{name}{tag}.jpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, quality=89)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inventory", "sheets"])
    parser.add_argument("--video")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--hz", type=float)
    args = parser.parse_args()
    if args.command == "inventory":
        inventory()
    else:
        clips = [clip for clip in rows(VIDEOS) if clip["duration_s"] and clip["status"] != "exclude"
                 and (args.video is None or clip["video_id"] == args.video)]
        with ThreadPoolExecutor(max_workers=3) as pool:
            for path in pool.map(lambda clip: sheet(clip, args.hz or 12 / float(clip["duration_s"]),
                                                   args.start, args.end, "_detail" if args.video else ""), clips):
                print(path)
