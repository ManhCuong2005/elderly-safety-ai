import argparse
import hashlib
import io
import json
import random
from collections import Counter
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .inference import Engine, NO_PERSON, SCHEMA, UNCLEAR, web_result
from .keypoints import get_keypoints, metadata
from .pose import CONFIG, MODEL
from .review import ANNOTATIONS, VIDEOS, annotation, inventory
from .storage import ROOT, atomic, read_json, rows, safe, sha, write_json, write_rows

SPLIT = ROOT / "data/manifests/split.csv"
SPLIT_POLICY = ROOT / "data/manifests/split_policy.json"
DEMO = ROOT / "data/manifests/model_videos.csv"
ARTIFACT = ROOT / "models/classifier.joblib"
MODEL_INFO = ROOT / "models/classifier.json"
PARTS = ("train", "validation", "test")
FALSE_ALARMS_TARGET = 1
THRESHOLDS = [round(x / 100, 2) for x in range(5, 100, 5)] + [0.98, 0.99]


def eligible(excluded=()):
    confirmed = read_json(ANNOTATIONS, {})
    clips = []
    for video in rows(VIDEOS):
        if video["status"] != "keep" or video["subject_id"] == "unknown" or video["subject_id"] in excluded:
            continue
        mark = confirmed.get(video["video_id"], {})
        if mark.get("video_sha256") != video["sha256"] or mark.get("subject_id") != video["subject_id"]:
            raise ValueError(f"Nhãn đã đổi. Chạy Inventory: {video['video_id']}")
        mark = annotation(mark, float(video["duration_s"]))
        if mark["label"] in {"Fall", "No_Fall"}:
            clips.append({**video, **mark})
    return clips


def connected_people(clips):
    parents = {clip["subject_id"]: clip["subject_id"] for clip in clips}

    def root(person):
        while parents[person] != person:
            person = parents[person]
        return person

    for field in ("recording_id", "sha256"):
        owner = {}
        for clip in clips:
            key, person = clip[field], clip["subject_id"]
            if key in {"", "unknown"}:
                raise ValueError(f"Thiếu {field}: {clip['video_id']}")
            if key in owner:
                parents[root(person)] = root(owner[key])
            owner[key] = person
    return {person: root(person) for person in parents}


def assert_split(clips, related=()):
    for field in ("subject_id", "recording_id", "sha256", "video_id"):
        mapping = {}
        for clip in clips:
            key, part = clip[field], clip["split"]
            if key in mapping and mapping[key] != part:
                raise ValueError(f"Giao nhau giữa tập theo {field}: {key}")
            mapping[key] = part
    if related:
        groups = connected_people([*clips, *related])
        partitions = {}
        for clip in clips:
            group, part = groups[clip["subject_id"]], clip["split"]
            if group in partitions and partitions[group] != part:
                raise ValueError(f"Giao nhau theo bản sao/lượt quay trong dữ liệu gốc: {group}")
            partitions[group] = part
    for part in PARTS:
        labels = {clip["label"] for clip in clips if clip["split"] == part}
        if labels != {"Fall", "No_Fall"}:
            raise ValueError(f"Tập {part} cần cả Fall và No_Fall")


