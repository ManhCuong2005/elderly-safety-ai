import hashlib
import tarfile
from urllib.request import urlopen

from .storage import atomic, read_json, safe, sha


def prepare():
    info = read_json(safe("models/movenet.json"))
    model = safe("models/" + info["file"])
    if model.exists():
        if sha(model) != info["sha256"]:
            raise ValueError("Checksum MoveNet sai. Kiểm tra file đã có trong models.")
        print(f"MoveNet hợp lệ: {model}")
        return
    archive = safe(".cache/movenet.tar.gz")
    if not archive.exists():
        with urlopen(info["download"], timeout=45) as response:
            data = response.read(8 * 1024**2 + 1)
        if len(data) > 8 * 1024**2:
            raise ValueError("Archive MoveNet quá lớn")
        atomic(archive, data)
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        if len(members) != 1 or members[0].name != info["file"] or not members[0].isreg():
            raise ValueError("Archive chỉ được chứa đúng file trọng số, không chứa đường dẫn hoặc liên kết")
        member = members[0]
        if not 0 < member.size <= 8 * 1024**2:
            raise ValueError("Kích thước trọng số không hợp lệ")
        with package.extractfile(member) as stream:
            data = stream.read()
    if hashlib.sha256(data).hexdigest() != info["sha256"]:
        raise ValueError("Checksum MoveNet tải về sai")
    atomic(model, data)
    print(f"Đã chuẩn bị MoveNet: {model}")


if __name__ == "__main__":
    prepare()
