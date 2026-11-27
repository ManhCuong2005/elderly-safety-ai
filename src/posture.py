from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .pose import CONFIG, MODEL, TORSO
from .storage import read_json, safe, write_json

ARTIFACT = "models/posture.json"
LABELS = {"Sitting": "Ngồi", "Standing": "Đứng"}
CONFIDENCE = 0.3
MIN_POSTURE_SCORE = 0.75
TRAIN_PEOPLE = {"Person02", "Person03", "Person05", "Person06", "Person21", "Person22",
                "Person24", "Person29", "Person35", "Person36"}
TEST_PEOPLE = {"Person27", "Person30", "Person31", "Person32"}


def posture_features(obs):
    points = obs.points
    good = points[:, 2] >= CONFIDENCE
    if not good[TORSO].all():
        return None
    xy = points[:, :2].astype(float)
    trunk = xy[[11, 12]].mean(axis=0) - xy[[5, 6]].mean(axis=0)
    scale = np.linalg.norm(trunk)
    # shortcut: sitting and standing labels only, train a lying class once labeled clips are available.
    if not np.isfinite(scale) or scale < 0.018 * max(obs.width, obs.height) or trunk[1] / scale < 0.65:
        return None
    legs = []
    for hip, knee, ankle in ((11, 13, 15), (12, 14, 16)):
        if not good[[hip, knee, ankle]].all():
            continue
        thigh, shin = (xy[knee] - xy[hip]) / scale, (xy[ankle] - xy[knee]) / scale
        lengths = np.linalg.norm([thigh, shin], axis=1)
        if not np.isfinite(lengths).all() or min(lengths) < 0.07:
            continue
        legs.append([thigh[1], abs(thigh[0]), shin[1], np.dot(thigh, trunk / scale) / lengths[0],
                     np.dot(thigh, shin) / np.prod(lengths)])
    return np.mean(legs, axis=0) if legs else None


def load_posture():
    try:
        data = read_json(safe(ARTIFACT))
        if data is None or data["movenet_sha256"] != MODEL["sha256"] or data["schema"] != 1:
            return None
        weights = np.asarray(data["weights"], dtype=float)
        bias = float(data["intercept"])
        classes = data["classes"]
        if (weights.shape != (5,) or not np.isfinite(weights).all() or not np.isfinite(bias)
                or sorted(classes) != sorted(LABELS)):
            return None
    except (OSError, TypeError, KeyError, ValueError):
        return None

    def classify(obs):
        features = posture_features(obs)
        if features is None:
            return None
        score = float(weights @ features + bias)
        if abs(score) < np.log(MIN_POSTURE_SCORE / (1 - MIN_POSTURE_SCORE)):
            return None
        return LABELS[classes[int(score > 0)]]

    return classify


def extended_posture(obs, base_classifier=None, confidence=CONFIDENCE):
    """Return Standing/Sitting from base classifier, or Lying / Slumped from trunk & head geometry."""
    from .inference import Body
    body = Body.from_pose(obs, confidence)
    if body is None:
        return None
    if body.lying:
        return "Nằm"
    if body.slumped:
        return "Gục người / trượt tường"
    if base_classifier is not None:
        return base_classifier(obs)
    return None


def train():
    from .keypoints import get_keypoints
    from .pose import Pose
    from .review import VIDEOS
    from .storage import rows
    from .train import connected_people, load_split, related_videos

    clips = [row for row in rows(VIDEOS) if row["original_label"] in LABELS
             and row["subject_id"] in TRAIN_PEOPLE | TEST_PEOPLE and row["status"] != "exclude"]
    groups = connected_people([*clips, *related_videos()])
    main_splits = {groups[row["subject_id"]]: row["split"] for row in load_split()}
    if (not all(main_splits[groups[p]] == "train" for p in TRAIN_PEOPLE)
            or {groups[p] for p in TRAIN_PEOPLE} & {groups[p] for p in TEST_PEOPLE}):
        raise ValueError("Dữ liệu tư thế train phải thuộc người train của mô hình té ngã.")
    pose = Pose()
    cfg = {**CONFIG, "sample_hz": 2}

    def samples(clip):
        observations = [obs for obs in get_keypoints(clip, cfg, pose) if 1 <= obs.t <= 25]
        usable = [(obs, x) for obs in observations if (x := posture_features(obs)) is not None]
        print(f"{clip['video_id']}: {len(usable)}/{len(observations)} frame", flush=True)
        return clip, observations, usable

    with ThreadPoolExecutor(max_workers=3) as pool:
        data = list(pool.map(samples, clips))
    training = [item for item in data if item[0]["subject_id"] in TRAIN_PEOPLE and item[2]]
    x = [features for _, _, usable in training for _, features in usable]
    y = [clip["original_label"] for clip, _, usable in training for _ in usable]
    model = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", random_state=CONFIG["seed"]))
    model.fit(x, y)
    scaler, estimator = model.steps[0][1], model.steps[1][1]
    weights = estimator.coef_[0] / scaler.scale_
    bias = estimator.intercept_[0] - weights @ scaler.mean_
    if not np.allclose(estimator.decision_function(scaler.transform(x)), np.asarray(x) @ weights + bias):
        raise ValueError("Trọng số đã xuất không khớp model tư thế.")
    write_json(safe(ARTIFACT), {"schema": 1, "movenet_sha256": MODEL["sha256"],
                               "weights": weights.tolist(), "intercept": float(bias),
                               "classes": estimator.classes_.tolist()})
    classify = load_posture()
    held_out = [item for item in data if item[0]["subject_id"] in TEST_PEOPLE]
    results = []
    for clip, observations, usable in held_out:
        predicted = [classify(obs) for obs, _ in usable]
        results.append({"video_id": clip["video_id"], "subject_id": clip["subject_id"],
                        "sha256": clip["sha256"], "frames": len(observations),
                        "shown": sum(label is not None for label in predicted),
                        "correct": predicted.count(LABELS[clip["original_label"]])})
    write_json(safe("reports/posture.json"), {
        "classes": list(LABELS.values()), "sample_hz": 2, "reviewed_range_s": [1, 25],
        "train_people": sorted({clip["subject_id"] for clip, _, _ in training}),
        "train_clips": [{"video_id": clip["video_id"], "sha256": clip["sha256"], "frames": len(usable)}
                        for clip, _, usable in training],
        "test_clips": results,
    })
    print(f"Train {len(training)} clips / {len(x)} frames. Holdout: "
          f"{sum(row['correct'] for row in results)}/{sum(row['shown'] for row in results)} nhãn đúng "
          f"khi có nhãn trên {sum(row['frames'] for row in results)} frame.")


if __name__ == "__main__":
    train()