def assign_splits(clips, seed, test_excluded=(), related=()):
    all_groups = connected_people([*clips, *related])
    groups = {clip["subject_id"]: all_groups[clip["subject_id"]] for clip in clips}
    independents = sorted(set(groups.values()))
    if len(independents) < 3:
        raise ValueError("Cần ít nhất ba nhóm người độc lập có nhãn xác nhận")
    group_labels = {group: set() for group in independents}
    for clip in clips:
        group_labels[groups[clip["subject_id"]]].add(clip["label"])
    if any(sum(label in labels for labels in group_labels.values()) < 3 for label in ("Fall", "No_Fall")):
        raise ValueError("Mỗi lớp cần video đã xác nhận của ít nhất ba nhóm người độc lập")
    rng = random.Random(seed)
    held = max(1, round(len(independents) * 0.2))
    cannot_test = {all_groups[p] for p in test_excluded if p in all_groups}
    fresh = set(independents) - cannot_test
    if len(fresh) < held:
        raise ValueError("Cần thêm người mới có nhãn xác nhận cho test")
    fall_groups = sum("Fall" in labels for labels in group_labels.values())
    minimum = 2 if fall_groups >= 8 and held >= 2 else 1
    for attempt in range(2000):
        rng.shuffle(independents)
        test = [group for group in independents if group in fresh][:held]
        validation = [group for group in independents if group not in test][:held]
        by_group = {group: "test" if group in test else "validation" if group in validation else "train"
                    for group in independents}
        labels = {part: set() for part in PARTS}
        falls = Counter()
        for group, part in by_group.items():
            labels[part].update(group_labels[group])
            falls[part] += "Fall" in group_labels[group]
        need = minimum if attempt < 1600 else 1
        if all(len(v) == 2 for v in labels.values()) and all(falls[part] >= need for part in PARTS):
            return {person: by_group[group] for person, group in groups.items()}
    raise ValueError("Chưa chia được ba tập đủ hai lớp theo người")


def related_videos():
    return [video for video in rows(VIDEOS)
            if video["subject_id"] != "unknown" and video["recording_id"] != "unknown"
            and (video["status"] != "exclude" or video["duplicate_of"])]


def split(rebuild=False, fresh_test=False):
    inventory()
    fixed = rows(SPLIT)
    policy = read_json(SPLIT_POLICY, {"excluded": [], "test_excluded": []})
    if fresh_test:
        if not (rebuild and fixed):
            raise ValueError("FreshTest cần split cũ và cờ Rebuild")
        policy["excluded"] = sorted(set(policy["excluded"]) | {r["subject_id"] for r in fixed if r["split"] == "test"})
        policy["test_excluded"] = sorted(set(policy["test_excluded"]) | {r["subject_id"] for r in fixed})
    clips = eligible(policy["excluded"])
    if SPLIT.exists() and not rebuild:
        if {r["video_id"] for r in fixed} != {c["video_id"] for c in clips}:
            raise ValueError("Tập clip đã đổi. Dùng Split -Rebuild để tạo phiên chia mới.")
        load_split()
        return fixed
    related = related_videos()
    assignment = assign_splits(clips, CONFIG["seed"], policy["test_excluded"], related)
    fields = ["video_id", "subject_id", "recording_id", "sha256", "original_label",
              "relative_path", "label", "split", "seed"]
    for clip in clips:
        clip.update(split=assignment[clip["subject_id"]], seed=CONFIG["seed"])
    assert_split(clips, related)
    fixed = [{field: clip[field] for field in fields} for clip in clips]
    write_rows(SPLIT, fixed, fields)
    if fresh_test:
        write_json(SPLIT_POLICY, policy)
    for part in PARTS:
        print(part, dict(Counter(c["label"] for c in fixed if c["split"] == part)))
    return fixed


def load_split():
    policy = read_json(SPLIT_POLICY, {})
    current = {clip["video_id"]: clip for clip in eligible(policy.get("excluded", []))}
    result = []
    entries = rows(SPLIT)
    if not entries:
        raise ValueError("Chưa có split cố định. Chạy Split sau khi xác nhận nhãn.")
    for entry in entries:
        video = current.get(entry["video_id"], {})
        if any(video.get(field) != entry[field]
               for field in ("subject_id", "sha256", "recording_id", "label", "relative_path")):
            raise ValueError(f"Manifest và split không khớp: {entry['video_id']}")
        result.append({**video, "split": entry["split"]})
    related = related_videos()
    assert_split(result, related)
    groups = connected_people([*result, *related])
    old_groups = {groups[p] for p in policy.get("test_excluded", []) if p in groups}
    if any(c["split"] == "test" and groups[c["subject_id"]] in old_groups for c in result):
        raise ValueError("Test có người đã tham gia đợt trước")
    return result


