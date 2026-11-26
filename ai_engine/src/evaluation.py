"""Video-level metrics; missing event onset means latency is null, not estimated."""
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from .engine import Engine


def metrics(rows):
    tp = sum(r['label'] == 'FALL' and r['detected'] for r in rows)
    fp = sum(r['label'] == 'NON_FALL' and r['detected'] for r in rows)
    fn = sum(r['label'] == 'FALL' and not r['detected'] for r in rows)
    tn = sum(r['label'] == 'NON_FALL' and not r['detected'] for r in rows)
    precision = tp/(tp+fp) if tp+fp else 0.0
    recall = tp/(tp+fn) if tp+fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "confusion_matrix": [[tn, fp], [fn, tp]],
            "matrix_order": "rows actual NON_FALL,FALL; columns predicted NON_FALL,FALL",
            "precision": precision, "recall": recall,
            "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.0,
            "false_positive_rate": fp/(fp+tn) if fp+tn else None,
            "false_positive_rate_definition": "FP / (FP + TN), video level"}


def replay(record, cache, config):
    engine = Engine(config)
    events = []
    total = valid = 0
    missing = []
    coverage=Counter()
    for line in cache.read_text().splitlines():
        row = json.loads(line)
        if record.get('input_layout')=='ur-rgbd' and row['width']/row['height']>2:
            raise ValueError('Legacy RGB/depth composite cache: extract again into a new cache tag before evaluating RGB accuracy.')
        result = engine.process(
            row['t'], row['landmarks'], row['width'], row['height'],
            row['reason'], world_landmarks=row.get('world_landmarks'),
        )
        total += 1
        coverage[result.get('pose_coverage','NONE')]+=1
        if result['features']:
            valid += 1
        else:
            missing.append(total)
        events.extend(result['events'])
    alerts = [e for e in events if e['kind'] in ('SUSPECTED_FALL','POSSIBLE_FALL')]
    verified = [e for e in events if e['kind']=='POSSIBLE_FALL']
    onset = record.get('fall_onset_s')
    latency = alerts[0]['timestamp']-onset if alerts and onset is not None else None
    return {"video_id": record['video_id'], "label": record['label'], "split": record['split'],
            "detected": bool(alerts), "verified_detected":bool(verified), "frame_count": total, "reliable_pose_frames": valid,
            "missing_landmark_frames": missing, "pose_coverage_counts":dict(coverage),
            "detection_latency_s": latency, "events": events}


def report(records, directory, config, split):
    rows = [replay(r, directory/f"{r['video_id']}.landmarks.jsonl", config)
            for r in records if r['split'] == split]
    if not rows:
        raise ValueError(f"No clips in split: {split}")
    thresholds = asdict(config)
    return {"algorithm_version":"1.4", "split": split, "experimental_small_sample": True, "subject_independence_verified": False,
            "thresholds_sha256": hashlib.sha256(json.dumps(thresholds, sort_keys=True).encode()).hexdigest(),
            "positive_definition":"At least one SUSPECTED_FALL warning (or verified POSSIBLE_FALL) per video; not a confirmed physical fall",
            "thresholds": thresholds, "metrics": metrics(rows),
            "verified_metrics":metrics([{**r,'detected':r['verified_detected']} for r in rows]), "videos": rows}
