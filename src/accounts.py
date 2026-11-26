import http.client
import json
import logging
import os
import re
import secrets
import threading
from datetime import date, datetime, timedelta, timezone
from queue import Full, Queue
from time import monotonic
from urllib.parse import urlencode
from uuid import uuid4

from flask import Response, jsonify, request, session
from flask.sessions import SecureCookieSessionInterface

from . import telegram
from .storage import read_json, safe

logger = logging.getLogger(__name__)


class AccountError(Exception):
    def __init__(self, message, status=503, *, code=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


class Supabase:
    def __init__(self, host, publishable_key, secret_key):
        self.host = host
        self.publishable_key = publishable_key
        self.secret_key = secret_key

    def request(self, method, path, payload=None, *, database=False, prefer=None):
        key = self.secret_key if database else self.publishable_key
        if not key:
            raise AccountError("Máy chủ chưa cấu hình cơ sở dữ liệu tài khoản.")
        headers = {"apikey": key, "Content-Type": "application/json"}
        if prefer is not None:
            headers["Prefer"] = prefer
        sends_confirmation = path in {"/auth/v1/signup", "/auth/v1/resend"}
        connection = http.client.HTTPSConnection(self.host, timeout=20 if sends_confirmation else 5)
        try:
            connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024)
        except TimeoutError:
            if sends_confirmation:
                raise AccountError("Supabase phản hồi quá lâu khi gửi email xác nhận. Kiểm tra hộp thư rồi thử lại.", 504) from None
            raise AccountError("Supabase phản hồi quá lâu. Vui lòng thử lại.", 504) from None
        except (OSError, http.client.HTTPException):
            raise AccountError("Không kết nối được với Supabase. Vui lòng thử lại.") from None
        finally:
            connection.close()
        try:
            result = json.loads(raw) if raw else None
        except ValueError:
            logger.warning("Supabase trả về phản hồi không đọc được (HTTP %s).", response.status)
            raise AccountError(f"Supabase trả về phản hồi không đọc được (HTTP {response.status}).", 502) from None
        if response.status < 300:
            return result
        details = result if isinstance(result, dict) else {}
        code = details.get("error_code") or details.get("code")
        provider_message = details.get("msg") or details.get("message") or details.get("error_description")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
            code = None
        if database:
            if code == "23505":
                raise AccountError("Tài khoản CameraAI hoặc Telegram này đã có liên kết.", 409)
            if code in {"PGRST205", "42P01"} and path.startswith("/rest/v1/camera_settings?"):
                raise AccountError("Supabase chưa có bảng cài đặt camera. Hãy chạy lại supabase/schema.sql.")
            logger.warning("Không truy cập được dữ liệu tài khoản Supabase (%s).", response.status)
            raise AccountError("Lịch sử hoặc kết nối Telegram chưa khả dụng. Kiểm tra cấu hình Supabase.")
        if code == "over_email_send_rate_limit":
            wait = re.fullmatch(r"For security purposes, you can only request this after ([0-9]{1,5}) seconds?\.",
                                provider_message) if isinstance(provider_message, str) else None
            if wait:
                seconds = int(wait[1]) + 1
                raise AccountError(f"Chờ {seconds} giây trước khi yêu cầu mã mới.", 429, retry_after=seconds)
            raise AccountError("Đã tới giới hạn gửi email xác nhận. Vui lòng đợi rồi thử lại.", 429)
        if response.status == 429 or code == "over_request_rate_limit":
            raise AccountError("Có quá nhiều yêu cầu. Vui lòng đợi rồi thử lại.", 429)
        if code == "email_not_confirmed":
            raise AccountError("Hãy xác nhận email trước khi đăng nhập.", 403, code=code)
        if path == "/auth/v1/verify" and code == "otp_expired":
            raise AccountError("Supabase không chấp nhận mã này. Nhập mã trong thư mới nhất hoặc gửi lại mã.", 400)
        if code == "invalid_credentials" or (response.status == 401 and path.startswith("/auth/v1/token?")):
            raise AccountError("Email hoặc mật khẩu không đúng.", 401)
        if code == "email_address_not_authorized":
            raise AccountError("Supabase không được phép gửi thư đến địa chỉ này. Kiểm tra cấu hình SMTP trong Supabase.", 403)
        if code == "signup_disabled":
            raise AccountError("Supabase đang tắt tính năng đăng ký tài khoản mới.", 403)
        if code in {"email_address_invalid", "validation_failed", "weak_password"}:
            raise AccountError("Supabase không chấp nhận email hoặc mật khẩu này.", 400)
        if (sends_confirmation and isinstance(provider_message, str)
                and provider_message.lower().startswith("error sending confirmation email")):
            logger.warning("Supabase Auth báo lỗi gửi thư xác nhận trên %s (HTTP %s, %s).",
                           path, response.status, code or "không có mã lỗi")
            raise AccountError("Supabase báo lỗi ở bước gửi email xác nhận. Xem Auth Logs trong Supabase để kiểm tra SMTP hoặc mẫu thư.", 502)
        logger.warning("Supabase Auth trả lỗi trên %s (HTTP %s, %s).",
                       path.partition("?")[0], response.status, code or "không có mã lỗi")
        raise AccountError(f"Supabase trả lỗi HTTP {response.status} khi xử lý tài khoản. Xem Auth Logs trong Supabase.", 502)

    def authenticate(self, payload, signup):
        path = "/auth/v1/signup" if signup else "/auth/v1/token?grant_type=password"
        result = self.request("POST", path, payload)
        if signup and isinstance(result, dict) and not result.get("access_token"):
            return None
        return self.authenticated_user(result)

    def verify_signup(self, email, token):
        result = self.request("POST", "/auth/v1/verify", {"email": email, "token": token, "type": "signup"})
        return self.authenticated_user(result)

    def resend_signup(self, email):
        self.request("POST", "/auth/v1/resend", {"email": email, "type": "signup"})

    @staticmethod
    def authenticated_user(result):
        user = result.get("user") if isinstance(result, dict) else None
        if (not isinstance(user, dict) or not isinstance(user.get("id"), str)
                or not isinstance(user.get("email"), str) or not user["email"]
                or not isinstance(result.get("access_token"), str) or not result["access_token"]):
            raise AccountError("Supabase không trả về thông tin tài khoản hợp lệ.")
        metadata = user.get("user_metadata") or {}
        return {"id": user["id"], "email": user["email"], "name": str(metadata.get("name", ""))[:80]}

    def user_rows(self, method, table, user_id, *, payload=None, prefer=None, **query):
        if method == "POST":
            payload = {**payload, "user_id": user_id}
        else:
            query["user_id"] = f"eq.{user_id}"
        return self.request(method, f"/rest/v1/{table}?{urlencode(query)}", payload, database=True, prefer=prefer)


