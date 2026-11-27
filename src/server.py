import argparse
import hashlib
import io
import ipaddress
import logging
import math
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import av
from flask import Flask, abort, jsonify, request, send_file, session as account_session
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

from .accounts import AccountAlerts, AccountError, load_supabase, load_telegram, register_account_routes
from .dataset import RAW
from .inference import Engine, FALL_WARNING, NO_PERSON, TRACKING, web_result
from .keypoints import get_keypoints
from .pose import CONFIG, MODEL, Cadence, Pose, sample_frames
from .posture import extended_posture, load_posture
from .review import ANNOTATIONS, VIDEOS, rotation_for, save_annotation
from .storage import read_json, rows, safe, sha
from .train import SPLIT, load_model

TTL = 8
MAX_SESSIONS = 12
MAX_JPEG = 600_000
MAX_UPLOAD = 64 * 1024**2
MAX_VIDEO_SECONDS = 90
ABSENCE_DEFAULT = 60
ABSENCE_MIN = 10
ABSENCE_MAX = 3600
ABSENCE_FRAME_GAP = 2
logger = logging.getLogger(__name__)


def reject_external_media(*args):
    raise OSError("Video tham chiếu tới nguồn khác")


def alert_jpeg(image):
    try:
        image.thumbnail((640, 640))
        with io.BytesIO() as photo:
            image.save(photo, format="JPEG", quality=82, optimize=True)
            return photo.getvalue()
    except OSError as error:
        logger.warning("Không tạo được ảnh cảnh báo. %s", error)
        return None


@dataclass
class Session:
    engine: Engine
    pace: Cadence
    owner: str
    user_id: str
    absence_after: int | None = None
    person_seen: bool = False
    absence_since: float | None = None
    absence_notified: bool = False
    last_observed: float | None = None
    last_seen: float = field(default_factory=time.monotonic)
    active: bool = True
    last_timestamp: float = -1
    lock: threading.Lock = field(default_factory=threading.Lock)

    def observe_absence(self, state, now):
        if self.last_observed is not None and now - self.last_observed > ABSENCE_FRAME_GAP:
            self.absence_since = None
        self.last_observed = now
        if state in {TRACKING, FALL_WARNING}:
            self.person_seen = True
            self.absence_notified = False
        if state != NO_PERSON or not self.person_seen or self.absence_after is None:
            self.absence_since = None
            return None
        if self.absence_since is None:
            self.absence_since = now
        if not self.absence_notified and now - self.absence_since >= self.absence_after:
            self.absence_notified = True
            return self.absence_after
        return None


class Sessions:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def reap(self):
        while not self.closed.wait(2):
            with self.lock:
                for token in list(self.items):
                    if time.monotonic() - self.items[token].last_seen >= TTL:
                        self.remove_locked(token)

    def remove_locked(self, token):
        entry = self.items.pop(token, None)
        if entry:
            entry.active = False

    def remove(self, token):
        with self.lock:
            self.remove_locked(token)

    def stop_owner(self, owner):
        with self.lock:
            for token, entry in list(self.items.items()):
                if entry.owner == owner:
                    self.remove_locked(token)

    def open(self, cfg, model, threshold, owner, user_id, absence_after):
        with self.lock:
            if len(self.items) >= MAX_SESSIONS:
                return None
            token = secrets.token_urlsafe(24)
            self.items[token] = Session(Engine(cfg, model, threshold), Cadence(1 / cfg["sample_hz"]),
                                        owner, user_id, absence_after)
            return token

    def configure_absence(self, user_id, seconds):
        with self.lock:
            entries = [entry for entry in self.items.values() if entry.user_id == user_id]
        for entry in entries:
            with entry.lock:
                if entry.absence_after != seconds:
                    entry.absence_after = seconds
                    entry.absence_since = None

    def find(self, token):
        with self.lock:
            return self.items.get(token)


def local_client():
    try:
        return (request.host.split(":", 1)[0] in {"localhost", "127.0.0.1"}
                and ipaddress.ip_address(request.remote_addr).is_loopback)
    except (TypeError, ValueError):
        return False


def available_videos(locked_split=None):
    split_matches = locked_split is None or (SPLIT.is_file() and sha(SPLIT) == locked_split)
    splits = {entry["video_id"]: entry for entry in rows(SPLIT)} if split_matches else {}
    annotations = read_json(ANNOTATIONS, {})
    result = {}
    for clip in rows(VIDEOS):
        if not clip["duration_s"] or clip["status"] == "exclude":
            continue
        mark = annotations.get(clip["video_id"])
        if mark and mark["video_sha256"] != clip["sha256"]:
            mark = None
        split = splits.get(clip["video_id"], {})
        result[clip["video_id"]] = {**clip, "split": split.get("split") if split.get("sha256") == clip["sha256"] else None,
                                    "annotation": mark}
    return result


