"""Tests for social media / public video collector & V2 analyzer tool."""
import csv
import json
from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ENGINE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from collect_and_analyze import (
    SUPPORTED_PLATFORMS,
    analyze_video,
    load_sources_csv,
    normalize_activity,
    save_analysis_outputs,
    search_platform,
)
from src.config import Config
from src.ml.features import FEATURE_NAMES


def test_supported_platforms_and_invalid_platform():
    for plat in ("youtube", "tiktok", "facebook", "instagram", "dailymotion", "vimeo", "pexels"):
        assert plat in SUPPORTED_PLATFORMS
    with pytest.raises(ValueError):
        search_platform("unknown_site", "fall")


def test_normalize_activity_and_csv_parser(tmp_path):
    assert normalize_activity("fall") == "FALL"
    assert normalize_activity("Bending") == "BENDING"
    assert normalize_activity("NON_FALL") == "OTHER"
    with pytest.raises(ValueError):
        normalize_activity("INVALID_LABEL")

    csv_file = tmp_path / "sources.csv"
    csv_file.write_text(
        "url,label,start_s,end_s,note\n"
        "# comment line\n"
        "https://example.com/v1,FALL,2,10,test fall\n"
        "https://example.com/v2,BENDING,,,test bend\n",
        encoding="utf-8",
    )
    rows = load_sources_csv(csv_file)
    assert len(rows) == 2
    assert rows[0]["label"] == "FALL" and rows[0]["start_s"] == 2.0 and rows[0]["end_s"] == 10.0
    assert rows[1]["label"] == "BENDING" and rows[1]["start_s"] is None


def test_analyze_real_video_and_export_outputs(tmp_path):
    sample = ENGINE_DIR / "datasets" / "raw" / "fall-28-cam0.mp4"
    model = ENGINE_DIR / "models" / "pose_landmarker_full.task"
    if not sample.is_file() or not model.is_file():
        pytest.skip("Sample UR Fall MP4 or pose model not present locally")

    cfg = Config.load(ENGINE_DIR / "configs" / "v2_ml.json")
    rep, feats = analyze_video(
        sample,
        cfg,
        str(model),
        expected_activity="FALL",
        input_layout="ur-rgbd",
        render_dir=tmp_path / "annotated",
    )
    assert rep["expected_label"] == "FALL"
    assert rep["predicted_label"] == "FALL"
    assert rep["match_expected"] is True
    assert rep["quality_verdict"] in ("USABLE", "REVIEW_NEEDED")
    assert Path(rep["rendered_video"]).is_file()
    assert len(feats) > 10

    j_p, c_p, f_p = save_analysis_outputs([rep], feats, tmp_path)
    summary = json.loads(j_p.read_text(encoding="utf-8"))
    assert summary["total_videos"] == 1
    assert summary["matched_expected"] == 1
    with f_p.open(newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    for col in FEATURE_NAMES:
        assert col in header
    assert c_p.is_file()