def load_supabase():
    try:
        values = read_json(safe(".secrets/supabase.json"), {})
        if not isinstance(values, dict):
            raise ValueError
        url = os.environ.get("SUPABASE_URL", values.get("project_url", ""))
        publishable = os.environ.get("SUPABASE_PUBLISHABLE_KEY", values.get("publishable_key", ""))
        private = os.environ.get("SUPABASE_SECRET_KEY", values.get("secret_key", ""))
        match = re.fullmatch(r"https://([a-z0-9]+\.supabase\.co)/?", url)
        if not match or not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", publishable):
            raise ValueError
        if private and not re.fullmatch(r"sb_secret_[A-Za-z0-9_-]+", private):
            raise ValueError
        return Supabase(match[1], publishable, private)
    except (OSError, TypeError, ValueError):
        logger.warning("Kiểm tra Project URL và API keys trong cấu hình Supabase.")
        return None


class TelegramLinks:
    def __init__(self, token):
        self.token = token
        self.bot = None
        self.offset = 0
        self.pending = {}
        self.lock = threading.Lock()
        self.delivery_locks = [threading.Lock() for _ in range(16)]

    def delivery_lock(self, user_id):
        return self.delivery_locks[hash(user_id) % len(self.delivery_locks)]

    def send(self, chat_id, text):
        try:
            telegram.api(self.token, "sendMessage", {"chat_id": chat_id, "text": text})
        except telegram.TelegramError as error:
            raise AccountError(str(error), 502) from None

    def send_photo(self, chat_id, caption, photo):
        try:
            telegram.api(self.token, "sendPhoto", {"chat_id": chat_id, "caption": caption}, photo=photo)
        except telegram.TelegramError as error:
            if error.status != 400:
                raise AccountError(str(error), 502) from None
            logger.warning("Telegram từ chối ảnh cảnh báo. Gửi thông báo chữ thay thế.")
            self.send(chat_id, caption)
            return "sent_text"
        return "sent"

    def start(self, login_id):
        with self.lock:
            if not self.bot:
                try:
                    bot = telegram.api(self.token, "getMe", {}).get("username", "")
                except telegram.TelegramError as error:
                    raise AccountError(str(error), 502) from None
                if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot):
                    raise AccountError("Không tìm thấy tên bot Telegram.", 502)
                self.bot = bot
            now = monotonic()
            self.pending = {key: value for key, value in self.pending.items() if value["expires"] > now}
            if login_id not in self.pending and len(self.pending) >= 128:
                raise AccountError("Có quá nhiều yêu cầu kết nối Telegram. Vui lòng thử lại sau.", 429)
            code = "camera_" + secrets.token_urlsafe(24)
            self.pending[login_id] = {"code": code, "expires": now + 600, "chat": None}
            return f"https://t.me/{self.bot}?start={code}"

    def check(self, login_id):
        with self.lock:
            entry = self.pending.get(login_id)
            if not entry or entry["expires"] <= monotonic():
                raise AccountError("Liên kết đã hết hạn. Hãy tạo liên kết mới.", 409)
            if entry["chat"] is None:
                by_code = {value["code"]: value for value in self.pending.values() if value["expires"] > monotonic()}
                try:
                    for _ in range(3):
                        updates = telegram.api(self.token, "getUpdates", {
                            "offset": self.offset, "timeout": 0, "allowed_updates": ["message"],
                        })
                        for update in updates:
                            message = update.get("message", {})
                            text = message.get("text", "").split()
                            if len(text) == 2 and text[0] == "/start" and text[1] in by_code:
                                pending = by_code[text[1]]
                                chat = telegram.private_start(message, text[1])
                                if chat and pending["chat"] is None:
                                    pending["chat"] = chat
                            self.offset = max(self.offset, update["update_id"] + 1)
                        if len(updates) < 100 or entry["chat"] is not None:
                            break
                except telegram.TelegramError as error:
                    raise AccountError(str(error), 502) from None
            return entry["chat"]

    def confirm(self, login_id, save):
        with self.lock:
            entry = self.pending.get(login_id)
            if not entry or entry["expires"] <= monotonic() or entry["chat"] is None:
                raise AccountError("Hãy mở bot và kiểm tra kết nối trước khi xác nhận.", 409)
            chat = entry["chat"]
            save(chat)
            del self.pending[login_id]
            return chat

    def cancel(self, login_id):
        with self.lock:
            self.pending.pop(login_id, None)