def window_label(clip, t, cfg):
    left = t - cfg["window_s"]
    if clip["label"] == "Fall":
        onset, impact = clip["onset_s"], clip["impact_s"]
        overlap = min(t, impact) - max(left, onset)
        minimum = min(cfg["positive_after_onset_s"], (impact - onset) * 0.75)
        if overlap >= minimum and t <= impact + cfg["positive_after_impact_s"]:
            return 1
    if any(left >= start - 1e-8 and t <= end for start, end in clip["negative"]):
        return 0
    return None


def make_windows(clips, cfg, cache):
    x, y, counts = [], [], {}
    windows = []
    for clip in clips:
        engine = Engine(cfg)
        examples = Counter()
        for obs in cache[clip["video_id"]]:
            frame = engine.step(obs)
            label = window_label(clip, obs.t, cfg)
            if frame["features"] is not None and label is not None:
                x.append(frame["features"])
                y.append(label)
                examples[label] += 1
                windows.append({"video_id": clip["video_id"], "timestamp_s": obs.t,
                                "window_start_s": obs.t - cfg["window_s"],
                                "label": "Fall" if label else "No_Fall",
                                **dict(zip(SCHEMA, frame["features"]))})
        counts[clip["video_id"]] = {"Fall": examples[1], "No_Fall": examples[0]}
    if set(y) != {0, 1}:
        raise ValueError("Train chưa có cửa sổ hợp lệ của cả hai lớp sau kiểm tra vai/hông và mốc sự kiện")
    write_rows(safe("data/processed/train_windows.csv"), windows)
    return np.stack(x), np.asarray(y), counts


def replay(observations, cfg, classifier=None, threshold=None, web=False, probabilities=None):
    engine = Engine(cfg, classifier, threshold, probabilities)
    if web:
        return [web_result(engine, obs) for obs in observations]
    return [engine.step(obs) for obs in observations]


def score_events(clips, traces, cfg):
    total = Counter()
    delays, mistakes, per_video = [], [], []
    for clip in clips:
        trace = traces[clip["video_id"]]
        intervals = clip["negative"]
        negative = sum(end - start for start, end in intervals) if clip["label"] == "No_Fall" else 0
        alarms = [row["t"] for row in trace if row["alarm"]]
        onset, impact = clip["onset_s"], clip["impact_s"]
        matched = None
        if clip["label"] == "Fall":
            total["events"] += 1
            matched = next((t for t in alarms if onset - cfg["match_before_s"] <= t
                            <= impact + cfg["match_after_impact_s"]), None)
            if matched is None:
                mistakes.append({"video_id": clip["video_id"], "relative_path": clip["relative_path"],
                                 "issue": "missed_fall", "timestamp_s": onset})
            else:
                delays.append(matched - impact)
        false = [t for t in alarms if clip["label"] == "No_Fall"
                 and any(start <= t <= end for start, end in intervals)]
        for t in false:
            mistakes.append({"video_id": clip["video_id"], "relative_path": clip["relative_path"],
                             "issue": "false_alarm", "timestamp_s": t})
        for t in alarms:
            if t != matched and t not in false:
                mistakes.append({"video_id": clip["video_id"], "relative_path": clip["relative_path"],
                                 "issue": "unmatched_outside_scored_adl", "timestamp_s": t})
        lost = Counter()
        duration = float(clip["duration_s"])
        for index, frame in enumerate(trace):
            end = trace[index + 1]["t"] if index + 1 < len(trace) else duration
            gap = max(0, min(end, duration) - frame["t"])
            if gap > cfg["max_gap_s"]:
                lost[UNCLEAR] += gap - cfg["max_gap_s"]
                gap = cfg["max_gap_s"]
            lost[frame["state"]] += gap
        total.update(false=len(false), negative_s=negative, video_s=duration,
                     unclear_s=lost[UNCLEAR], no_person_s=lost[NO_PERSON],
                     unmatched=len(alarms) - len(false) - (matched is not None))
        per_video.append({"video_id": clip["video_id"], "label": clip["label"],
                          "alarms_s": alarms, "matched_s": matched, "onset_s": onset,
                          "impact_s": impact, "no_fall_s": negative, "unclear_s": lost[UNCLEAR],
                          "no_person_s": lost[NO_PERSON]})
    n = len(delays)
    return {"videos": len(clips), "people": len({c["subject_id"] for c in clips}),
            "events": total["events"], "detected": n, "missed": total["events"] - n,
            "recall": n / total["events"] if total["events"] else None,
            "false_alarms": total["false"], "negative_s": total["negative_s"],
            "false_per_hour": total["false"] * 3600 / total["negative_s"] if total["negative_s"] else None,
            "video_s": total["video_s"], "unclear_s": total["unclear_s"], "no_person_s": total["no_person_s"],
            "other_unmatched": total["unmatched"], "latency_s": delays,
            "median_latency_s": float(np.median(delays)) if n else None,
            "mistakes": mistakes, "per_video": per_video}


