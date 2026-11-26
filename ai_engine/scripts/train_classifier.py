"""Phase 2 & 5: Train, compare, validate, and benchmark V2 ML Fall/Activity Classifier.

Strictly leak-free video-grouped protocol:
- Train/CV partition: fall-01..20 + adl-01..20 (40 videos)
  -> StratifiedGroupKFold(n_splits=5) grouped by video_id.
  -> Compares Random Forest, Extra Trees, RBF SVM, MLP Neural Network, HistGradientBoosting.
  -> Selects best model & threshold on train_cv out-of-fold video-level F1 ONLY.
- Held-out Independent Test partition: fall-21..30 + adl-21..30 (20 videos, incl. test_v1_4)
  -> Never touched during training or threshold selection.
- Full 60-video 5-fold GroupKFold out-of-fold video evaluation for full benchmark reporting.
- Generates thesis figures in docs/figures/ and JSON report in docs/evaluation-v2-ml-report.json.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

ENGINE_DIR = Path(__file__).resolve().parents[1]
ROOT = ENGINE_DIR.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from src.config import Config
from src.engine import Engine
from src.evaluation import metrics as video_metrics
from src.ml.classifier import FallActivityClassifier
from src.ml.features import FEATURE_NAMES

DATA = ENGINE_DIR / "datasets"
META = DATA / "metadata"
MODEL_OUT = ENGINE_DIR / "trained_models" / "fall_activity_model.joblib"
CONFIG_V2 = ENGINE_DIR / "configs" / "v2_ml.json"
FIG_DIR = ROOT / "docs" / "figures"
REPORT_OUT = ROOT / "docs" / "evaluation-v2-ml-report.json"


def make_models():
    return {
        "RandomForest": RandomForestClassifier(
            n_estimators=300, max_depth=12, min_samples_leaf=3,
            class_weight="balanced_subsample", random_state=42, n_jobs=-1,
        ),
        "ExtraTrees": ExtraTreesClassifier(
            n_estimators=300, max_depth=14, min_samples_leaf=2,
            class_weight="balanced_subsample", random_state=42, n_jobs=-1,
        ),
        "HistGradientBoosting": HistGradientBoostingClassifier(
            max_iter=200, max_depth=6, learning_rate=0.06,
            min_samples_leaf=12, class_weight="balanced", random_state=42,
        ),
        "SVM_RBF": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", CalibratedClassifierCV(
                SVC(kernel="rbf", C=2.5, gamma="scale", class_weight="balanced", random_state=42),
                cv=3,
            )),
        ]),
        "MLP_NeuralNet": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", MLPClassifier(hidden_layer_sizes=(64, 32), alpha=0.02, max_iter=300,
                                  early_stopping=True, random_state=42)),
        ]),
    }


def _video_preds_from_probs(df_eval, probs, threshold, min_consecutive=2):
    """Simulate consecutive-frame trigger per video from out-of-fold frame probabilities."""
    rows = []
    for vid, grp in df_eval.groupby("video_id", sort=False):
        label = grp["video_label"].iloc[0]
        p = probs[grp.index]
        postures = grp["posture_rule"].values
        hits = 0
        detected = False
        first_t = None
        onset = grp["fall_onset_s"].iloc[0]
        for idx_i, (prob, post, ts) in enumerate(zip(p, postures, grp["timestamp_s"].values)):
            if prob >= threshold and post not in ("STANDING", "WALKING"):
                hits += 1
            else:
                hits = 0
            if hits >= min_consecutive:
                detected = True
                first_t = float(ts)
                break
        latency = None
        if detected and pd.notna(onset) and str(onset) != "":
            latency = round(first_t - float(onset), 3)
        rows.append({
            "video_id": vid, "label": label, "detected": detected,
            "first_alert_s": first_t, "latency_s": latency,
            "max_prob": round(float(np.max(p)), 4),
        })
    return rows, video_metrics(rows)


def replay_engine_videos(records, cache_dir, config, onsets, classifier=None):
    """Run full end-to-end Engine (with real FSM) on cached RGB landmarks."""
    rows = []
    infer_times_ms = []
    for rec in records:
        vid = rec["video_id"]
        cache = cache_dir / f"{vid}.landmarks.jsonl"
        engine = Engine(config, classifier=classifier)
        events = []
        max_score = 0.0
        lines = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines()]
        for row in lines:
            t0 = time.perf_counter()
            res = engine.process(
                row["t"], row["landmarks"], row["width"], row["height"],
                row["reason"], world_landmarks=row.get("world_landmarks"),
            )
            infer_times_ms.append((time.perf_counter() - t0) * 1000.0)
            max_score = max(max_score, float(res.get("fall_score", 0.0)))
            events.extend(res["events"])
        alerts = [e for e in events if e["kind"] in ("SUSPECTED_FALL", "POSSIBLE_FALL")]
        verified = [e for e in events if e["kind"] == "POSSIBLE_FALL"]
        onset = onsets.get(vid)
        latency = round(alerts[0]["timestamp"] - onset, 3) if (alerts and onset is not None) else None
        rows.append({
            "video_id": vid,
            "label": rec["label"],
            "split": rec["split"],
            "detected": bool(alerts),
            "verified_detected": bool(verified),
            "first_alert_s": round(alerts[0]["timestamp"], 3) if alerts else None,
            "fall_onset_s": onset,
            "detection_latency_s": latency,
            "max_fall_score": round(max_score, 4),
            "activity_summary": engine.activity.summary(),
        })
    m_alert = video_metrics(rows)
    m_verified = video_metrics([{**r, "detected": r["verified_detected"]} for r in rows])
    latencies = [r["detection_latency_s"] for r in rows if r["label"] == "FALL" and r["detection_latency_s"] is not None]
    return {
        "metrics": m_alert,
        "verified_metrics": m_verified,
        "mean_latency_s": round(float(np.mean(latencies)), 3) if latencies else None,
        "median_latency_s": round(float(np.median(latencies)), 3) if latencies else None,
        "engine_mean_ms_per_frame": round(float(np.mean(infer_times_ms)), 3) if infer_times_ms else None,
        "videos": rows,
    }


def save_figures(cv_results, best_name, feature_importances, v1_holdout, v2_holdout, all60_oof, y_true_cv, oof_probs_map):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3})

    # 1. Model Comparison Bar Chart (V1 Rule-based vs ML models on CV & Holdout)
    names = ["V1 Rule-Based\n(Holdout)"] + list(cv_results.keys())
    precisions = [v1_holdout["metrics"]["precision"]] + [cv_results[k]["video_cv"]["precision"] for k in cv_results]
    recalls = [v1_holdout["metrics"]["recall"]] + [cv_results[k]["video_cv"]["recall"] for k in cv_results]
    f1s = [v1_holdout["metrics"]["f1"]] + [cv_results[k]["video_cv"]["f1"] for k in cv_results]

    x = np.arange(len(names))
    w = 0.26
    fig, ax = plt.subplots(figsize=(11, 5.2))
    b1 = ax.bar(x - w, precisions, w, label="Precision", color="#2a9d8f")
    b2 = ax.bar(x, recalls, w, label="Recall", color="#e76f51")
    b3 = ax.bar(x + w, f1s, w, label="F1-Score", color="#264653")
    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:.2f}", (bar.get_x() + bar.get_width() / 2, h),
                        ha="center", va="bottom", fontsize=8, xytext=(0, 2), textcoords="offset points")
    ax.set_ylabel("Score (0.0 – 1.0)")
    ax.set_title("Video-Level Fall Detection Comparison: V1 Rule-Based vs V2 ML Classifiers (5-Fold GroupKFold CV)")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.15)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "model_comparison.png", dpi=180)
    plt.close(fig)

    # 2. Confusion Matrices: V1 Holdout vs V2 Holdout vs V2 All-60 OOF
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))
    panels = [
        ("V1 Rule-Based\n(Holdout 20 videos)", v1_holdout["metrics"]["confusion_matrix"]),
        (f"V2 {best_name} + FSM\n(Holdout 20 videos)", v2_holdout["metrics"]["confusion_matrix"]),
        (f"V2 {best_name} (OOF CV)\n(All 60 videos)", all60_oof["metrics"]["confusion_matrix"]),
    ]
    for ax, (title, cm) in zip(axes, panels):
        cm_arr = np.array(cm)
        im = ax.imshow(cm_arr, cmap="Teal" if "Teal" in plt.colormaps() else "Blues")
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["Pred NON_FALL", "Pred FALL"])
        ax.set_yticklabels(["Actual NON_FALL", "Actual FALL"])
        ax.grid(False)
        thresh = cm_arr.max() / 2.0 if cm_arr.max() > 0 else 0.5
        for i in range(2):
            for j in range(2):
                ax.text(j, i, str(cm_arr[i, j]), ha="center", va="center",
                        color="white" if cm_arr[i, j] > thresh else "black", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "confusion_matrix_v2.png", dpi=180)
    plt.close(fig)

    # 3. Feature Importance (Top 15 Kinematic Features)
    top = sorted(feature_importances.items(), key=lambda kv: kv[1], reverse=True)[:15][::-1]
    fig, ax = plt.subplots(figsize=(9.5, 5.8))
    labels = [k for k, _ in top]
    vals = [v for _, v in top]
    ax.barh(labels, vals, color="#007f86")
    ax.set_xlabel("Importance Score")
    ax.set_title(f"Top 15 Spatio-Temporal Kinematic Features ({best_name})")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "feature_importance.png", dpi=180)
    plt.close(fig)

    # 4. ROC & Precision-Recall Curves (Frame-level OOF on Train/CV)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.8))
    for name, probs in oof_probs_map.items():
        fpr, tpr, _ = roc_curve(y_true_cv, probs)
        roc_auc = roc_auc_score(y_true_cv, probs)
        ax1.plot(fpr, tpr, lw=2, label=f"{name} (AUC={roc_auc:.3f})")
        prec, rec, _ = precision_recall_curve(y_true_cv, probs)
        ap = average_precision_score(y_true_cv, probs)
        ax2.plot(rec, prec, lw=2, label=f"{name} (AP={ap:.3f})")
    ax1.plot([0, 1], [0, 1], "k--", alpha=0.4)
    ax1.set_xlabel("False Positive Rate")
    ax1.set_ylabel("True Positive Rate")
    ax1.set_title("Frame-Level ROC Curve (5-Fold Video-Grouped CV)")
    ax1.legend(loc="lower right", fontsize=8)
    ax2.set_xlabel("Recall")
    ax2.set_ylabel("Precision")
    ax2.set_title("Frame-Level Precision-Recall Curve (5-Fold CV)")
    ax2.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "roc_pr_curves.png", dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache-tag", default="rgb_v2")
    args = p.parse_args()

    cache_dir = DATA / "processed" / args.cache_tag
    csv_path = cache_dir / "dataset_features.csv"
    onsets = json.loads((cache_dir / "fall_onsets.json").read_text(encoding="utf-8"))
    records = json.loads((META / "manifest.json").read_text(encoding="utf-8"))
    df_all = pd.read_csv(csv_path)

    # Training frames exclude static late post-fall lying (target_fall == -1)
    df_train_all = df_all[(df_all["dataset_partition"] == "train_cv") & (df_all["target_fall"] >= 0)].reset_index(drop=True)
    df_train_full = df_all[df_all["dataset_partition"] == "train_cv"].reset_index(drop=True)
    X_train = df_train_all[FEATURE_NAMES].values.astype(np.float32)
    y_train = df_train_all["target_fall"].values.astype(int)
    groups_train = df_train_all["video_id"].values

    print(f"Train/CV frames: {len(df_train_all)} (pos={int(y_train.sum())}, neg={int((y_train == 0).sum())}) across {df_train_all['video_id'].nunique()} videos", flush=True)

    sgkf = StratifiedGroupKFold(n_splits=5)
    models = make_models()
    cv_results = {}
    oof_probs_map = {}

    for name, model in models.items():
        oof_train = np.zeros(len(df_train_all), dtype=float)
        oof_full = np.zeros(len(df_train_full), dtype=float)
        for fold, (tr_idx, va_idx) in enumerate(sgkf.split(X_train, y_train, groups_train)):
            val_vids = set(groups_train[va_idx])
            m_clone = make_models()[name]
            m_clone.fit(X_train[tr_idx], y_train[tr_idx])
            oof_train[va_idx] = m_clone.predict_proba(X_train[va_idx])[:, 1]
            mask_full = df_train_full["video_id"].isin(val_vids).values
            oof_full[mask_full] = m_clone.predict_proba(df_train_full.loc[mask_full, FEATURE_NAMES].values.astype(np.float32))[:, 1]

        oof_probs_map[name] = oof_train
        roc_auc = float(roc_auc_score(y_train, oof_train))
        pr_auc = float(average_precision_score(y_train, oof_train))

        # Tune video-level threshold and min_consecutive strictly on train_cv OOF predictions
        best_cfg = None
        for min_consec in (2, 3, 4):
            for th in np.linspace(0.35, 0.80, 19):
                _, vm = _video_preds_from_probs(df_train_full, oof_full, float(th), min_consecutive=min_consec)
                key = (vm["f1"], -vm["fp"], vm["recall"], -abs(th - 0.55))
                if best_cfg is None or key > best_cfg[0]:
                    best_cfg = (key, round(float(th), 3), min_consec, vm)

        _, best_th, best_consec, best_vm = best_cfg
        frame_pred = (oof_train >= best_th).astype(int)
        cv_results[name] = {
            "frame_cv": {
                "roc_auc": round(roc_auc, 4),
                "pr_auc": round(pr_auc, 4),
                "precision": round(float(precision_score(y_train, frame_pred, zero_division=0)), 4),
                "recall": round(float(recall_score(y_train, frame_pred, zero_division=0)), 4),
                "f1": round(float(f1_score(y_train, frame_pred, zero_division=0)), 4),
            },
            "selected_threshold": best_th,
            "selected_min_consecutive": best_consec,
            "video_cv": best_vm,
        }
        print(
            f"[{name:20s}] Frame AUC={roc_auc:.3f} AP={pr_auc:.3f} | "
            f"Video CV (40v) F1={best_vm['f1']:.3f} P={best_vm['precision']:.3f} R={best_vm['recall']:.3f} "
            f"(TP={best_vm['tp']} FP={best_vm['fp']} FN={best_vm['fn']} TN={best_vm['tn']}) th={best_th} c={best_consec}",
            flush=True,
        )

    # Select winning model strictly by train_cv Video F1, then Frame PR-AUC, then fewer FP
    best_name = max(
        cv_results.keys(),
        key=lambda n: (
            cv_results[n]["video_cv"]["f1"],
            -cv_results[n]["video_cv"]["fp"],
            cv_results[n]["frame_cv"]["pr_auc"],
            cv_results[n]["frame_cv"]["roc_auc"],
        ),
    )
    best_th = cv_results[best_name]["selected_threshold"]
    best_consec = cv_results[best_name]["selected_min_consecutive"]
    print(f"\n>>> Selected Best Model on Train/CV: {best_name} (threshold={best_th}, min_consecutive={best_consec})", flush=True)

    # Fit winning model on all 40 train_cv videos and serialize bundle
    final_model = make_models()[best_name]
    final_model.fit(X_train, y_train)

    # Compute feature importances (native for tree models, permutation importance otherwise)
    if hasattr(final_model, "feature_importances_"):
        importances = {k: round(float(v), 5) for k, v in zip(FEATURE_NAMES, final_model.feature_importances_)}
    else:
        perm = permutation_importance(final_model, X_train, y_train, n_repeats=5, random_state=42, n_jobs=-1)
        importances = {k: round(float(max(0.0, v)), 5) for k, v in zip(FEATURE_NAMES, perm.importances_mean)}

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": final_model,
        "model_name": best_name,
        "feature_names": FEATURE_NAMES,
        "threshold": best_th,
        "min_consecutive": best_consec,
        "classes": list(getattr(final_model, "classes_", [0, 1])),
        "metadata": {
            "dataset": "UR Fall Detection Dataset (RGB-corrected, cam0)",
            "train_videos": 40,
            "train_frames": int(len(df_train_all)),
            "train_cv_video_f1": cv_results[best_name]["video_cv"]["f1"],
            "train_cv_frame_roc_auc": cv_results[best_name]["frame_cv"]["roc_auc"],
        },
    }
    joblib.dump(bundle, MODEL_OUT, compress=3)
    print(f"Saved model bundle -> {MODEL_OUT} ({MODEL_OUT.stat().st_size / 1024:.1f} KB)", flush=True)

    # Save frozen V2 config
    v2_config = Config(
        visibility=0.5,
        lying_lean=55.0,
        grace_period_s=0.45,
        auto_reacquire=True,
        enable_bending=True,
        landmark_smooth_tau_s=0.06,
        ml_model_path="trained_models/fall_activity_model.joblib",
        ml_fall_threshold=best_th,
        ml_min_consecutive=best_consec,
        stumble_risk_threshold=round(max(0.25, best_th * 0.65), 2),
    )
    CONFIG_V2.write_text(json.dumps(asdict(v2_config), indent=2), encoding="utf-8")
    print(f"Saved V2 config -> {CONFIG_V2}", flush=True)

    # === INDEPENDENT HELD-OUT EVALUATION (20 videos: 21..30) ===
    v1_config = Config.load(ENGINE_DIR / "configs/calibrated-v1_4.json")
    holdout_records = [r for r in records if int(r["video_id"].split("-")[1]) >= 21]
    v1_4_records = [r for r in records if int(r["video_id"].split("-")[1]) >= 26]

    clf = FallActivityClassifier(MODEL_OUT)
    v1_holdout = replay_engine_videos(holdout_records, cache_dir, v1_config, onsets, classifier=None)
    v2_holdout = replay_engine_videos(holdout_records, cache_dir, v2_config, onsets, classifier=clf)
    v1_test14 = replay_engine_videos(v1_4_records, cache_dir, v1_config, onsets, classifier=None)
    v2_test14 = replay_engine_videos(v1_4_records, cache_dir, v2_config, onsets, classifier=clf)

    # === ALL-60 5-FOLD VIDEO-GROUPED OUT-OF-FOLD BENCHMARK (zero leakage across all 60 videos) ===
    df_all_trainable = df_all[df_all["target_fall"] >= 0].reset_index(drop=True)
    X_60 = df_all_trainable[FEATURE_NAMES].values.astype(np.float32)
    y_60 = df_all_trainable["target_fall"].values.astype(int)
    g_60 = df_all_trainable["video_id"].values
    oof_60_rows = []
    for fold, (tr_i, va_i) in enumerate(sgkf.split(X_60, y_60, g_60)):
        val_vids = set(g_60[va_i])
        fold_model = make_models()[best_name]
        fold_model.fit(X_60[tr_i], y_60[tr_i])

        class _FoldClf:
            def __init__(self, m, th, mname):
                self.m, self.th, self.mname = m, th, mname
            def predict(self, f_obj, m_obj):
                from src.ml.features import build_feature_vector
                v = build_feature_vector(f_obj, m_obj)
                if v is None:
                    return None
                p = float(self.m.predict_proba(v.reshape(1, -1))[0, 1])
                return {"fall_prob": round(p, 4), "is_fall_frame": p >= self.th, "model_name": self.mname, "threshold": self.th}

        val_recs = [r for r in records if r["video_id"] in val_vids]
        fold_res = replay_engine_videos(val_recs, cache_dir, v2_config, onsets, classifier=_FoldClf(fold_model, best_th, best_name))
        oof_60_rows.extend(fold_res["videos"])

    all60_oof = {
        "metrics": video_metrics(oof_60_rows),
        "verified_metrics": video_metrics([{**r, "detected": r["verified_detected"]} for r in oof_60_rows]),
        "videos": oof_60_rows,
    }
    v1_all60 = replay_engine_videos(records, cache_dir, v1_config, onsets, classifier=None)

    # Aggregate pose + engine throughput
    perf_files = list(cache_dir.glob("*.performance.json"))
    perfs = [json.loads(p.read_text(encoding="utf-8")) for p in perf_files]
    pose_fps_mean = round(float(np.mean([p["throughput_fps"] for p in perfs])), 2) if perfs else None
    pose_ms_mean = round(float(np.mean([p["avg_ms_per_frame"] for p in perfs])), 2) if perfs else None

    save_figures(cv_results, best_name, importances, v1_holdout, v2_holdout, all60_oof, y_train, oof_probs_map)

    report = {
        "algorithm_version": "2.0-ml",
        "selected_model": best_name,
        "selected_threshold": best_th,
        "selected_min_consecutive": best_consec,
        "model_bundle_path": str(MODEL_OUT.relative_to(ROOT)),
        "model_bundle_kb": round(MODEL_OUT.stat().st_size / 1024, 1),
        "feature_count": len(FEATURE_NAMES),
        "feature_names": FEATURE_NAMES,
        "feature_importances": importances,
        "train_cv_comparison_40_videos": cv_results,
        "holdout_20_videos_21_to_30": {
            "v1_rule_based": {k: v for k, v in v1_holdout.items() if k != "videos"},
            "v2_ml_engine": {k: v for k, v in v2_holdout.items() if k != "videos"},
            "v2_videos": v2_holdout["videos"],
        },
        "test_v1_4_10_videos_26_to_30": {
            "v1_rule_based": {k: v for k, v in v1_test14.items() if k != "videos"},
            "v2_ml_engine": {k: v for k, v in v2_test14.items() if k != "videos"},
        },
        "all_60_videos_benchmark": {
            "v1_rule_based": {k: v for k, v in v1_all60.items() if k != "videos"},
            "v2_ml_5fold_oof": {k: v for k, v in all60_oof.items() if k != "videos"},
        },
        "edge_performance": {
            "mediapipe_pose_mean_fps": pose_fps_mean,
            "mediapipe_pose_mean_ms": pose_ms_mean,
            "v2_ml_engine_mean_ms": v2_holdout["engine_mean_ms_per_frame"],
            "combined_estimated_fps": round(1000.0 / (pose_ms_mean + v2_holdout["engine_mean_ms_per_frame"]), 2)
            if (pose_ms_mean and v2_holdout["engine_mean_ms_per_frame"]) else None,
        },
    }
    REPORT_OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n================ FINAL BENCHMARK SUMMARY ================")
    print("Holdout 20 videos (21..30) — V1 Rule-Based:", json.dumps(v1_holdout["metrics"]))
    print("Holdout 20 videos (21..30) — V2 ML Engine :", json.dumps(v2_holdout["metrics"]))
    print("Holdout 20 videos (21..30) — V2 Verified  :", json.dumps(v2_holdout["verified_metrics"]))
    print("Test v1_4 10 videos (26..30) — V1         :", json.dumps(v1_test14["metrics"]))
    print("Test v1_4 10 videos (26..30) — V2 ML      :", json.dumps(v2_test14["metrics"]))
    print("All 60 videos — V1 Rule-Based             :", json.dumps(v1_all60["metrics"]))
    print("All 60 videos — V2 ML 5-Fold OOF          :", json.dumps(all60_oof["metrics"]))
    print("V2 Mean Detection Latency (Holdout)       :", v2_holdout["mean_latency_s"], "s")
    print("Edge CPU Performance                      :", json.dumps(report["edge_performance"]))
    print(f"Report saved -> {REPORT_OUT}")
    print(f"Figures saved -> {FIG_DIR}")


if __name__ == "__main__":
    main()