def load_telegram():
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            config = telegram.read_config()
            token = config and config["bot_token"]
        if token and not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise telegram.TelegramError("Kiểm tra TELEGRAM_BOT_TOKEN.")
        return TelegramLinks(token) if token else None
    except telegram.TelegramError as error:
        logger.warning("Telegram chưa bật. %s", error)
        return None


class AccountAlerts:
    def __init__(self, db, links):
        self.db = db
        self.links = links
        self.pending = Queue(maxsize=64)
        threading.Thread(target=self.run, name="account-alerts", daemon=True).start()

    def enqueue(self, user_id, *, photo=None, absence_seconds=None):
        try:
            self.pending.put_nowait((user_id, datetime.now(timezone.utc), photo, absence_seconds))
        except Full:
            logger.warning("Hàng đợi cảnh báo đã đầy.")

    def send_linked(self, user_id, text, *, photo=None):
        if not self.links:
            return "unavailable"
        with self.links.delivery_lock(user_id):
            rows = self.db.user_rows("GET", "telegram_links", user_id, select="chat_id", limit=1)
            if not rows:
                return "unlinked"
            chat_id = rows[0]["chat_id"]
            if photo is not None:
                return self.links.send_photo(chat_id, text, photo)
            self.links.send(chat_id, text)
            return "sent"

    def record(self, user_id, occurred_at, *, video_time=None, photo=None, absence_seconds=None):
        alert_id = str(uuid4())
        event = {
            "id": alert_id, "occurred_at": occurred_at.isoformat(), "telegram_status": "pending",
        }
        if absence_seconds is not None:
            event["source"] = "camera_absence"
        elif video_time is not None:
            event["source"] = "video_test"
        if photo is not None:
            event["photo_jpeg"] = "\\x" + photo.hex()
        history_status = "saved"
        try:
            self.db.user_rows("POST", "fall_alerts", user_id, payload=event)
        except AccountError as error:
            logger.warning("Không lưu được lịch sử cảnh báo. %s", error)
            history_status = "error"

        status = "error"
        try:
            if absence_seconds is not None:
                text = telegram.absence_text(occurred_at, absence_seconds)
            elif video_time is not None:
                text = telegram.video_test_text(video_time)
            else:
                text = telegram.fall_text(occurred_at)
            status = self.send_linked(user_id, text, photo=photo)
            if status == "sent" and video_time is not None and photo is None:
                status = "sent_text"
        except AccountError as error:
            logger.warning("Không gửi được cảnh báo Telegram. %s", error)

        if history_status == "saved":
            stored_status = {"sent_text": "sent", "unavailable": "unlinked"}.get(status, status)
            try:
                self.db.user_rows("PATCH", "fall_alerts", user_id, id=f"eq.{alert_id}",
                                  payload={"telegram_status": stored_status})
            except AccountError as error:
                logger.warning("Không cập nhật được trạng thái Telegram trong lịch sử. %s", error)
                history_status = "status_error"
        return status, history_status

    def run(self):
        while True:
            user_id, occurred_at, photo, absence_seconds = self.pending.get()
            try:
                self.record(user_id, occurred_at, photo=photo, absence_seconds=absence_seconds)
            finally:
                self.pending.task_done()