def evaluation(clips, cache, cfg, classifier, threshold):
    traces = {v["video_id"]: replay(cache[v["video_id"]], cfg, classifier, threshold) for v in clips}
    return score_events(clips, traces, cfg)


def compare_validation(clips, cache, cfg, candidates):
    feature_frames = {}
    for clip in clips:
        key = clip["video_id"]
        feature_frames[key] = [(row["t"], row["features"]) for row in replay(cache[key], cfg)
                               if row["features"] is not None]
    result = []
    for name, model in candidates.items():
        scores = {}
        for key, features in feature_frames.items():
            scores[key] = {}
            if features:
                times, x = zip(*features)
                scores[key] = dict(zip(times, model.predict_proba(np.stack(x))[:, 1].tolist()))
        for threshold in THRESHOLDS:
            traces = {key: replay(cache[key], cfg, threshold=threshold, probabilities=probabilities)
                      for key, probabilities in scores.items()}
            stats = score_events(clips, traces, cfg)
            result.append({"classifier": name, "threshold": threshold, **stats})
    return result


def rank(result):
    latency = result["median_latency_s"]
    return (-result["detected"], result["false_alarms"], result["other_unmatched"],
            latency if latency is not None else float("inf"),
            result["classifier"] != "Logistic Regression", abs(result["threshold"] - 0.5))