def create_app(host="127.0.0.1", start_sweeper=True):
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=MAX_JPEG, TRUSTED_HOSTS=[host, "127.0.0.1", "localhost"])
    sessions = Sessions()
    pose = None
    admin_lock = threading.Lock()
    pose_lock = threading.Lock()
    upload_lock = threading.Lock()
    settings_lock = threading.Lock()
    try:
        info, model = load_model()
        load_error = None
    except (ValueError, OSError, KeyError) as error:
        info, model, load_error = None, None, str(error)
    cfg = {**CONFIG, **info["config"]} if info else CONFIG
    threshold = info["threshold"] if info else None
    locked_split = info["split_sha256"] if info else None
    train_hashes = {row["sha256"] for row in rows(SPLIT) if row["split"] == "train"} if (
        locked_split and SPLIT.is_file() and sha(SPLIT) == locked_split) else set()
    pose_path = safe("models/" + MODEL["file"])
    pose_ready = pose_path.is_file() and sha(pose_path) == MODEL["sha256"]
    posture = load_posture()
    db = load_supabase()
    telegram = load_telegram()
    alerts = AccountAlerts(db, telegram) if db and db.secret_key else None
    register_account_routes(app, db, telegram, sessions.stop_owner)
    if start_sweeper:
        threading.Thread(target=sessions.reap, daemon=True).start()
    app.extensions["sessions"] = sessions

    def get_pose():
        nonlocal pose
        with pose_lock:
            if pose is None:
                pose = Pose()
            return pose

    def get_clip():
        if not local_client():
            abort(403)
        clip = available_videos(locked_split).get(request.args.get("id"))
        if clip is None:
            abort(404)
        safe_clip(clip)
        return clip

    def tracked_frame(engine, obs):
        result = web_result(engine, obs)
        if result["state"] in {TRACKING, FALL_WARNING}:
            result["activity"] = extended_posture(obs, posture, cfg["confidence"])
        return result

    def tracked_trace(observations):
        engine = Engine(cfg, model, threshold)
        return [tracked_frame(engine, obs) for obs in observations]

    @app.before_request
    def same_origin():
        if request.method in {"POST", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                abort(403)
        if (request.path.startswith("/api/") and request.endpoint not in {"account", "authenticate", "logout"}
                and not account_session.get("login_id")):
            return jsonify(error="Hãy đăng nhập để tiếp tục."), 401

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        return response

    @app.errorhandler(ValueError)
    def bad_value(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(RequestEntityTooLarge)
    def oversized(error):
        return jsonify(error="Tệp hoặc khung hình vượt giới hạn kích thước."), 413

    @app.get("/")
    def index():
        return send_file(safe("web/index.html"))

    @app.get("/assets/<name>")
    def asset(name):
        mime = {
            "app.js": "text/javascript",
            "account.js": "text/javascript",
            "style.css": "text/css",
            "favicon.svg": "image/svg+xml",
        }.get(name)
        if mime is None:
            abort(404)
        return send_file(safe(f"web/{name}"), mimetype=mime)

    @app.get("/assets/fonts/<name>")
    def font_asset(name):
        allowed = {
            f"inter-{subset}-{weight}-normal.woff2"
            for subset in ("latin", "vietnamese")
            for weight in ("400", "500", "600", "700")
        }
        if name not in allowed:
            abort(404)
        return send_file(safe(f"web/fonts/{name}"), mimetype="font/woff2")

    @app.get("/api/status")
    def status():
        message = load_error
        if not pose_ready:
            message = "Thiếu MoveNet hoặc checksum sai. Kiểm tra bước Model."
        elif not info and not message:
            message = "Chưa có bộ phân loại đã huấn luyện. Có thể xem MoveNet khi phát clip."
        elif info and (threshold > 1 or info.get("validation_detected") == 0):
            message = "Bộ phân loại pilot chưa phát hiện được ca ngã trên validation."
        return jsonify(ready=bool(pose_ready and info), pose_ready=pose_ready,
                       model=info["classifier"] if info else None, sample_hz=cfg["sample_hz"],
                       local=local_client(), message=message, posture_ready=posture is not None,
                       upload_max_bytes=MAX_UPLOAD, upload_max_seconds=MAX_VIDEO_SECONDS)

    @app.get("/api/videos")
    def videos():
        if not local_client():
            abort(403)
        return jsonify(list(available_videos(locked_split).values()))

    @app.get("/api/video")
    def video():
        return send_file(safe_clip(get_clip()), mimetype="video/mp4", conditional=True)

    @app.get("/api/replay")
    def playback():
        clip = get_clip()
        observations = get_keypoints(clip, cfg, get_pose())
        trace = tracked_trace(observations)
        return jsonify(trace=trace, classifier_ready=info is not None, rotation=rotation_for(clip))

    @app.post("/api/analyze-video")
    def analyze_video():
        if not local_client():
            abort(403)
        if not info or not pose_ready:
            return jsonify(error="Máy xử lý chưa có đủ model té ngã."), 503
        request.max_content_length = MAX_UPLOAD
        if not upload_lock.acquire(blocking=False):
            return jsonify(error="Đang phân tích một video khác. Thử lại khi video đó xử lý xong."), 429
        alarms = []
        photo = None
        try:
            data = request.get_data(cache=False)
            if data[4:8] == b"ftyp":
                fmt = "mp4"
            elif data.startswith(b"\x1a\x45\xdf\xa3"):
                fmt = "webm"
            else:
                return jsonify(error="Chọn tệp video MP4 hoặc WebM hợp lệ."), 415
            try:
                with av.open(io.BytesIO(data), format=fmt, io_open=reject_external_media) as container:
                    if not container.streams.video:
                        raise ValueError("Tệp không có hình ảnh video.")
                    stream = container.streams.video[0]
                    duration = (float(stream.duration * stream.time_base) if stream.duration is not None
                                else container.duration / av.time_base if container.duration is not None else None)
                    if duration is not None and duration > MAX_VIDEO_SECONDS:
                        raise ValueError(f"Video tối đa {MAX_VIDEO_SECONDS} giây.")
                    if stream.width * stream.height > 3840 * 2160:
                        raise ValueError("Video vượt giới hạn độ phân giải 4K.")
                    if stream.average_rate and stream.average_rate > 61:
                        raise ValueError("Chọn video có tốc độ tối đa 60 khung hình/giây.")
                    estimator = get_pose()
                    estimator.reset_tracking()
                    engine = Engine(cfg, model, threshold)
                    trace = []
                    for t, image in sample_frames(container, cfg["sample_hz"], limit_s=MAX_VIDEO_SECONDS):
                        result = tracked_frame(engine, estimator.observe(t, image))
                        trace.append(result)
                        if result["alarm"]:
                            if not alarms and alerts is not None:
                                photo = alert_jpeg(image)
                            alarms.append(result["t"])
            except (av.FFmpegError, OSError):
                raise ValueError("Không đọc được video. Thử một tệp MP4 hoặc WebM khác.") from None
            if not trace:
                raise ValueError("Video không có khung hình đọc được.")
            matches_train = hashlib.sha256(data).hexdigest() in train_hashes
        finally:
            upload_lock.release()
        telegram_status = "unavailable" if alarms else None
        history_status = "unavailable" if alarms else None
        if alarms and alerts is not None:
            telegram_status, history_status = alerts.record(account_session["user"]["id"], datetime.now(timezone.utc),
                                                             video_time=alarms[0], photo=photo)
        return jsonify(trace=trace, classifier_ready=True, alarms=alarms, telegram_status=telegram_status,
                       history_status=history_status,
                       has_predictions=any(frame["score"] is not None for frame in trace), matches_train=matches_train)

    @app.post("/api/annotation")
    def annotate():
        clip = get_clip()
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError("Dữ liệu nhãn không hợp lệ")
        with admin_lock:
            mark = save_annotation(clip, payload, "local-review")
        return jsonify(mark)

    @app.post("/api/session")
    def start():
        if not info:
            return jsonify(error=load_error or "Chưa có bộ phân loại đã huấn luyện."), 503
        get_pose().reset_tracking()
        user_id = account_session["user"]["id"]
        with settings_lock:
            absence_after = None
            if alerts is not None:
                try:
                    settings = camera_settings(user_id)
                    if settings["enabled"]:
                        absence_after = settings["seconds"]
                except AccountError as error:
                    logger.warning("Không tải được cài đặt vắng người. %s", error)
            token = sessions.open(cfg, model, threshold, account_session["login_id"], user_id, absence_after)
        if token is None:
            return jsonify(error="Đã đầy phiên theo dõi. Thử lại sau."), 429
        return jsonify(token=token, sample_hz=cfg["sample_hz"])

    def camera_settings(user_id):
        saved = db.user_rows("GET", "camera_settings", user_id, select="absence_enabled,absence_seconds", limit=1)
        if saved:
            return {"enabled": saved[0]["absence_enabled"], "seconds": saved[0]["absence_seconds"]}
        return {"enabled": False, "seconds": ABSENCE_DEFAULT}

    @app.route("/api/account/camera-settings", methods=["GET", "POST"])
    def settings_camera():
        if alerts is None:
            raise AccountError("Máy chủ chưa cấu hình lưu cài đặt camera.")
        user_id = account_session["user"]["id"]
        if request.method == "GET":
            return jsonify(camera_settings(user_id))
        request.max_content_length = 2048
        values = request.get_json(silent=True)
        if not isinstance(values, dict) or type(values.get("enabled")) is not bool:
            raise AccountError("Chọn bật hoặc tắt cảnh báo.", 400)
        enabled, seconds = values["enabled"], values.get("seconds")
        if type(seconds) is not int or not ABSENCE_MIN <= seconds <= ABSENCE_MAX:
            raise AccountError(f"Nhập số giây từ {ABSENCE_MIN} đến {ABSENCE_MAX}.", 400)
        with settings_lock:
            db.user_rows("POST", "camera_settings", user_id,
                         payload={"absence_enabled": enabled, "absence_seconds": seconds},
                         prefer="resolution=merge-duplicates")
            sessions.configure_absence(user_id, seconds if enabled else None)
        return jsonify(enabled=enabled, seconds=seconds)

    @app.delete("/api/session/<token>")
    def stop(token):
        entry = sessions.find(token)
        if entry and entry.owner == account_session["login_id"]:
            sessions.remove(token)
        return "", 204

    @app.post("/api/session/<token>/confirm-safe")
    def confirm_safe(token):
        entry = sessions.find(token)
        if entry is None or entry.owner != account_session["login_id"]:
            return jsonify(error="Phiên đã kết thúc. Bấm bắt đầu lại."), 410
        with entry.lock:
            cleared = entry.engine.confirm_safe(entry.last_timestamp if entry.last_timestamp >= 0 else None)
            return jsonify(cleared=cleared, state=entry.engine.state, alert_locked=entry.engine.alert_locked)

    @app.post("/api/frame/<token>")
    def frame(token):
        session = sessions.find(token)
        if session is None or session.owner != account_session["login_id"]:
            return jsonify(error="Phiên đã kết thúc. Bấm bắt đầu lại."), 410
        if not session.lock.acquire(blocking=False):
            return "", 204
        try:
            try:
                timestamp = float(request.headers.get("X-Frame-Time", ""))
            except ValueError:
                return jsonify(error="Timestamp không hợp lệ"), 400
            if not math.isfinite(timestamp) or not 0 <= timestamp <= 86400 or timestamp <= session.last_timestamp:
                return jsonify(error="Timestamp không hợp lệ"), 400
            if request.mimetype != "image/jpeg":
                return jsonify(error="Frame phải là JPEG"), 415
            now = time.monotonic()
            if not session.active or now - session.last_seen >= TTL:
                sessions.remove(token)
                return jsonify(error="Phiên đã hết thời gian chờ."), 410
            session.last_seen = now
            session.last_timestamp = timestamp
            if not session.pace.due(timestamp):
                return "", 204
            try:
                with Image.open(io.BytesIO(request.get_data()), formats=["JPEG"]) as jpeg:
                    if max(jpeg.size) > 1280:
                        return jsonify(error="Frame camera quá lớn"), 413
                    image = jpeg.convert("RGB")
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                return jsonify(error="Không đọc được khung camera"), 400
            if not session.active:
                return "", 204
            obs = get_pose().observe(timestamp, image)
            if not session.active:
                return "", 204
            result = tracked_frame(session.engine, obs)
            if alerts is not None:
                if result["alarm"]:
                    alerts.enqueue(session.user_id, photo=alert_jpeg(image))
                absence = session.observe_absence(result["state"], now)
                if absence is not None:
                    alerts.enqueue(session.user_id, photo=alert_jpeg(image), absence_seconds=absence)
                    result["absence_alarm"] = absence
            return jsonify(result)
        finally:
            session.lock.release()

    return app


def safe_clip(clip):
    full = safe(clip["relative_path"])
    if not full.is_relative_to(RAW) or full.suffix.lower() != ".mp4" or not full.is_file():
        abort(404)
    return full


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.host)
    if args.cert or args.key:
        if not (args.cert and args.key and address.is_private and not address.is_unspecified):
            raise SystemExit("HTTPS cần IP riêng cụ thể và cả đường dẫn Cert/Key tương đối trong project.")
        from werkzeug.serving import run_simple

        print(f"https://{args.host}:{args.port}", flush=True)
        run_simple(args.host, args.port, create_app(args.host), threaded=True,
                   ssl_context=(str(safe(args.cert)), str(safe(args.key))))
    else:
        if not address.is_loopback:
            raise SystemExit("Camera qua LAN cần HTTPS. Xem README.")
        from waitress import serve

        print(f"http://{args.host}:{args.port}", flush=True)
        serve(create_app(args.host), host=args.host, port=args.port,
              threads=6, max_request_body_size=MAX_UPLOAD + 1, inbuf_overflow=MAX_JPEG + 64_000)