class AccountCookie(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return request.is_secure or super().get_cookie_secure(app)


def register_account_routes(app, db, links, stop_sessions):
    app.secret_key = os.environ.get("CAMERAAI_SESSION_SECRET") or secrets.token_bytes(32)
    app.session_interface = AccountCookie()
    app.config.update(SESSION_COOKIE_NAME="cameraai_account", SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_HTTPONLY=True, SESSION_REFRESH_EACH_REQUEST=False,
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12))

    @app.errorhandler(AccountError)
    def account_error(error):
        if error.retry_after is not None:
            return jsonify(error=str(error)), error.status, {"Retry-After": str(error.retry_after)}
        if error.code:
            return jsonify(error=str(error), code=error.code), error.status
        return jsonify(error=str(error)), error.status

    @app.get("/api/account")
    def account():
        return jsonify(user=session.get("user"), configured=db is not None)

    def end_session():
        login_id = session.get("login_id")
        if login_id:
            stop_sessions(login_id)
            if links:
                links.cancel(login_id)
        session.clear()

    def sign_in(user):
        end_session()
        session.permanent = True
        session.update(user=user, login_id=secrets.token_urlsafe(24))
        return jsonify(user=user)

    def email_request():
        if db is None:
            raise AccountError("Máy chủ chưa cấu hình Supabase.")
        request.max_content_length = 8192
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise AccountError("Dữ liệu tài khoản không hợp lệ.", 400)
        email = body.get("email")
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+", email.strip()):
            raise AccountError("Nhập địa chỉ email hợp lệ.", 400)
        return body, email.strip()

    @app.post("/api/account/register")
    @app.post("/api/account/login")
    def authenticate():
        body, email = email_request()
        signup = request.path.endswith("/register")
        password = body.get("password")
        name = body.get("name", "")
        if not isinstance(password, str) or not ((8 if signup else 1) <= len(password) <= 256):
            raise AccountError("Mật khẩu đăng ký cần ít nhất 8 ký tự." if signup else "Nhập mật khẩu hợp lệ.", 400)
        payload = {"email": email, "password": password}
        if signup:
            if not isinstance(name, str) or len(name.strip()) > 80:
                raise AccountError("Tên hiển thị tối đa 80 ký tự.", 400)
            payload["data"] = {"name": name.strip()}
        user = db.authenticate(payload, signup)
        if user is None:
            return jsonify(confirmation_required=True), 202
        return sign_in(user)

    @app.post("/api/account/verify-email")
    def verify_email():
        body, email = email_request()
        token = body.get("token")
        if not isinstance(token, str) or not re.fullmatch(r"[0-9]{6,10}", token):
            raise AccountError("Nhập đầy đủ mã xác nhận từ 6 đến 10 chữ số trong email.", 400)
        return sign_in(db.verify_signup(email, token))

    @app.post("/api/account/resend-email")
    def resend_email():
        _, email = email_request()
        db.resend_signup(email)
        return "", 204

    @app.post("/api/account/logout")
    def logout():
        end_session()
        return "", 204

    def user_rows(method, table, **options):
        if db is None:
            raise AccountError("Máy chủ chưa cấu hình Supabase.")
        return db.user_rows(method, table, session["user"]["id"], **options)

    @app.get("/api/account/history")
    def history():
        selected = request.args.get("date", "")
        page = request.args.get("page", "1")
        if not re.fullmatch(r"[1-9][0-9]{0,4}", page):
            raise AccountError("Trang lịch sử không hợp lệ.", 400)
        filters = {}
        if selected:
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", selected):
                    raise ValueError
                day = date.fromisoformat(selected)
                start = datetime.combine(day, datetime.min.time(), telegram.VN_TIME).astimezone(timezone.utc)
                end = start + timedelta(days=1)
            except (ValueError, OverflowError):
                raise AccountError("Ngày lọc lịch sử không hợp lệ.", 400) from None
            filters["and"] = f"(occurred_at.gte.{start.isoformat()},occurred_at.lt.{end.isoformat()})"
        events = user_rows("GET", "fall_alerts", select="id,occurred_at,telegram_status,source,has_photo",
                           order="occurred_at.desc,id.desc", limit=51, offset=(int(page) - 1) * 50, **filters)
        return jsonify(events=events[:50], has_more=len(events) > 50)

    @app.get("/api/account/history/<uuid:alert_id>/photo")
    def history_photo(alert_id):
        rows = user_rows("GET", "fall_alerts", select="photo_jpeg", id=f"eq.{alert_id}", limit=1)
        value = rows[0]["photo_jpeg"] if rows else None
        if value is None:
            raise AccountError("Cảnh báo này chưa có ảnh.", 404)
        try:
            photo = bytes.fromhex(value[2:]) if value.startswith("\\x") else b""
        except (AttributeError, ValueError):
            photo = b""
        if not photo.startswith(b"\xff\xd8"):
            raise AccountError("Không đọc được ảnh cảnh báo.", 502)
        return Response(photo, mimetype="image/jpeg", headers={"Cross-Origin-Resource-Policy": "same-origin"})

    @app.get("/api/account/telegram")
    def telegram_status():
        if links is None:
            return jsonify(available=False)
        rows = user_rows("GET", "telegram_links", select="label", limit=1)
        return jsonify(available=True, linked=bool(rows), label=rows[0]["label"] if rows else None)

    @app.post("/api/account/telegram/<action>")
    def telegram_action(action):
        if links is None:
            raise AccountError("Máy chủ chưa cấu hình bot Telegram.")
        login_id = session["login_id"]
        if action == "start":
            if user_rows("GET", "telegram_links", select="label", limit=1):
                raise AccountError("Hãy ngắt kết nối Telegram hiện tại trước khi đổi tài khoản.", 409)
            return jsonify(url=links.start(login_id))
        if action == "check":
            chat = links.check(login_id)
            return jsonify(found=bool(chat), label=chat["label"] if chat else None)
        with links.delivery_lock(session["user"]["id"]):
            if action == "confirm":
                chat = links.confirm(login_id, lambda found: user_rows("POST", "telegram_links", payload=found))
                return jsonify(label=chat["label"])
            if action == "unlink":
                links.cancel(login_id)
                user_rows("DELETE", "telegram_links")
                return "", 204
            if action == "test":
                rows = user_rows("GET", "telegram_links", select="chat_id", limit=1)
                if not rows:
                    raise AccountError("Hãy kết nối Telegram trước khi gửi tin nhắn thử.", 409)
                links.send(rows[0]["chat_id"], "Tin nhắn thử từ CameraAI. Tài khoản này đã kết nối Telegram.")
                return "", 204
        raise AccountError("Thao tác Telegram không tồn tại.", 404)
