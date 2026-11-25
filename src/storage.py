import csv
import hashlib
import io
import json
import os
import stat
import tempfile
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
if ROOT == ROOT.parent or ROOT.drive.casefold() == "c:":
    raise RuntimeError(f"PROJECT_ROOT không phù hợp: {ROOT}")


def safe(relative, base=ROOT):
    name = str(relative).replace("\\", "/")
    parts = name.split("/")
    if any(part in {"", ".", ".."} or ":" in part or part.endswith((" ", "."))
           or PureWindowsPath(part).is_reserved() for part in parts):
        raise ValueError("Đường dẫn không hợp lệ")
    parent = base
    for folder in (base, *base.parents):
        check_link(folder)
    if not base.is_relative_to(ROOT):
        raise ValueError("Thư mục ngoài project")
    for part in parts:
        parent /= part
        check_link(parent)
    if not parent.resolve().is_relative_to(base):
        raise ValueError("Đường dẫn thoát khỏi thư mục cho phép")
    return parent


def check_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
        raise ValueError(f"Không hỗ trợ liên kết: {path}")
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError(f"Không hỗ trợ hard link: {path}")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic(path, data):
    path = safe(path.relative_to(ROOT).as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def write_json(path, value):
    atomic(path, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())


def rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_rows(path, records, fields=None):
    if fields is None:
        if not records:
            raise ValueError("Cần khai báo cột cho bảng rỗng")
        fields = list(records[0])
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields)
    writer.writeheader()
    writer.writerows(records)
    atomic(path, stream.getvalue().encode("utf-8-sig"))
