import argparse
import base64
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .storage import ROOT, read_json, rows, safe, sha, write_json, write_rows

SLUG = "abhatewari22/varishta-mm50-organized"
VERSION = 5
SOURCE = f"https://www.kaggle.com/datasets/{SLUG}"
API = "https://www.kaggle.com/api/v1/datasets"
RAW = ROOT / "data/raw/varishta"
MANIFEST = ROOT / "data/manifests/download_manifest.csv"
CATALOG = ROOT / "data/manifests/source_catalog.csv"
DOCS = {"README.txt", "age_to_person_map.csv", "final_person_list_with_batch.csv",
        "folder_count_summary.csv", "person_count_per_activity.csv"}
FALL = {"Sit_n_Fall", "Trip_n_Fall", "Walk_n_Fall"}
NORMAL = {"Walking", "Standing", "Sitting", "Jogging", "Stair_Climbing", "Stair_Descending"}
MEDIA_NAME = re.compile(r"(Person[0-9]+)_(?:video\.mp4|Metadata\.csv)")
PILOT = {
    "Person01": {"Sit_n_Fall", "Jogging", "Standing"},
    "Person02": {"Trip_n_Fall", "Sitting", "Stair_Climbing"},
    "Person03": {"Walk_n_Fall", "Walking", "Stair_Descending"},
    "Person04": {"Sit_n_Fall", "Sitting", "Stair_Descending"},
    "Person05": {"Trip_n_Fall", "Walking", "Jogging"},
    "Person06": {"Walk_n_Fall", "Standing", "Stair_Climbing"},
}
FIELDS = ["relative_path", "source", "original_name", "size_bytes", "sha256",
          "dataset_version", "project_download", "download_run"]


def request(action, extra="", params=None, start=0):
    query = urlencode({"datasetVersionNumber": VERSION, **(params or {})})
    req = Request(f"{API}/{action}/{SLUG}{extra}?{query}")
    token = os.getenv("KAGGLE_API_TOKEN")
    username, key = os.getenv("KAGGLE_USERNAME"), os.getenv("KAGGLE_KEY")
    if not token:
        token_path = safe(".secrets/access_token")
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
    if not (token or (username and key)):
        credential = read_json(safe(".secrets/kaggle.json"), {})
        username, key = credential.get("username"), credential.get("key")
    if token:
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    elif username and key:
        basic = base64.b64encode(f"{username}:{key}".encode()).decode()
        req.add_unredirected_header("Authorization", f"Basic {basic}")
    if start:
        req.add_header("Range", f"bytes={start}-")
    return urlopen(req, timeout=45)


def catalog():
    seen = set()
    records = []
    token = ""
    while True:
        with request("list", params={"pageSize": 200, "pageToken": token}) as response:
            page = json.load(response)
        if page.get("errorMessage"):
            raise ValueError("Kaggle báo lỗi danh mục")
        for item in page["datasetFiles"]:
            name = item["name"]
            safe(name, RAW)
            if name.casefold() in seen:
                raise ValueError("Tên trùng trong danh mục Kaggle")
            seen.add(name.casefold())
            records.append({"name": name, "totalBytes": item["totalBytes"], "dataset_version": VERSION})
        token = page.get("nextPageToken")
        if not token:
            break
    write_rows(CATALOG, records)
    return records


def wanted(name, all_videos, clip_ids):
    if name in DOCS:
        return True
    parts = name.split("/")
    if len(parts) != 3:
        return False
    group, person, filename = parts
    return (group in FALL | NORMAL and MEDIA_NAME.fullmatch(filename) is not None
            and (all_videos or (f"{group}/{person}" in clip_ids if clip_ids else group in PILOT.get(person, set()))))


