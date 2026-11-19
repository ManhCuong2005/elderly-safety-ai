"""Select UR RGB sequences, verify ZIP CRC, enforce a 1 GB directory budget."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "datasets"
BASE = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
LIMIT = 1_000_000_000


def size():
    return sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file())


def download(name, destination):
    if destination.exists():
        return
    partial = destination.with_suffix(destination.suffix+".part")
    partial.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(BASE+name, timeout=60) as response, partial.open("wb") as output:
            length = int(response.headers.get("Content-Length", 0))
            if length and size()+length > LIMIT:
                raise RuntimeError("Dataset budget exceeded before download")
            while block := response.read(1024*1024):
                if size()+len(block) > LIMIT:
                    raise RuntimeError("Dataset budget exceeded while streaming")
                output.write(block)
        partial.rename(destination)
    finally:
        partial.unlink(missing_ok=True)


def prepare(clip, split, kind):
    raw, metadata = ROOT/"raw", ROOT/"metadata"
    filename = f"{clip}-cam0-rgb.zip" if kind == "rgb" else f"{clip}-cam0.mp4"
    path = raw/filename
    sequence = raw/f"{clip}-cam0-rgb"
    marker = sequence/".verified.json"
    if kind == "rgb" and marker.exists():
        record = json.loads(marker.read_text())
    else:
        download(filename, path)
        with path.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        record = {"source_url": BASE+filename, "sha256": digest, "download_bytes": path.stat().st_size}
        if kind == "rgb":
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise RuntimeError(f"Corrupt ZIP: {filename}")
                expanded = sum(i.file_size for i in archive.infolist())
                if size()+expanded > LIMIT:
                    raise RuntimeError("Extraction exceeds 1 GB; archive retained; select fewer clips")
                sequence.mkdir(exist_ok=True)
                for info in archive.infolist():
                    target = (sequence/info.filename).resolve()
                    if not target.is_relative_to(sequence.resolve()) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RuntimeError("Unsafe archive member")
                archive.extractall(sequence)
            record["expanded_bytes"] = expanded
            marker.write_text(json.dumps(record, indent=2))
            path.unlink()  # remove only the verified archive downloaded by this script
    sync = metadata/f"{clip}-data.csv"
    download(f"{clip}-data.csv", sync)
    return {**record, "video_id": clip, "subject_id": None, "camera": "cam0",
            "label": "FALL" if clip.startswith("fall") else "NON_FALL", "split": split,
            "path": str((sequence if kind == "rgb" else path).relative_to(ROOT.parent.parent)).replace('\\','/'),
            "sync_path": str(sync.relative_to(ROOT.parent.parent)).replace('\\','/'),
            "fall_onset_s": None, "activity": "fall" if clip.startswith("fall") else "ADL_unspecified",
            "version": "UR online release, accessed 2026-11-09", "license": "CC BY-NC-SA 4.0; academic noncommercial",
            "timestamp_source": "UR sync CSV milliseconds" if kind == "rgb" else "MP4 presentation timeline",
            "subject_split_verified": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format", choices=["rgb", "mp4"], default="rgb")
    p.add_argument("--per-class", type=int, default=3)
    p.add_argument("--start-index", type=int, default=1)
    p.add_argument("--append", action='store_true')
    args = p.parse_args()
    if not 2 <= args.per_class <= 10:
        p.error("Select 2 to 10 sequences per class; budget enforced separately")
    for folder in ["raw", "processed", "metadata"]:
        (ROOT/folder).mkdir(parents=True, exist_ok=True)
    manifest = ROOT/"metadata"/"manifest.json"
    records = json.loads(manifest.read_text()) if args.append and manifest.exists() else []
    existing = {r['video_id'] for r in records}
    for i in range(args.start_index, args.start_index+args.per_class):
        for category in ["fall", "adl"]:
            clip = f"{category}-{i:02d}"
            if clip in existing:
                continue
            print(f"Preparing {clip}; current bytes={size()}", flush=True)
            split = "calibration" if i in [1,9,10] else "test_v1_4" if i>=26 else "test_v1_3" if i>=21 else "test_v1_2" if i>=16 else "test_v1_1" if i >=11 else "test_final" if i in range(4,9) else "test"
            records.append(prepare(clip, split, args.format))
            (ROOT/"metadata"/"manifest.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(json.dumps({"sequences": len(records), "total_bytes": size()}))


if __name__ == "__main__":
    main()
