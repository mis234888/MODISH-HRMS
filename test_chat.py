"""Portable chat regression checks. No .env, production DB, or real push calls.

Run: python -m unittest test_chat -v
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from flask import Flask
from flask_cors import CORS

from chat_backend import init_chat


class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ekkaa-chat-test-")
        self.directory = Path(self.temp.name)
        self.rows = [
            {"id": "1", "email": "alice@example.test", "full_name": "Alice", "status": "Active", "password_hash": "fixture"},
            {"id": "2", "email": "bob@example.test", "full_name": "Bob", "status": "Active", "password_hash": "fixture"},
            {"id": "3", "email": "gone@example.test", "full_name": "Gone", "status": "Exited"},
        ]
        self.host = SimpleNamespace(
            db_list=lambda table: [dict(row) for row in self.rows], supabase=None,
            ADMIN_EMAILS={"boss@example.test", "gone@example.test"}, ApiError=ApiError,
            ADMIN_PASSWORD="test-only-administrator-password",
        )
        self.app = self.make_app()
        self.chat = self.app.extensions["chat"]
        self.client = self.app.test_client()

    def make_app(self):
        app = Flask("chat_test", root_path=str(self.directory), static_folder=str(self.directory / "static"))
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key-not-for-deployment",
                          CHAT_DATA_DIR=str(self.directory / "chat"), CHAT_ENCRYPTION_KEY=None,
                          CHAT_VAPID_PUBLIC_KEY=None, CHAT_VAPID_PRIVATE_KEY=None, CHAT_VAPID_SUBJECT=None)
        CORS(app)
        init_chat(app, self.host)
        return app

    def tearDown(self):
        if self.chat._executor:
            self.chat._executor.shutdown(wait=True)
        self.temp.cleanup()

    def login(self, email="alice@example.test", employee="1", role="Employee"):
        with self.client.session_transaction() as session:
            session.clear()
            session["user"] = {"email": email, "employee_id": employee, "role": role}
        response = self.client.get("/api/chat/bootstrap")
        self.assertEqual(response.status_code, 200, response.json)
        self.token = response.json["csrf_token"]
        return response.json

    def write(self, path, body, method="POST"):
        return self.client.open(path, method=method, json=body, headers={"X-Chat-CSRF": self.token})

    def send(self, body="Private fixture message", peer="e:2", client_id=None):
        return self.write("/api/chat/messages/" + peer, {"body": body, "client_id": client_id or str(uuid.uuid4())})

    def test_identity_and_no_admin_employee_fallback(self):
        self.assertEqual(self.client.get("/api/chat/bootstrap").status_code, 401)
        payload = self.login()
        self.assertEqual(payload["me"]["id"], "e:1")
        self.assertEqual({p["id"] for p in payload["contacts"]}, {"e:2", "a:boss@example.test"})
        self.rows[0]["status"] = "Exited"
        self.assertEqual(self.client.get("/api/chat/events").status_code, 403)
        self.rows[0]["status"] = "Active"
        with self.client.session_transaction() as session:
            session["user"] = {"email": "alice@example.test", "employee_id": "2", "role": "Employee"}
        self.assertEqual(self.client.get("/api/chat/bootstrap").status_code, 403)
        payload = self.login("boss@example.test", None, "HR Admin")
        self.assertEqual(payload["me"]["id"], "a:boss@example.test")

    def test_csrf_origin_and_no_cors_even_on_errors(self):
        self.login()
        body = {"body": "Hello", "client_id": str(uuid.uuid4())}
        self.assertEqual(self.client.post("/api/chat/messages/e:2", json=body).status_code, 403)
        for method in ("GET", "OPTIONS"):
            response = self.client.open("/api/chat/bootstrap", method=method, headers={"Origin": "https://other.test"})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertFalse(any(k.lower().startswith("access-control-") for k in response.headers.keys()))
        response = self.client.post("/api/chat/messages/e:2", json=body,
                                    headers={"Origin": "http://localhost", "X-Chat-CSRF": self.token})
        self.assertEqual(response.status_code, 201)

    def test_saved_messages_idempotency_and_third_party_privacy(self):
        self.login()
        client_id = str(uuid.uuid4())
        first = self.send(client_id=client_id)
        self.assertEqual(first.status_code, 201)
        duplicate = self.send(client_id=client_id)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json, first.json)
        self.assertEqual(self.send("Different", client_id=client_id).status_code, 409)
        self.assertEqual(self.send(peer="a:boss@example.test", client_id=client_id).status_code, 409)
        self.assertEqual(self.make_app().test_client().get("/api/chat/events").status_code, 401)
        self.login("bob@example.test", "2")
        self.assertEqual(self.client.get("/api/chat/messages/e:1").json["messages"], [first.json["message"]])
        self.login("boss@example.test", None, "HR Admin")
        self.assertEqual(self.client.get("/api/chat/messages/e:1").json["messages"], [])
        self.assertEqual(self.client.get("/api/chat/events").json["events"], [])
        self.assertEqual(self.client.get("/api/chat/conversations").json["unread_count"], 0)
        self.assertEqual(self.write("/api/chat/messages/e:1/read", {"through_id": first.json["message"]["id"]}).status_code, 404)

    def test_persistence_across_storage_instances_and_encryption(self):
        self.login()
        self.send("unique-plaintext-marker")
        fresh = self.make_app().extensions["chat"]
        rows = fresh.storage().messages("e:2", "e:1", None)
        self.assertEqual(fresh.message(rows[0])["body"], "unique-plaintext-marker")
        for path in (self.directory / "chat").iterdir():
            self.assertNotIn(b"unique-plaintext-marker", path.read_bytes())
        key = self.directory / "chat" / "chat.key"
        self.assertEqual(len(key.read_bytes()), 44)
        if os.name != "nt":
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)

    def test_bounded_read_receipts(self):
        self.login()
        one = self.send("One").json["message"]["id"]
        two = self.send("Two").json["message"]["id"]
        self.assertEqual(self.write("/api/chat/messages/e:2/read", {"through_id": two}).status_code, 404)
        self.assertEqual(self.login("bob@example.test", "2")["unread_count"], 2)
        self.assertEqual(self.write("/api/chat/messages/e:1/read", {"through_id": two + 1}).status_code, 404)
        self.assertEqual(self.write("/api/chat/messages/e:1/read", {"through_id": one}).status_code, 200)
        rows = self.client.get("/api/chat/messages/e:1").json["messages"]
        self.assertIsNotNone(rows[0]["read_at"])
        self.assertIsNone(rows[1]["read_at"])
        self.assertEqual(self.client.get("/api/chat/conversations").json["unread_count"], 1)

    def test_pagination_and_recipient_scoped_catchup(self):
        self.login()
        with self.chat.storage().connection(write=True) as db:
            for i in range(125):
                db.execute("INSERT INTO chat_messages(sender_id,recipient_id,client_id,body_ciphertext,body_digest,created_at) VALUES(?,?,?,?,?,?)",
                           ("e:2", "e:1", str(uuid.uuid4()), self.chat.encrypt(str(i)), "a" * 64, "2020-01-01T00:00:00+00:00"))
        latest = self.client.get("/api/chat/messages/e:2").json
        self.assertEqual([m["id"] for m in latest["messages"]], list(range(76, 126)))
        self.assertTrue(latest["has_more"])
        middle = self.client.get("/api/chat/messages/e:2?before=76").json
        self.assertEqual([m["id"] for m in middle["messages"]], list(range(26, 76)))
        tail = self.client.get("/api/chat/messages/e:2?before=26").json
        self.assertEqual(len(tail["messages"]), 25)
        self.assertFalse(tail["has_more"])
        events = self.client.get("/api/chat/events?after=0").json
        self.assertEqual((len(events["events"]), events["cursor"], events["has_more"]), (100, 100, True))
        tail = self.client.get("/api/chat/events?after=100").json
        self.assertEqual((len(tail["events"]), tail["cursor"], tail["has_more"]), (25, 125, False))
        self.login("boss@example.test", None, "HR Admin")
        self.assertEqual(self.client.get("/api/chat/events").json["events"], [])

    def test_persistent_rate_limit_and_concurrent_retries(self):
        self.login()
        first_id = str(uuid.uuid4())
        for i in range(30):
            self.assertEqual(self.send(client_id=first_id if i == 0 else None).status_code, 201)
        self.assertEqual(self.send(client_id=first_id).status_code, 200)
        self.assertEqual(self.send().status_code, 429)
        store = self.make_app().extensions["chat"].storage()
        self.assertEqual(store.send("e:1", "e:2", str(uuid.uuid4()), self.chat.encrypt("X"), "a" * 64)[0], "rate_limited")
        client_id = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: store.send("e:2", "e:1", client_id, self.chat.encrypt("X"), "a" * 64), range(8)))
        self.assertEqual(sum(status == "created" for status, _ in results), 1)
        self.assertEqual(len({row["id"] for _, row in results}), 1)

    def subscription(self, suffix="one"):
        public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return {"endpoint": "https://fcm.googleapis.com/fcm/send/" + suffix, "expirationTime": None,
                "keys": {"p256dh": base64.urlsafe_b64encode(public).decode().rstrip("="),
                         "auth": base64.urlsafe_b64encode(b"0123456789abcdef").decode().rstrip("=")}}

    def test_push_ssrf_validation_encryption_and_account_scoped_delete(self):
        self.login()
        subscription = self.subscription()
        for endpoint in ("http://fcm.googleapis.com/x", "https://localhost/x", "https://fcm.googleapis.com.evil.test/x",
                         "https://user@fcm.googleapis.com/x", "https://fcm.googleapis.com:444/x", "https://fcm.googleapis.com/x#f"):
            self.assertEqual(self.write("/api/chat/push-subscriptions", {"subscription": dict(subscription, endpoint=endpoint)}).status_code, 400)
        self.assertEqual(self.write("/api/chat/push-subscriptions", {"subscription": subscription}).status_code, 200)
        row = self.chat.storage().subscriptions("e:1")[0]
        self.assertFalse(row["preview"])
        self.assertNotIn(subscription["endpoint"], row["subscription_ciphertext"])
        self.login("bob@example.test", "2")
        self.assertEqual(self.write("/api/chat/push-subscriptions", {"endpoint": subscription["endpoint"]}, "DELETE").status_code, 200)
        self.assertEqual(len(self.chat.storage().subscriptions("e:1")), 1)

    def test_mocked_push_preview_cleanup_and_message_survives_push_failure(self):
        from pywebpush import WebPushException
        self.login()
        subscription = self.subscription()
        self.write("/api/chat/push-subscriptions", {"subscription": subscription})
        message = {"id": 1, "body": "Preview " * 30, "sender_id": "e:2", "recipient_id": "e:1"}
        self.app.config.update(CHAT_VAPID_PUBLIC_KEY="synthetic", CHAT_VAPID_PRIVATE_KEY="synthetic",
                               CHAT_VAPID_SUBJECT="mailto:admin@example.test")
        def invoke():
            self.chat._push_slots.acquire()
            self.chat._push(message)
        with patch("pywebpush.webpush") as push:
            invoke()
            self.assertEqual(json.loads(push.call_args.kwargs["data"])["body"], "You have a new message.")
            self.assertEqual(push.call_args.kwargs["timeout"], 3)
            self.write("/api/chat/push-subscriptions", {"subscription": subscription, "preview": True})
            invoke()
            self.assertEqual(len(json.loads(push.call_args.kwargs["data"])["body"]), 120)
        with patch("pywebpush.webpush", side_effect=WebPushException("fixture", response=SimpleNamespace(status_code=410))):
            invoke()
        self.assertEqual(self.chat.storage().subscriptions("e:1"), [])
        with patch.object(self.chat, "queue_push", side_effect=RuntimeError("fixture failure")):
            self.assertEqual(self.send().status_code, 201)
        self.assertEqual(len(self.client.get("/api/chat/messages/e:2").json["messages"]), 1)

    def test_invalid_requests_cannot_spoof_sender(self):
        self.login()
        for query in ("after=-1", "after=1.2", "after=9007199254740992", "after=1&after=2"):
            self.assertEqual(self.client.get("/api/chat/events?" + query).status_code, 400)
        for body in ("", " ", "X" * 4001, "\ud800"):
            self.assertEqual(self.send(body).status_code, 400)
        self.assertEqual(self.write("/api/chat/messages/e:2", {"body": "X", "client_id": str(uuid.uuid4()), "sender_id": "e:2"}).status_code, 400)
        self.assertEqual(self.write("/api/chat/messages/e:2/read", {"through_id": True}).status_code, 400)
        self.assertEqual(self.send(peer="e:1").status_code, 404)
        for raw in ("[]", "null", '{"body":"X","body":"Y","client_id":"X"}'):
            self.assertEqual(self.client.post("/api/chat/messages/e:2", data=raw, content_type="application/json",
                                             headers={"X-Chat-CSRF": self.token}).status_code, 400)
        self.assertEqual(self.client.post("/api/chat/messages/e:2", data="X" * 32769, content_type="application/json",
                                         headers={"X-Chat-CSRF": self.token}).status_code, 413)

    def test_production_fails_closed_without_keys_or_individual_password(self):
        self.host.supabase = SimpleNamespace(supabase_key="sb_secret_synthetic")
        self.host.supabase_key_source = "SUPABASE_SERVICE_KEY"
        with self.client.session_transaction() as session:
            session["user"] = {"email": "alice@example.test", "employee_id": "1", "role": "Employee"}
        response = self.client.get("/api/chat/bootstrap")
        self.assertEqual(response.status_code, 503)
        self.assertIn("CHAT_ENCRYPTION_KEY", response.json["error"])
        self.app.config["CHAT_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        self.host.supabase_key_source = "SUPABASE_KEY"
        self.assertIn("SERVICE_ROLE", self.client.get("/api/chat/bootstrap").json["error"])
        self.host.supabase_key_source = "SUPABASE_SERVICE_KEY"
        self.app.secret_key = "weak"
        with self.client.session_transaction() as session:
            session["user"] = {"email": "alice@example.test", "employee_id": "1", "role": "Employee"}
        self.assertIn("FLASK_SECRET_KEY", self.client.get("/api/chat/bootstrap").json["error"])
        self.app.secret_key = "test-only-session-key-not-for-deployment"
        with self.client.session_transaction() as session:
            session["user"] = {"email": "alice@example.test", "employee_id": "1", "role": "Employee"}
        self.host.ADMIN_PASSWORD = "demo123"
        self.assertIn("ADMIN_PASSWORD", self.client.get("/api/chat/bootstrap").json["error"])
        self.rows[0]["password_hash"] = ""
        self.assertEqual(self.client.get("/api/chat/bootstrap").status_code, 403)
        self.assertFalse((self.directory / "chat").exists())

    def test_worker_route_root_scope(self):
        (self.directory / "static").mkdir()
        (self.directory / "static" / "chat-sw.js").write_text("// test fixture\n")
        response = self.client.get("/chat-sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/javascript")
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        response.close()

    def test_key_generator_outputs_valid_pairs_without_overwriting_live_keys(self):
        from py_vapid import Vapid
        from tools.chat_keys import generate
        settings = generate("mailto:admin@example.test")
        Fernet(settings["CHAT_ENCRYPTION_KEY"].encode())
        vapid = Vapid.from_string(settings["CHAT_VAPID_PRIVATE_KEY"])
        public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        self.assertEqual(base64.urlsafe_b64encode(public).decode().rstrip("="), settings["CHAT_VAPID_PUBLIC_KEY"])
        with self.assertRaises(ValueError):
            generate("mailto:admin@example.test\nMALICIOUS=value")


class HostIntegrationTests(unittest.TestCase):
    """Exercise real HRMS login/template integration, but patch dotenv BEFORE import."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ekkaa-integration-")
        cls.environment = patch.dict(os.environ, {
            "USE_MOCK_DATA": "true", "MOCK_PERSIST": "false", "ADMIN_EMAILS": "admin@company.com",
            "ADMIN_PASSWORD": "test-only-administrator-password", "EMPLOYEE_PASSWORD": "test-bootstrap-password",
            "FLASK_SECRET_KEY": "test-only-session-key-not-for-deployment", "SESSION_COOKIE_SECURE": "false",
            "CHAT_DATA_DIR": cls.temp.name, "CHAT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "CHAT_VAPID_PUBLIC_KEY": "", "CHAT_VAPID_PRIVATE_KEY": "", "CHAT_VAPID_SUBJECT": "",
        })
        cls.environment.start()
        with patch("dotenv.load_dotenv"):
            cls.host = importlib.import_module("app")
        cls.host.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temp.cleanup()

    def test_real_login_dashboard_chat_and_hr_report_exclusion(self):
        client = self.host.app.test_client()
        # The employee bootstrap password must NOT also unlock an unrelated admin account.
        self.assertEqual(client.post("/login", json={"email": "admin@company.com", "password": "test-bootstrap-password"}).status_code, 401)
        response = client.post("/login", json={"email": "admin@company.com", "password": "test-only-administrator-password"})
        self.assertEqual(response.status_code, 200)
        dashboard = client.get("/dashboard?chat=e:1")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b'id="module-chat"', dashboard.data)
        self.assertIn(b"/static/js/chat.js", dashboard.data)
        self.assertIn("chat", client.get("/api/session").json["modules"])
        bootstrap = client.get("/api/chat/bootstrap")
        self.assertEqual(bootstrap.status_code, 200, bootstrap.json)
        self.assertEqual(bootstrap.json["me"]["id"], "a:admin@company.com")
        contact = next(p for p in bootstrap.json["contacts"] if p["id"].startswith("e:"))
        response = client.post("/api/chat/messages/" + contact["id"], json={"body": "Integration hello", "client_id": str(uuid.uuid4())},
                               headers={"X-Chat-CSRF": bootstrap.json["csrf_token"]})
        self.assertEqual(response.status_code, 201, response.json)
        self.assertNotIn("chat_messages", self.host.CUSTOM_REPORT_DATASETS)
        self.assertNotIn("chat_push_subscriptions", self.host.SUPA_COLUMNS)
        client.get("/logout")
        response = client.get("/api/chat/bootstrap")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