def training_snapshot(clips):
    values = [{key: clip[key] for key in ("video_id", "split", "sha256", "label", "onset_s",
                                         "impact_s", "negative")} for clip in clips if clip["split"] != "test"]
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def train():
    clips = load_split()
    training = [c for c in clips if c["split"] == "train"]
    validation = [c for c in clips if c["split"] == "validation"]
    cfg = CONFIG
    cache = {c["video_id"]: get_keypoints(c, cfg) for c in training + validation}
    x, y, counts = make_windows(training, cfg, cache)
    candidates = {
        "Logistic Regression": make_pipeline(SimpleImputer(keep_empty_features=True), StandardScaler(),
                                              LogisticRegression(class_weight="balanced", random_state=cfg["seed"])),
        "Random Forest": make_pipeline(SimpleImputer(keep_empty_features=True),
                                      RandomForestClassifier(n_estimators=120, min_samples_leaf=3,
                                                             class_weight="balanced", random_state=cfg["seed"])),
    }
    for model in candidates.values():
        model.fit(x, y)
    results = compare_validation(validation, cache, cfg, candidates)
    if not results[0]["negative_s"]:
        raise ValueError("Validation cần khoảng No_Fall đã xác nhận")
    allowed = int(FALSE_ALARMS_TARGET * results[0]["negative_s"] / 3600)
    if not any(r["detected"] and r["false_alarms"] <= allowed for r in results):
        # Apply one common observed count budget when minutes of ADL make the hourly target too coarse.
        allowed = min((r["false_alarms"] for r in results if r["detected"]),
                      default=min(r["false_alarms"] for r in results))
    within = [r for r in results if r["false_alarms"] <= allowed]
    best = [min((r for r in within if r["classifier"] == name), key=rank, default=None) for name in candidates]
    for i, result in enumerate(best):
        if result is None:
            name = list(candidates)[i]
            best[i] = min((r for r in results if r["classifier"] == name), key=lambda r: (r["false_alarms"], rank(r)))
    selected = min(within, key=rank)
    chosen = selected["classifier"]
    buffer = io.BytesIO()
    joblib.dump(candidates[chosen], buffer, compress=3)
    atomic(ARTIFACT, buffer.getvalue())
    digest = sha(ARTIFACT)
    run = {
        "model_id": f"pilot-{digest[:12]}", "classifier": chosen, "threshold": selected["threshold"],
        "artifact_sha256": digest, "feature_schema": SCHEMA, "config": cfg, "movenet": MODEL,
        "keypoint_runtime": metadata(training[0], cfg),
        "split_sha256": sha(SPLIT), "training_snapshot": training_snapshot(clips),
        "trained_utc": datetime.now(timezone.utc).isoformat(),
        "train_windows": {"Fall": int(y.sum()), "No_Fall": int(len(y) - y.sum())},
        "train_videos": sum(sum(v.values()) > 0 for v in counts.values()),
        "train_people": len({c["subject_id"] for c in training if sum(counts[c["video_id"]].values())}),
        "train_events": sum(v["Fall"] > 0 for v in counts.values()), "validation_target_false_per_hour": FALSE_ALARMS_TARGET,
        "validation_alarm_budget_count": allowed, "validation_detected": selected["detected"],
    }
    write_json(MODEL_INFO, run)
    write_json(safe("reports/validation.json"), {
        "model_id": run["model_id"], "selected": selected, "best": best,
        "candidates": [{k: v for k, v in r.items() if k not in {"mistakes", "per_video"}} for r in results],
    })
    fields = ["model_id", "split", "video_id", "relative_path", "subject_id", "original_label", "label",
              "sha256", "onset_s", "impact_s", "negative", "train_fall_windows", "train_no_fall_windows"]
    mapping = []
    for clip in clips:
        count = counts.get(clip["video_id"], {})
        mapping.append({**{field: clip[field] for field in fields[1:-2]},
                        "model_id": run["model_id"], "train_fall_windows": count.get("Fall", ""),
                        "train_no_fall_windows": count.get("No_Fall", "")})
    write_rows(DEMO, mapping, fields)
    print(f"{chosen}, threshold {run['threshold']}, {run['train_videos']} clip, "
          f"{run['train_people']} người, {run['train_events']} ca Fall thực sự có cửa sổ train.")


def load_model():
    info = read_json(MODEL_INFO)
    if info is None or not ARTIFACT.exists():
        return None, None
    if (info["movenet"]["sha256"] != MODEL["sha256"] or info["feature_schema"] != SCHEMA
            or sha(safe("models/classifier.joblib")) != info["artifact_sha256"]):
        raise ValueError("Model đã lưu không khớp trọng số hoặc schema")
    return info, joblib.load(safe("models/classifier.joblib"))


