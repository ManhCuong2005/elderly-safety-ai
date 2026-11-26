import io
import unittest
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from src.accounts import AccountAlerts, AccountError, Supabase, TelegramLinks
from src.server import create_app
from src.storage import safe
from src.telegram import TelegramError
from src.train import load_model, load_split


class SupabaseFixture(Supabase):
    def __init__(self):
        super().__init__("test.supabase.co", "publishable", "secret")
        self.links = {}
        self.events = {}

    def request(self, method, path, payload=None, *, database=False):
        route = urlsplit(path)
        if route.path == "/auth/v1/signup":
            return {"id": "pending-confirmation"}
        if route.path == "/auth/v1/token":
            if payload["password"] != "valid-pass":
                raise AccountError("Email hoặc mật khẩu không đúng.", 401)
            email = payload["email"]
            return {"access_token": "private-test-token", "user": {
                "id": email.split("@")[0], "email": email, "user_metadata": {"name": "Người kiểm thử"},
            }}
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


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.db = SupabaseFixture()
        self.links = TelegramLinks("1:test")
        with (patch("src.server.load_supabase", return_value=self.db),
              patch("src.server.load_telegram", return_value=self.links)):
            self.app = create_app(start_sweeper=False)
        self.alice, self.bob, self.guest = [self.app.test_client() for _ in range(3)]

    def login(self, client, name, password="valid-pass"):
        return client.post("/api/account/login", json={"email": f"{name}@example.com", "password": password})

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
            "email": "alice@example.com", "password": "valid-pass", "name": "Alice",
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

    def test_two_telegram_links_and_private_history(self):
        self.login(self.alice, "alice")
        self.login(self.bob, "bob")
        prefix = "/api/account/telegram/"
        received = []
        outgoing = []

        def fake_bot(token, method, body):
            if method == "getMe":
                return {"username": "CameraTestBot"}
            if method == "getUpdates":
                return [update for update in received if update["update_id"] >= body["offset"]]
            self.assertEqual(method, "sendMessage")
            outgoing.append(body)

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
            alerts.enqueue("alice")
            alerts.enqueue("bob")
            alerts.pending.join()
            self.assertEqual([message["chat_id"] for message in outgoing], [111, 111, 222])
            self.assertIn("Nghi té ngã", outgoing[1]["text"])
            alice = self.alice.get("/api/account/history?user_id=bob").json["events"]
            bob = self.bob.get("/api/account/history").json["events"]
            self.assertEqual(alice[0]["telegram_status"], "sent")
            self.assertEqual(alice[0]["source"], "camera")
            self.assertFalse(alice[0]["has_photo"])
            self.assertEqual(self.alice.get(f'/api/account/history/{alice[0]["id"]}/photo').status_code, 404)
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
        alice = self.alice.get("/api/account/history").json["events"]
        bob = self.bob.get("/api/account/history").json["events"]
        self.assertEqual([(e["source"], e["telegram_status"]) for e in alice],
                         [("video_test", "unlinked"), ("video_test", "sent")])
        self.assertEqual([(e["source"], e["telegram_status"]) for e in bob], [("video_test", "error")])
        self.assertTrue(alice[0]["has_photo"])
        self.assertTrue(bob[0]["has_photo"])

    def test_skips_alert_delivery_when_history_insert_fails(self):
        self.db.links["alice"] = {"chat_id": 111}
        with (patch.object(self.db, "user_rows", side_effect=AccountError("Supabase is offline")),
              patch("src.telegram.api") as bot):
            with self.assertRaises(AccountError):
                AccountAlerts(self.db, self.links).record("alice", datetime.now(timezone.utc),
                                                         video_time=0, photo=b"test JPEG")
            bot.assert_not_called()