def fetch(item, old, run):
    name, size = item["name"], int(item["totalBytes"])
    path = safe(name, RAW)
    path.parent.mkdir(parents=True, exist_ok=True)
    relative = path.relative_to(ROOT).as_posix()
    receipt = safe(".cache/downloads/" + name + ".json")
    pending = read_json(receipt)
    historic = old.get(relative) or pending
    if path.exists():
        digest = sha(path)
        if path.stat().st_size != size or (historic and historic["sha256"] != digest):
            raise ValueError(f"File hiện có không khớp. Giữ nguyên: {relative}")
        if historic:
            return historic
        return dict(zip(FIELDS, (relative, SOURCE, name, size, digest, VERSION, "no", "")))
    part = safe(".cache/downloads/" + name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            transfer(name, part, size)
            break
        except HTTPError as error:
            if error.code in {401, 403, 404} or attempt == 2:
                raise
        except (OSError, ValueError, URLError):
            if attempt == 2:
                raise
        time.sleep(0.4 * (attempt + 1))
    record = dict(zip(FIELDS, (relative, SOURCE, name, size, sha(part), VERSION, "yes", run)))
    write_json(receipt, record)
    if path.exists():
        raise ValueError(f"File đích đã xuất hiện: {relative}")
    part.rename(path)
    return record


def transfer(name, part, size):
    start = part.stat().st_size if part.exists() else 0
    if start > size:
        raise ValueError(f"File tải dở quá kích thước: {name}")
    if start != size:
        with request("download", "/" + quote(name, safe=""), start=start) as response:
            if response.headers.get_content_type() == "text/html":
                raise ValueError(f"Kaggle trả về trang web thay file: {name}")
            resume = response.status == 206
            if resume and not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                raise ValueError(f"Kaggle trả sai khoảng byte: {name}")
            if not resume:
                start = 0
            with part.open("ab" if resume else "wb") as stream:
                while chunk := response.read(1024 * 1024):
                    start += len(chunk)
                    if start > size:
                        raise ValueError(f"Kaggle trả quá kích thước: {name}")
                    stream.write(chunk)
    if not part.exists() or part.stat().st_size != size:
        raise ValueError(f"Kaggle trả thiếu byte: {name}")


@contextmanager
def download_lock():
    import msvcrt

    with safe(".cache/dataset-download.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise ValueError("Chỉ chạy một lệnh tải dữ liệu cùng lúc") from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def download(all_videos=False, clip_ids=()):
    entries = rows(CATALOG) or catalog()
    if any(int(item["dataset_version"]) != VERSION for item in entries):
        raise ValueError("Danh mục không khớp phiên bản")
    selected = [item for item in entries if wanted(item["name"], all_videos, clip_ids)]
    available = {item["name"].rsplit("/", 1)[0] for item in selected if item["name"].endswith(".mp4")}
    if set(clip_ids) - available:
        raise ValueError(f"Clip không có trong danh mục: {sorted(set(clip_ids) - available)}")
    old = {item["relative_path"]: item for item in rows(MANIFEST)}
    needed = sum(int(item["totalBytes"]) for item in selected if not safe(item["name"], RAW).exists())
    free = shutil.disk_usage(ROOT).free
    print(f"Dung lượng trống {free:,} byte. Cần tối đa {needed:,} byte cho đợt tải theo file.", flush=True)
    if free < needed + 256 * 1024**2:
        raise ValueError("Thiếu dung lượng. Dùng đợt pilot hoặc giải phóng dung lượng trong ổ.")
    for item in selected:
        safe(item["name"], RAW).parent.mkdir(parents=True, exist_ok=True)
        safe(".cache/downloads/" + item["name"] + ".part").parent.mkdir(parents=True, exist_ok=True)
    run = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    failures = []
    previous = old.copy()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, item, previous, run): item["name"] for item in selected}
        for future in as_completed(futures):
            try:
                record = future.result()
            except HTTPError as error:
                failures.append((futures[future], f"HTTP {error.code}"))
            except ValueError as error:
                failures.append((futures[future], str(error)))
            except (OSError, URLError) as error:
                failures.append((futures[future], type(error).__name__))
            else:
                old[record["relative_path"]] = record
                write_rows(MANIFEST, sorted(old.values(), key=lambda row: row["relative_path"]), FIELDS)
                print(record["original_name"], flush=True)
    if failures:
        for name, error in failures:
            print(f"{name}: {error}")
        raise SystemExit("Tải chưa đủ. Chạy lại để tiếp tục. Với HTTP 401/403, kiểm tra quyền Kaggle.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["catalog", "download"])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--clip", action="append", default=[])
    args = parser.parse_args()
    if args.command == "catalog":
        print(f"{len(catalog())} mục từ Kaggle")
    else:
        with download_lock():
            download(args.all, args.clip)
