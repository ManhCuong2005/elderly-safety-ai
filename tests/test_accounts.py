import io
import json
import unittest
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import call, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from src.accounts import AccountAlerts, AccountError, Supabase, TelegramLinks
from src.inference import FALL_WARNING, NO_PERSON, UNCLEAR
from src.server import Session, create_app
from src.storage import safe
from src.telegram import TelegramError
from src.train import load_model, load_split


class SupabaseFixture(Supabase):
    def __init__(self):
        super().__init__("test.supabase.co", "publishable", "secret")
        self.links = {}
        self.events = {}
        self.settings = {}
        self.pending_signups = {}
        self.avatars = {}
        self.names = {}
        self.passwords = {}

    def request(self, method, path, payload=None, *, database=False, prefer=None, token=None):
        route = urlsplit(path)
        if route.path == "/auth/v1/signup":
            email = payload["email"]
            self.pending_signups[email] = ("012345", payload["data"]["name"])
            return {"id": "pending-confirmation"}
        if route.path in {"/auth/v1/verify", "/auth/v1/resend"}:
            assert method == "POST" and payload["type"] == "signup"
            email = payload["email"]
            token, name = self.pending_signups.get(email, (None, ""))
            if route.path == "/auth/v1/resend":
                assert payload == {"email": email, "type": "signup"}
                if token:
                    self.pending_signups[email] = ("06543210", name)
                return {}
            if payload["token"] != token:
                raise AccountError("Mã xác nhận sai hoặc đã hết hạn.", 400)
            self.pending_signups.pop(email)
            return {"access_token": "private-test-token", "user": {
                "id": email.split("@")[0], "email": email, "user_metadata": {"name": name},
            }}
        if route.path == "/auth/v1/token":
            email = payload["email"]
            if payload["password"] != self.passwords.get(email, "valid-pass"):
                raise AccountError("Email hoặc mật khẩu không đúng.", 401)
            if email in self.pending_signups:
                raise AccountError("Hãy xác nhận email trước khi đăng nhập.", 403, code="email_not_confirmed")
            user_id = email.split("@")[0]
            return {"access_token": f"private-test-token:{email}", "user": {
                "id": user_id, "email": email, "user_metadata": {"name": self.names.get(user_id, "Người kiểm thử")},
            }}
        if route.path == "/auth/v1/user":
            assert method == "PUT" and token.startswith("private-test-token:")
            email = token.split(":", 1)[1]
            assert payload["current_password"] == self.passwords.get(email, "valid-pass")
            self.passwords[email] = payload["password"]
            return {}
        if route.path.startswith("/auth/v1/admin/users/"):
            assert method == "PUT" and database
            self.names[route.path.rsplit("/", 1)[1]] = payload["user_metadata"]["name"]
            return {}
        assert database
        query = parse_qs(route.query)
        owner = payload["user_id"] if method == "POST" else query["user_id"][0][3:]
        if route.path == "/rest/v1/telegram_links":
            if method == "POST":
                if owner in self.links or any(row["chat_id"] == payload["chat_id"] for row in self.links.values()):
                    raise AccountError("Đã có liên kết", 409)
                self.links[owner] = payload.copy()
            elif method == "DELETE":
                self.links.pop(owner, None)
            else:
                return [self.links[owner].copy()] if owner in self.links else []
        elif route.path == "/rest/v1/camera_settings":
            if method == "POST":
                assert prefer == "resolution=merge-duplicates"
                self.settings[owner] = payload.copy()
            else:
                return [self.settings[owner].copy()] if owner in self.settings else []
        else:
            events = self.events.setdefault(owner, {})
            if method == "POST":
                events[payload["id"]] = {"source": "camera", "photo_jpeg": None, **payload,
                                         "has_photo": payload.get("photo_jpeg") is not None}
            elif method == "PATCH":
                events[query["id"][0][3:]].update(payload)
            else:
                latest = sorted(events.values(), key=lambda row: (row["occurred_at"], row["id"]), reverse=True)
                if "id" in query:
                    latest = [row for row in latest if row["id"] == query["id"][0][3:]]
                if "and" in query:
                    gte, lt = query["and"][0][1:-1].split(",")
                    start = datetime.fromisoformat(gte.removeprefix("occurred_at.gte."))
                    end = datetime.fromisoformat(lt.removeprefix("occurred_at.lt."))
                    latest = [row for row in latest if start <= datetime.fromisoformat(row["occurred_at"]) < end]
                offset = int(query.get("offset", [0])[0])
                limit = int(query.get("limit", [len(latest)])[0])
                latest = latest[offset:offset + limit]
                return [{key: row[key] for key in query["select"][0].split(",")} for row in latest]

    def avatar(self, method, user_id, jpeg=None):
        if method == "POST":
            self.avatars[user_id] = jpeg
        elif method == "DELETE":
            self.avatars.pop(user_id, None)
        else:
            return self.avatars.get(user_id)
        return None


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.db = SupabaseFixture()
        self.links = TelegramLinks("1:test")
        self.alerts = AccountAlerts(self.db, self.links)
        with (patch("src.server.load_supabase", return_value=self.db),
              patch("src.server.load_telegram", return_value=self.links),
              patch("src.server.AccountAlerts", return_value=self.alerts)):
            self.app = create_app(start_sweeper=False)
        self.alice, self.bob, self.guest = [self.app.test_client() for _ in range(3)]

    def login(self, client, name, password="valid-pass"):
        return client.post("/api/account/login", json={"email": f"{name}@example.com", "password": password})

    def test_camera_settings_are_optional_validated_and_private(self):
        url = "/api/account/camera-settings"
        self.assertEqual(self.guest.get(url).status_code, 401)
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")
        default = {"enabled": False, "seconds": 60}
        self.assertEqual(self.alice.get(url).json, default)
        for seconds in (9, 3601, 60.5, True, "60"):
            self.assertEqual(self.alice.post(url, json={"enabled": True, "seconds": seconds}).status_code, 400)
        self.assertEqual(self.alice.post(url, json={"enabled": "false", "seconds": 60}).status_code, 400)
        self.assertEqual(self.alice.post(url, json={"enabled": True, "seconds": 30}).status_code, 200)
        self.assertEqual(self.bob.get(url).json, default)
        self.login(self.guest, "alice")
        self.assertEqual(self.guest.get(url).json, {**default, "enabled": True, "seconds": 30})
        self.assertEqual(self.alice.post(url, json={"enabled": False, "seconds": 30}).status_code, 200)
        self.assertEqual(self.guest.get(url).json, {**default, "seconds": 30})

    def test_absence_timer_restarts_after_unclear_frames_or_capture_gap(self):
        monitor = Session(None, None, "login", "alice", absence_after=10)
        for now in range(12):
            self.assertIsNone(monitor.observe_absence(NO_PERSON, now))
        monitor.observe_absence(FALL_WARNING, 12)
        for now in range(13, 19):
            self.assertIsNone(monitor.observe_absence(NO_PERSON, now))
        monitor.observe_absence(UNCLEAR, 19)
        for now in range(20, 28):
            self.assertIsNone(monitor.observe_absence(NO_PERSON, now))
        for now in range(31, 41):
            self.assertIsNone(monitor.observe_absence(NO_PERSON, now))
        self.assertEqual(monitor.observe_absence(NO_PERSON, 41), 10)
        monitor.observe_absence(UNCLEAR, 42)
        for now in range(43, 55):
            self.assertIsNone(monitor.observe_absence(NO_PERSON, now))

    def test_camera_absence_sends_once_per_departure_and_keeps_fall_alert(self):
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")
        self.db.links["alice"] = {"chat_id": 111}
        token = self.alice.post("/api/session").json["token"]
        monitor = self.app.extensions["sessions"].find(token)
        self.assertIsNone(monitor.absence_after)
        url = "/api/account/camera-settings"
        self.bob.post(url, json={"enabled": True, "seconds": 30})
        self.assertIsNone(monitor.absence_after)
        with io.BytesIO() as buffer:
            Image.new("RGB", (20, 20)).save(buffer, "JPEG")
            jpeg = buffer.getvalue()
        with io.BytesIO() as buffer:
            Image.new("RGB", (28, 20)).save(buffer, "JPEG")
            absence_jpeg = buffer.getvalue()
        start = monitor.last_seen

        def send(stamp, state, *, alarm=False, frame=jpeg):
            clock = SimpleNamespace(monotonic=lambda: start + stamp)
            with (patch("src.server.time", clock),
                  patch("src.server.web_result", return_value={"t": stamp, "state": state, "alarm": alarm})):
                result = self.alice.post(f"/api/frame/{token}", data=frame, content_type="image/jpeg",
                                         headers={"X-Frame-Time": str(stamp)})
            self.assertEqual(result.status_code, 200)
            return result.json.get("absence_alarm")

        with patch("src.server.Pose"), patch("src.accounts.telegram.api") as bot:
            send(0, FALL_WARNING, alarm=True)
            for stamp in range(1, 12):
                self.assertIsNone(send(stamp, NO_PERSON))
            self.alice.post(url, json={"enabled": True, "seconds": 10})
            for stamp in range(12, 22):
                self.assertIsNone(send(stamp, NO_PERSON))
            self.assertEqual(send(22, NO_PERSON, frame=absence_jpeg), 10)
            self.assertIsNone(send(23, NO_PERSON))
            self.assertIsNone(send(24, FALL_WARNING))
            for stamp in range(25, 35):
                self.assertIsNone(send(stamp, NO_PERSON))
            self.assertEqual(send(35, NO_PERSON, frame=absence_jpeg), 10)
            self.alerts.pending.join()

        self.assertEqual([call.args[1] for call in bot.call_args_list], ["sendPhoto"] * 3)
        photos = []
        for call in bot.call_args_list[1:]:
            self.assertEqual(call.args[2]["chat_id"], 111)
            self.assertIn("Không thấy người trong khung hình ít nhất 10 giây", call.args[2]["caption"])
            photo = call.kwargs["photo"]
            with Image.open(io.BytesIO(photo)) as image:
                self.assertEqual((image.format, image.size), ("JPEG", (28, 20)))
            photos.append(photo)
        events = self.alice.get("/api/account/history").json["events"]
        self.assertCountEqual([(row["source"], row["has_photo"], row["telegram_status"]) for row in events],
                              [("camera", True, "sent"), ("camera_absence", True, "sent"), ("camera_absence", True, "sent")])
        history_photos = []
        for row in events:
            if row["source"] == "camera_absence":
                url = f'/api/account/history/{row["id"]}/photo'
                response = self.alice.get(url)
                self.assertEqual(response.mimetype, "image/jpeg")
                history_photos.append(response.data)
                self.assertEqual(self.bob.get(url).status_code, 404)
        self.assertCountEqual(history_photos, photos)
        self.assertEqual(self.bob.get("/api/account/history").json["events"], [])

    def test_history_filters_vietnam_day_before_paginating(self):
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")

        def store(owner, event_id, timestamp):
            self.db.user_rows("POST", "fall_alerts", owner, payload={
                "id": event_id, "occurred_at": timestamp, "telegram_status": "sent",
            })

        store("alice", "day-before", "2026-11-25T16:59:59+00:00")
        store("alice", "start", "2026-11-25T17:00:00+00:00")
        for second in range(50):
            store("alice", f"alert-{second}", f"2026-11-26T03:00:{second:02d}+00:00")
        store("alice", "day-after", "2026-11-26T17:00:00+00:00")
        store("bob", "private", "2026-11-26T10:00:00+00:00")
        url = "/api/account/history?date=2026-11-26"
        first = self.alice.get(url).json
        self.assertEqual(len(first["events"]), 50)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["events"][0]["id"], "alert-49")
        second = self.alice.get(url + "&page=2").json
        self.assertEqual([event["id"] for event in second["events"]], ["start"])
        self.assertFalse(second["has_more"])
        for query in ("date=2026-02-29", "date=0001-01-01", "page=0", "page=100000"):
            self.assertEqual(self.alice.get(f"/api/account/history?{query}").status_code, 400)

    def test_authentication_and_web_gate(self):
        self.assertEqual(self.guest.get("/api/account").json, {"user": None, "configured": True})
        for route in ("/api/status", "/api/account/history", "/api/account/telegram", "/api/videos"):
            self.assertEqual(self.guest.get(route).status_code, 401)
        self.assertEqual(self.guest.post("/api/session").status_code, 401)
        self.assertEqual(self.guest.post("/api/account/register", json={
            "email": "pending@example.com", "password": "valid-pass", "name": "Pending",
        }).status_code, 202)
        self.assertEqual(self.login(self.alice, "alice", "bad-pass").status_code, 401)
        response = self.login(self.alice, "alice")
        self.assertEqual(response.json["user"]["email"], "alice@example.com")
        self.assertNotIn("private-test-token", str(response.json))
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", response.headers["Set-Cookie"])
        self.assertEqual(self.alice.get("/api/status").status_code, 200)
        self.assertEqual(self.alice.post("/api/account/logout", headers={"Origin": "https://elsewhere.test"}).status_code, 403)
        self.assertEqual(self.alice.post("/api/account/logout").status_code, 204)
        self.assertEqual(self.alice.get("/api/account/history").status_code, 401)

    def test_signup_verification_resends_and_signs_in_once(self):
        prefix = "/api/account/"
        email = "new@example.com"
        self.assertEqual(self.guest.post(prefix + "register", json={
            "email": email, "password": "valid-pass", "name": "Người mới",
        }).json, {"confirmation_required": True})
        pending = self.login(self.guest, "new")
        self.assertEqual(pending.status_code, 403)
        self.assertEqual(pending.json["code"], "email_not_confirmed")

        def verify(token, **options):
            return self.guest.post(prefix + "verify-email", json={"email": email, "token": token}, **options)

        self.assertEqual(verify(123456).status_code, 400)
        self.assertEqual(verify("１２３４５６").status_code, 400)
        self.assertEqual(verify("12345").status_code, 400)
        self.assertEqual(verify("12345678901").status_code, 400)
        self.assertEqual(verify("012345", headers={"Origin": "https://elsewhere.test"}).status_code, 403)
        self.assertEqual(self.guest.post(prefix + "resend-email", json={"email": "bad"}).status_code, 400)
        self.assertEqual(self.guest.post(prefix + "resend-email", json={"email": email}).status_code, 204)
        self.assertEqual(verify("012345").status_code, 400)
        self.assertEqual(verify("065432").status_code, 400)
        self.assertIsNone(self.guest.get("/api/account").json["user"])
        accepted = verify("06543210")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json, {"user": {"id": "new", "email": email, "name": "Người mới"}})
        self.assertIn("HttpOnly", accepted.headers["Set-Cookie"])
        self.assertEqual(self.guest.get("/api/status").status_code, 200)
        self.assertEqual(verify("06543210").status_code, 400)

    def test_supabase_signup_reports_mail_failure_without_exposing_upstream_details(self):
        db = Supabase("test.supabase.co", "publishable", "secret")
        with patch("src.accounts.http.client.HTTPSConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 500
            response.read.return_value = json.dumps({
                "error_code": "unexpected_failure", "msg": "Error sending confirmation email: private SMTP detail",
            }).encode()
            with self.assertLogs("src.accounts", level="WARNING") as logged:
                with self.assertRaises(AccountError) as failure:
                    db.authenticate({"email": "new@example.com"}, True)
            self.assertEqual(failure.exception.status, 502)
            self.assertIn("gửi email xác nhận", str(failure.exception))
            self.assertIn("unexpected_failure", logged.output[0])
            self.assertNotIn("private SMTP detail", str(failure.exception) + logged.output[0])

            response.status = 403
            response.read.return_value = b'{"error_code":"otp_expired"}'
            with self.assertRaises(AccountError) as invalid:
                db.verify_signup("new@example.com", "065432")
            self.assertEqual(invalid.exception.status, 400)
            self.assertIn("không chấp nhận mã", str(invalid.exception))

    def test_confirmation_email_uses_supabase_retry_after(self):
        db = Supabase("test.supabase.co", "publishable", "secret")
        with patch("src.accounts.http.client.HTTPSConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 429
            response.read.return_value = json.dumps({
                "error_code": "over_email_send_rate_limit",
                "msg": "For security purposes, you can only request this after 12 seconds.",
            }).encode()
            with patch.object(self.db, "resend_signup", db.resend_signup):
                delayed = self.guest.post("/api/account/resend-email", json={"email": "new@example.com"})
            self.assertEqual(delayed.status_code, 429)
            self.assertEqual(delayed.headers["Retry-After"], "13")
            self.assertIn("13 giây", delayed.json["error"])

    def test_account_can_change_name_and_password_only_for_current_user(self):
        url = "/api/account/"
        self.assertEqual(self.guest.post(url + "password").status_code, 401)
        self.login(self.alice, "alice")
        self.assertEqual(self.alice.post(url + "profile", json={"name": "  "}).status_code, 400)
        updated = self.alice.post(url + "profile", json={"name": "  Minh  ", "user_id": "bob"})
        self.assertEqual(updated.json["user"]["name"], "Minh")
        self.assertEqual(self.login(self.bob, "bob").json["user"]["name"], "Người kiểm thử")
        payload = {"current_password": "wrong-old", "new_password": "new-valid-pass", "email": "bob@example.com"}
        self.assertEqual(self.alice.post(url + "password", json=payload).status_code, 400)
        payload["current_password"] = "valid-pass"
        self.assertEqual(self.alice.post(url + "password", json=payload,
                                         headers={"Origin": "https://elsewhere.test"}).status_code, 403)
        self.assertEqual(self.alice.post(url + "password", json=payload).status_code, 204)
        self.assertEqual(self.login(self.alice, "alice").status_code, 401)
        self.assertEqual(self.login(self.alice, "alice", "new-valid-pass").json["user"]["name"], "Minh")
        self.assertEqual(self.login(self.bob, "bob").status_code, 200)

    def test_avatar_is_normalized_private_and_removable(self):
        url = "/api/account/avatar"
        self.assertEqual(self.guest.get(url).status_code, 401)
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")
        self.assertEqual(self.alice.post(url, data=b"<svg/>", content_type="image/svg+xml").status_code, 415)
        self.assertEqual(self.alice.post(url, data=b"x" * (5 * 1024**2 + 1)).status_code, 413)
        png = io.BytesIO()
        Image.new("RGBA", (400, 160), "#248557").save(png, "PNG")
        response = self.alice.post(url, data=png.getvalue(), content_type="image/png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        with Image.open(io.BytesIO(response.data)) as photo:
            self.assertEqual((photo.format, photo.size), ("JPEG", (256, 256)))
        self.assertEqual(self.alice.get(url).data, response.data)
        self.assertEqual(self.bob.get(url).status_code, 204)
        self.assertEqual(self.bob.delete(url).status_code, 204)
        self.assertEqual(self.alice.get(url).data, response.data)
        self.assertEqual(self.alice.delete(url).status_code, 204)
        self.assertEqual(self.alice.get(url).status_code, 204)

    def test_first_avatar_write_creates_a_private_bucket(self):
        db = Supabase("test.supabase.co", "publishable", "secret")
        with patch.object(db, "storage_request", side_effect=[(400, {"error": "NoSuchBucket"}),
                                                               (200, {}), (200, {"public": False}),
                                                               (200, {})]) as storage:
            db.avatar("POST", "alice", b"stored-jpeg")
        self.assertEqual(storage.call_args_list, [
            call("GET", "bucket/cameraai-avatars"),
            call("POST", "bucket", {"id": "cameraai-avatars", "name": "cameraai-avatars", "public": False,
                                    "allowed_mime_types": ["image/jpeg"], "file_size_limit": 256 * 1024}),
            call("GET", "bucket/cameraai-avatars"),
            call("POST", "object/cameraai-avatars/alice.jpg", b"stored-jpeg"),
        ])
        with patch.object(db, "storage_request", return_value=(200, {"public": True})) as storage:
            with self.assertRaises(AccountError):
                db.avatar("POST", "alice", b"stored-jpeg")
        storage.assert_called_once_with("GET", "bucket/cameraai-avatars")

    def test_two_telegram_links_and_private_history(self):
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")
        prefix = "/api/account/telegram/"
        received = []
        outgoing = []

        def fake_bot(token, method, body, *, photo=None):
            if method == "getMe":
                return {"username": "CameraTestBot"}
            if method == "getUpdates":
                return [update for update in received if update["update_id"] >= body["offset"]]
            self.assertIn(method, ("sendMessage", "sendPhoto"))
            outgoing.append((method, body, photo))

        def start(client):
            url = client.post(prefix + "start").json["url"]
            return parse_qs(urlsplit(url).query)["start"][0]

        def receive(code, chat_id, chat_type="private"):
            received.append({"update_id": len(received) + 1, "message": {"text": f"/start {code}",
                             "chat": {"id": chat_id, "type": chat_type, "username": f"chat_{chat_id}"}}})

        with patch("src.accounts.telegram.api", side_effect=fake_bot):
            a, b = start(self.alice), start(self.bob)
            self.assertNotEqual(a, b)
            receive(a, 111, "group")
            receive(b, 222)
            self.assertFalse(self.alice.post(prefix + "check").json["found"])
            self.assertEqual(self.alice.post(prefix + "confirm").status_code, 409)
            self.assertEqual(self.bob.post(prefix + "check").json, {"found": True, "label": "@chat_222"})
            self.assertEqual(self.bob.post(prefix + "confirm").status_code, 200)
            self.assertEqual(self.bob.post(prefix + "confirm").status_code, 409)
            receive(a, 222)
            self.assertTrue(self.alice.post(prefix + "check").json["found"])
            self.assertEqual(self.alice.post(prefix + "confirm").status_code, 409)
            receive(start(self.alice), 111)
            self.assertTrue(self.alice.post(prefix + "check").json["found"])
            self.assertEqual(self.alice.post(prefix + "confirm").status_code, 200)
            self.assertEqual(self.alice.post(prefix + "test").status_code, 204)
            self.assertEqual(self.alice.get(prefix.rstrip("/")).json["label"], "@chat_111")

            alerts = AccountAlerts(self.db, self.links)
            with io.BytesIO() as buffer:
                Image.new("RGB", (20, 20), "red").save(buffer, "JPEG")
                camera_photo = buffer.getvalue()
            alerts.enqueue("alice", photo=camera_photo)
            alerts.enqueue("bob")
            alerts.pending.join()
            self.assertEqual([(method, body["chat_id"]) for method, body, _ in outgoing],
                             [("sendMessage", 111), ("sendPhoto", 111), ("sendMessage", 222)])
            self.assertIn("Nghi té ngã qua camera", outgoing[1][1]["caption"])
            self.assertEqual(outgoing[1][2], camera_photo)
            alice = self.alice.get("/api/account/history?user_id=bob").json["events"]
            bob = self.bob.get("/api/account/history").json["events"]
            self.assertEqual(alice[0]["telegram_status"], "sent")
            self.assertEqual(alice[0]["source"], "camera")
            self.assertTrue(alice[0]["has_photo"])
            url = f'/api/account/history/{alice[0]["id"]}/photo'
            self.assertEqual(self.alice.get(url).data, camera_photo)
            self.assertEqual(self.bob.get(url).status_code, 404)
            self.assertFalse(bob[0]["has_photo"])
            self.assertNotEqual(alice[0]["id"], bob[0]["id"])
            self.assertEqual(self.alice.post(prefix + "unlink").status_code, 204)
            alerts.enqueue("alice")
            alerts.pending.join()
            self.assertEqual(len(outgoing), 3)
            self.assertEqual(self.alice.get("/api/account/history").json["events"][0]["telegram_status"], "unlinked")

    def test_expired_link_and_error_delivery(self):
        self.login(self.alice, "alice")
        with patch("src.accounts.telegram.api", return_value={"username": "CameraTestBot"}):
            self.alice.post("/api/account/telegram/start")
        for pending in self.links.pending.values():
            pending["expires"] = 0
        self.assertEqual(self.alice.post("/api/account/telegram/check").status_code, 409)
        self.db.links["alice"] = {"chat_id": 111}
        with patch("src.accounts.telegram.api", side_effect=TelegramError("Telegram không phản hồi.")):
            AccountAlerts(self.db, self.links).record("alice", datetime.now(timezone.utc))
        self.assertEqual(self.alice.get("/api/account/history").json["events"][0]["telegram_status"], "error")

    def test_uploaded_fall_sends_jpeg_only_to_linked_account(self):
        if not safe("data/manifests/split.csv").is_file() or not load_model()[0]:
            self.skipTest("Thiếu split hoặc classifier để thử video thật")
        clips = {clip["video_id"]: safe(clip["relative_path"]) for clip in load_split()}
        fall = clips.get("Trip_n_Fall/Person27")
        walking = clips.get("Walking/Person27")
        if not fall or not walking or not fall.is_file() or not walking.is_file():
            self.skipTest("Thiếu clip test té ngã hoặc đi bộ")
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")
        self.db.links["alice"] = {"chat_id": 111}
        self.db.links["bob"] = {"chat_id": 222}

        def upload(client, clip):
            response = client.post("/api/analyze-video", data=clip.read_bytes(), content_type="application/octet-stream")
            self.assertEqual(response.status_code, 200)
            return response.json

        with patch("src.telegram.http.client.HTTPSConnection") as transport:
            connection = transport.return_value
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = b'{"ok":true,"result":{}}'
            detected = upload(self.alice, fall)
            self.assertTrue(detected["alarms"])
            self.assertEqual(detected["telegram_status"], "sent")
            self.assertEqual(detected["history_status"], "saved")
            alice_history = self.alice.get("/api/account/history").json["events"]
            self.assertEqual(len(alice_history), 1)
            self.assertEqual((alice_history[0]["source"], alice_history[0]["telegram_status"]), ("video_test", "sent"))
            self.assertTrue(alice_history[0]["has_photo"])
            self.assertNotIn("photo_jpeg", alice_history[0])
            self.assertEqual(self.bob.get("/api/account/history").json["events"], [])
            connection.request.assert_called_once()
            method, path, body, headers = connection.request.call_args.args
            self.assertEqual((method, path), ("POST", "/bot1:test/sendPhoto"))
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {headers['Content-Type']}\r\n\r\n".encode() + body)
            fields = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
            self.assertEqual(fields["chat_id"].get_payload(decode=True), b"111")
            caption = fields["caption"].get_payload(decode=True).decode()
            self.assertIn("[THỬ VIDEO]", caption)
            self.assertIn("00:06.52", caption)
            self.assertEqual(fields["photo"].get_content_type(), "image/jpeg")
            jpeg = fields["photo"].get_payload(decode=True)
            with Image.open(io.BytesIO(jpeg)) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertLessEqual(max(image.size), 640)
                image.verify()
            photo_url = f'/api/account/history/{alice_history[0]["id"]}/photo'
            photo = self.alice.get(photo_url)
            self.assertEqual((photo.status_code, photo.mimetype, photo.data), (200, "image/jpeg", jpeg))
            self.assertEqual(photo.headers["Cache-Control"], "no-store")
            self.assertEqual(self.bob.get(photo_url).status_code, 404)
            self.assertEqual(self.guest.get(photo_url).status_code, 401)
            self.assertFalse(upload(self.alice, walking)["alarms"])
            self.assertEqual(self.alice.get("/api/account/history").json["events"], alice_history)
            self.db.links.pop("alice")
            self.assertEqual(upload(self.alice, fall)["telegram_status"], "unlinked")
            connection.request.assert_called_once()

            connection.request.side_effect = OSError("Simulated Telegram timeout")
            failed = upload(self.bob, fall)
            self.assertEqual(failed["alarms"], detected["alarms"])
            self.assertEqual(failed["telegram_status"], "error")
            self.assertEqual(failed["history_status"], "saved")
            self.assertEqual(connection.request.call_count, 2)
        alice = self.alice.get("/api/account/history").json["events"]
        bob = self.bob.get("/api/account/history").json["events"]
        self.assertEqual([(e["source"], e["telegram_status"]) for e in alice],
                         [("video_test", "unlinked"), ("video_test", "sent")])
        self.assertEqual([(e["source"], e["telegram_status"]) for e in bob], [("video_test", "error")])
        self.assertTrue(alice[0]["has_photo"])
        self.assertTrue(bob[0]["has_photo"])

    def test_history_write_errors_do_not_block_or_mask_telegram(self):
        self.db.links["alice"] = {"chat_id": 111}
        original = self.db.user_rows
        alerts = AccountAlerts(self.db, self.links)
        for failing_method, expected in (("POST", "error"), ("PATCH", "status_error")):
            with self.subTest(failing_method=failing_method):
                def user_rows(method, table, user_id, **kwargs):
                    if method == failing_method and table == "fall_alerts":
                        raise AccountError("Supabase history write failed")
                    return original(method, table, user_id, **kwargs)

                with (patch.object(self.db, "user_rows", side_effect=user_rows),
                      patch("src.telegram.api") as bot):
                    status = alerts.record("alice", datetime.now(timezone.utc), video_time=0, photo=b"test JPEG")
                    self.assertEqual(status, ("sent", expected))
                    bot.assert_called_once()
                    self.assertEqual(bot.call_args.args[1], "sendPhoto")
                    self.assertEqual(bot.call_args.args[2]["chat_id"], 111)
                    self.assertEqual(bot.call_args.kwargs["photo"], b"test JPEG")

    def test_rejected_or_missing_photo_falls_back_to_test_text(self):
        self.db.links["alice"] = {"chat_id": 111}
        alerts = AccountAlerts(self.db, self.links)
        for photo, methods in ((b"test JPEG", ["sendPhoto", "sendMessage"]), (None, ["sendMessage"])):
            def transport(token, method, payload, **kwargs):
                if method == "sendPhoto":
                    raise TelegramError("Rejected photo", status=400)

            with self.subTest(photo=photo), patch("src.telegram.api", side_effect=transport) as bot:
                status = alerts.record("alice", datetime.now(timezone.utc), video_time=0, photo=photo)
                self.assertEqual(status, ("sent_text", "saved"))
                self.assertEqual([call.args[1] for call in bot.call_args_list], methods)
                self.assertEqual(bot.call_args.args[2]["chat_id"], 111)
                self.assertIn("[THỬ VIDEO]", bot.call_args.args[2]["text"])