def evaluate():
    clips = load_split()
    info, model = load_model()
    if info is None:
        raise ValueError("Chưa có model. Chạy Train sau khi chốt validation.")
    if sha(SPLIT) != info["split_sha256"] or training_snapshot(clips) != info["training_snapshot"]:
        raise ValueError("Split hoặc nhãn train/validation đã đổi sau khi chốt model")
    test = [c for c in clips if c["split"] == "test"]
    cfg = info["config"]
    cache = {c["video_id"]: get_keypoints(c, cfg) for c in test}
    result = evaluation(test, cache, cfg, model, info["threshold"])
    write_json(safe("reports/test.json"), {"model_id": info["model_id"], **result})
    write_rows(safe("reports/test_mistakes.csv"), result["mistakes"],
               ["video_id", "relative_path", "issue", "timestamp_s"])
    validation = read_json(safe("reports/validation.json"))
    if validation["model_id"] != info["model_id"]:
        raise ValueError("Báo cáo validation không khớp model")
    lines = [
        "# Đánh giá pilot theo sự kiện", "",
        f"Model đã chốt: **{info['classifier']}** · ngưỡng {info['threshold']} · `{info['model_id']}`.",
        f"Train thực tế: {info['train_videos']} clip, {info['train_people']} người, {info['train_events']} ca Fall.",
        f"Cửa sổ train: {info['train_windows']['Fall']} Fall, {info['train_windows']['No_Fall']} No_Fall.",
        "", f"Validation có {validation['selected']['people']} người. Ngân sách so sánh là "
        f"{info.get('validation_alarm_budget_count', 0)} lần báo giả trong thời lượng ADL đã xác nhận.",
        "", "| Validation | Ngưỡng | Bắt được | Recall | Báo giả | Phút ADL | Báo giả/giờ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in validation["best"]:
        lines.append(f"| {row['classifier']} | {row['threshold']} | {row['detected']}/{row['events']} | "
                     f"{row['recall']:.1%} | {row['false_alarms']} | {row['negative_s']/60:.2f} | "
                     f"{row['false_per_hour']:.2f} |")
    lines.extend(["", f"Test độc lập: {result['videos']} clip từ {result['people']} người.",
                  f"- Bắt được {result['detected']}/{result['events']} ca ({result['recall']:.1%}), "
                  f"bỏ sót {result['missed']}.",
                  f"- {result['false_alarms']} báo giả trong {result['negative_s']/60:.2f} phút ADL "
                  f"({result['false_per_hour']:.2f}/giờ).",
                  f"- Độ trễ từng ca (giây, cảnh báo trừ lúc chạm): {[round(x, 3) for x in result['latency_s']]}.",
                  f"- Không nhìn rõ {result['unclear_s']:.2f} giây, chưa thấy người {result['no_person_s']:.2f} "
                  f"giây trên {result['video_s']:.2f} giây test. Cảnh báo khác: {result['other_unmatched']}.",
                  "", "Ghép cảnh báo đầu tiên từ 0,25 giây trước lúc mất thăng bằng đến 1,5 giây sau "
                  "lúc chạm. Độ trễ âm nghĩa là báo trước khi chạm.",
                  "Thời lượng ADL pilot ngắn. Số báo giả/giờ là phép quy đổi từ số quan sát được.",
                  "Xem `test_mistakes.csv` để mở lại clip và timestamp sai.",
                  "", "## Clip mở khi chấm", "",
                  "| Tập | Nhãn xác nhận | Clip gốc | Mốc chạm (giây) |",
                  "|---|---|---|---:|"])
    matched = {item["video_id"] for item in result["per_video"] if item["matched_s"] is not None}
    references = [row for row in rows(DEMO) if row["model_id"] == info["model_id"]]
    for part in ("train", "test"):
        for label in ("Fall", "No_Fall"):
            items = [row for row in references if row["split"] == part and row["label"] == label]
            if part == "train":
                field = "train_fall_windows" if label == "Fall" else "train_no_fall_windows"
                items = sorted((row for row in items if int(row[field]) > 0), key=lambda row: -int(row[field]))
            elif label == "Fall":
                items.sort(key=lambda row: row["video_id"] not in matched)
            if items:
                item = items[0]
                lines.append(f"| {part} | {label} | [{item['video_id']}](../{item['relative_path']}) | "
                             f"{item['impact_s'] or '—'} |")
    lines.extend(["", "Các ca trong báo cáo là mô phỏng. Nhiều clip dùng cùng bối cảnh dù người được chia độc lập."])
    if safe("reports/pilot_01/model_evaluation.md").is_file():
        lines.append("Pilot trước dùng tập test khác và được lưu tại [pilot_01](pilot_01/model_evaluation.md).")
    lines.append("")
    atomic(safe("reports/model_evaluation.md"), "\n".join(lines).encode())
    print("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["split", "train", "evaluate"])
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--fresh-test", action="store_true")
    args = parser.parse_args()
    action = {"split": lambda: split(args.rebuild, args.fresh_test), "train": train, "evaluate": evaluate}
    try:
        action[args.command]()
    except ValueError as error:
        raise SystemExit(str(error)) from error
