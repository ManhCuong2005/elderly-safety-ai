import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from src.accounts import AccountAlerts, AccountError, Supabase, TelegramLinks
from src.server import create_app
from src.telegram import TelegramError


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
                events[payload["id"]] = payload.copy()
            elif method == "PATCH":
                events[query["id"][0][3:]].update(payload)
            else:
                return [{key: row[key] for key in query["select"][0].split(",")} for row in events.values()]


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
            self.assertNotEqual(alice[0]["id"], bob[0]["id"])
            self.assertEqual(self.alice.post(prefix + "unlink").status_code, 204)
            alerts.enqueue("alice")
            alerts.pending.join()
            self.assertEqual(len(outgoing), 3)
            self.assertEqual(self.alice.get("/api/account/history").json["events"][-1]["telegram_status"], "unlinked")

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
