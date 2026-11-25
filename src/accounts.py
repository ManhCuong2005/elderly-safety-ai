import http.client
import json
import logging
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from queue import Full, Queue
from time import monotonic
from urllib.parse import urlencode
from uuid import uuid4

from flask import jsonify, request, session
from flask.sessions import SecureCookieSessionInterface

from . import telegram
from .storage import read_json, safe

logger = logging.getLogger(__name__)


class AccountError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class Supabase:
    def __init__(self, host, publishable_key, secret_key):
        self.host = host
        self.publishable_key = publishable_key
        self.secret_key = secret_key

    def request(self, method, path, payload=None, *, database=False):
        key = self.secret_key if database else self.publishable_key
        if not key:
            raise AccountError("Máy chủ chưa cấu hình cơ sở dữ liệu tài khoản.")
        headers = {"apikey": key, "Content-Type": "application/json"}
        connection = http.client.HTTPSConnection(self.host, timeout=5)
        try:
            connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
            response = connection.getresponse()
            raw = response.read(1024 * 1024)
            result = json.loads(raw) if raw else None
        except (OSError, ValueError, http.client.HTTPException):
            raise AccountError("Không kết nối được với Supabase. Vui lòng thử lại.") from None
        finally:
            connection.close()
        if response.status < 300:
            return result
        code = result if isinstance(result, dict) else {}
        code = code.get("error_code") or code.get("code")
        if database:
            if code == "23505":
                raise AccountError("Tài khoản CameraAI hoặc Telegram này đã có liên kết.", 409)
            logger.warning("Không truy cập được dữ liệu tài khoản Supabase (%s).", response.status)
            raise AccountError("Lịch sử hoặc kết nối Telegram chưa khả dụng. Kiểm tra cấu hình Supabase.")
        if response.status == 429 or code in {"over_email_send_rate_limit", "over_request_rate_limit"}:
            raise AccountError("Có quá nhiều yêu cầu. Vui lòng đợi rồi thử lại.", 429)
        if code == "email_not_confirmed":
            raise AccountError("Hãy xác nhận email trước khi đăng nhập.", 403)
        if code == "invalid_credentials" or response.status == 401:
            raise AccountError("Email hoặc mật khẩu không đúng.", 401)
        if code in {"email_address_invalid", "email_address_not_authorized", "validation_failed", "weak_password"}:
            raise AccountError("Supabase không chấp nhận email hoặc mật khẩu này.", 400)
        raise AccountError("Supabase chưa xử lý được yêu cầu tài khoản. Vui lòng thử lại.")

    def authenticate(self, payload, signup):
        path = "/auth/v1/signup" if signup else "/auth/v1/token?grant_type=password"
        result = self.request("POST", path, payload)
        if signup and isinstance(result, dict) and not result.get("access_token"):
            return None
        user = result.get("user") if isinstance(result, dict) else None
        if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user.get("email"):
            raise AccountError("Supabase không trả về thông tin tài khoản hợp lệ.")
        metadata = user.get("user_metadata") or {}
        return {"id": user["id"], "email": user["email"], "name": str(metadata.get("name", ""))[:80]}

    def user_rows(self, method, table, user_id, *, payload=None, **query):
        if method == "POST":
            payload = {**payload, "user_id": user_id}
        else:
            query["user_id"] = f"eq.{user_id}"
        return self.request(method, f"/rest/v1/{table}?{urlencode(query)}", payload, database=True)


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

    def send(self, chat_id, text, *, photo=None):
        try:
            if photo is None:
                telegram.api(self.token, "sendMessage", {"chat_id": chat_id, "text": text})
            else:
                telegram.api(self.token, "sendPhoto", {"chat_id": chat_id, "caption": text}, photo=photo)
        except telegram.TelegramError as error:
            raise AccountError(str(error), 502) from None

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

    def enqueue(self, user_id):
        try:
            self.pending.put_nowait((user_id, datetime.now(timezone.utc)))
        except Full:
            logger.warning("Hàng đợi cảnh báo đã đầy.")

    def send_linked(self, user_id, text, *, photo=None):
        if not self.links:
            return False
        with self.links.delivery_lock(user_id):
            rows = self.db.user_rows("GET", "telegram_links", user_id, select="chat_id", limit=1)
            if not rows:
                return False
            self.links.send(rows[0]["chat_id"], text, photo=photo)
            return True

    def record(self, user_id, occurred_at):
        alert_id = str(uuid4())
        self.db.user_rows("POST", "fall_alerts", user_id, payload={
            "id": alert_id, "occurred_at": occurred_at.isoformat(), "telegram_status": "pending",
        })
        status = "error"
        try:
            status = "sent" if self.send_linked(user_id, telegram.fall_text(occurred_at)) else "unlinked"
        except AccountError as error:
            logger.warning("Không gửi được cảnh báo Telegram. %s", error)
        finally:
            self.db.user_rows("PATCH", "fall_alerts", user_id, id=f"eq.{alert_id}",
                              payload={"telegram_status": status})

    def run(self):
        while True:
            user_id, occurred_at = self.pending.get()
            try:
                self.record(user_id, occurred_at)
            except AccountError as error:
                logger.warning("Không lưu được lịch sử cảnh báo. %s", error)
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

    @app.post("/api/account/register")
    @app.post("/api/account/login")
    def authenticate():
        if db is None:
            raise AccountError("Máy chủ chưa cấu hình Supabase.")
        signup = request.path.endswith("/register")
        request.max_content_length = 8192
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise AccountError("Dữ liệu đăng nhập không hợp lệ.", 400)
        email, password = body.get("email"), body.get("password")
        name = body.get("name", "")
        if not isinstance(email, str) or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+", email.strip()):
            raise AccountError("Nhập địa chỉ email hợp lệ.", 400)
        if not isinstance(password, str) or not ((8 if signup else 1) <= len(password) <= 256):
            raise AccountError("Mật khẩu đăng ký cần ít nhất 8 ký tự." if signup else "Nhập mật khẩu hợp lệ.", 400)
        payload = {"email": email.strip(), "password": password}
        if signup:
            if not isinstance(name, str) or len(name.strip()) > 80:
                raise AccountError("Tên hiển thị tối đa 80 ký tự.", 400)
            payload["data"] = {"name": name.strip()}
        user = db.authenticate(payload, signup)
        if user is None:
            return jsonify(confirmation_required=True), 202
        end_session()
        session.permanent = True
        session.update(user=user, login_id=secrets.token_urlsafe(24))
        return jsonify(user=user)

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
        return jsonify(events=user_rows("GET", "fall_alerts", select="id,occurred_at,telegram_status",
                                        order="occurred_at.desc,id.desc", limit=50))

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
