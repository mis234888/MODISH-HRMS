"""Private one-to-one chat. Integrate with ``init_chat(app, host_module)``.

Call after the host's functions/CORS setup and before its __main__ block. This
module never uses the host's demo employee fallback or generic report tables.
Apply supabase_chat.sql with an administrator before using real Supabase.

Settings (Flask config takes precedence over environment): CHAT_ENCRYPTION_KEY
(Fernet, mandatory for Supabase), CHAT_DATA_DIR (demo only, defaults to data/),
CHAT_VAPID_PUBLIC_KEY, CHAT_VAPID_PRIVATE_KEY, CHAT_VAPID_SUBJECT. Encryption is
server-side, NOT end-to-end. Preserve the encryption key when moving storage;
there is deliberately no plaintext/key-loss recovery or production fallback.

Push is best-effort: a small bounded, in-process executor uses a 3-second HTTP
timeout per subscription. A restart/full queue can drop a notification; messages
remain durable. At most five subscriptions/account are kept. Sending is limited
transactionally to 30 new messages/minute/account in either storage engine.
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import tempfile
import threading
from urllib.parse import urlsplit
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from flask import Blueprint, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException


MAX_ID = 9007199254740991
MAX_BODY = 4000
MAX_REQUEST = 32768
MAX_CONTACTS = 10000
MAX_SUBSCRIPTIONS = 5
MESSAGE_COLUMNS = "id,sender_id,recipient_id,client_id,body_ciphertext,body_digest,created_at,read_at"
_EMPLOYEE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_EMAIL = re.compile(r"[^\s@\x00-\x1f\x7f]{1,200}@[^\s@\x00-\x1f\x7f]{1,200}\Z")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _email(value):
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    return value if len(value) <= 254 and _EMAIL.fullmatch(value) else ""


def _label(value, limit=200):
    return value[:limit] if isinstance(value, str) else ""


def _number(value, fail, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        fail("Invalid message ID.", 400)
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,16}", text):
        fail("Invalid message ID.", 400)
    result = int(text)
    if result < (0 if allow_zero else 1) or result > MAX_ID:
        fail("Invalid message ID.", 400)
    return result


def _json_object(fail, allowed, required):
    if not request.is_json:
        fail("A JSON object is required.", 415)
    if request.content_length is not None and request.content_length > MAX_REQUEST:
        fail("Chat request is too large.", 413)
    raw = request.stream.read(MAX_REQUEST + 1)
    if len(raw) > MAX_REQUEST:
        fail("Chat request is too large.", 413)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("nonfinite number")

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError):
        fail("A valid JSON object is required.", 400)
    if not isinstance(data, dict) or set(data) - allowed or required - set(data):
        fail("Invalid chat request fields.", 400)
    return data


def _origin(value):
    """Return a canonical origin, rejecting URL components origins cannot have."""
    parsed = urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("invalid origin")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def _subscription(value, fail):
    if not isinstance(value, dict) or set(value) - {"endpoint", "expirationTime", "keys"}:
        fail("Invalid push subscription.", 400)
    expiration = value.get("expirationTime")
    if expiration is not None and (isinstance(expiration, bool)
                                   or not isinstance(expiration, (int, float))
                                   or not 0 <= expiration <= MAX_ID):
        fail("Invalid push subscription.", 400)
    endpoint = value.get("endpoint")
    if not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 2048:
        fail("Invalid push endpoint.", 400)
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        allowed = (host == "fcm.googleapis.com" or host == "web.push.apple.com"
                   or (host.endswith(".push.services.mozilla.com") and host != ".push.services.mozilla.com")
                   or (host.endswith(".notify.windows.com") and host != ".notify.windows.com"))
        if (not allowed or parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or "#" in endpoint or "\\" in endpoint
                or any(ord(c) < 33 or ord(c) > 126 for c in endpoint)):
            raise ValueError("invalid endpoint")
    except ValueError:
        fail("Invalid push endpoint.", 400)
    keys = value.get("keys")
    if not isinstance(keys, dict) or set(keys) != {"p256dh", "auth"}:
        fail("Invalid push keys.", 400)
    decoded = {}
    for name, size in (("p256dh", 65), ("auth", 16)):
        encoded = keys[name]
        if not isinstance(encoded, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}={0,2}", encoded):
            fail("Invalid push keys.", 400)
        try:
            decoded[name] = base64.b64decode(encoded + "=" * (-len(encoded) % 4),
                                             altchars=b"-_", validate=True)
        except (ValueError, TypeError):
            fail("Invalid push keys.", 400)
        if len(decoded[name]) != size:
            fail("Invalid push keys.", 400)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decoded["p256dh"])
    except ValueError:
        fail("Invalid push keys.", 400)
    # expirationTime is browser metadata, not needed by the push sender.
    return {"endpoint": endpoint, "keys": dict(keys)}


class _SQLiteStore:
    def __init__(self, directory):
        self.path = str(directory / "chat.sqlite3")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("invalid database file")
        finally:
            os.close(fd)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK(id BETWEEN 1 AND 9007199254740991),
                    sender_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
                    client_id TEXT NOT NULL, body_ciphertext TEXT NOT NULL,
                    body_digest TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT,
                    UNIQUE(sender_id, client_id), CHECK(sender_id <> recipient_id)
                );
                CREATE INDEX IF NOT EXISTS chat_pair_out ON chat_messages(sender_id, recipient_id, id);
                CREATE INDEX IF NOT EXISTS chat_pair_in ON chat_messages(recipient_id, sender_id, id);
                CREATE INDEX IF NOT EXISTS chat_events ON chat_messages(recipient_id, id);
                CREATE INDEX IF NOT EXISTS chat_unread ON chat_messages(recipient_id, sender_id, id)
                    WHERE read_at IS NULL;
                CREATE INDEX IF NOT EXISTS chat_send_rate ON chat_messages(sender_id, created_at);
                CREATE TABLE IF NOT EXISTS chat_push_subscriptions (
                    account_id TEXT NOT NULL, endpoint_hash TEXT NOT NULL,
                    subscription_ciphertext TEXT NOT NULL, preview INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(account_id, endpoint_hash)
                );
            """)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def messages(self, account, peer, before):
        with self.connection() as db:
            return [dict(r) for r in db.execute("""
                SELECT * FROM chat_messages WHERE id < ? AND
                  ((sender_id = ? AND recipient_id = ?) OR (sender_id = ? AND recipient_id = ?))
                ORDER BY id DESC LIMIT 51
            """, (before or MAX_ID + 1, account, peer, peer, account))]

    def events(self, account, after):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM chat_messages WHERE recipient_id = ? AND id > ? ORDER BY id LIMIT 101",
                (account, after))]

    def conversations(self, account):
        with self.connection() as db:
            return [dict(r) for r in db.execute("""
                WITH mine AS (
                    SELECT *, recipient_id AS peer_id FROM chat_messages WHERE sender_id = ?
                    UNION ALL
                    SELECT *, sender_id AS peer_id FROM chat_messages WHERE recipient_id = ?
                ), ranked AS (
                    SELECT *, ROW_NUMBER() OVER(PARTITION BY peer_id ORDER BY id DESC) AS rn,
                        SUM(CASE WHEN recipient_id = ? AND read_at IS NULL THEN 1 ELSE 0 END)
                            OVER(PARTITION BY peer_id) AS unread_count
                    FROM mine
                ) SELECT * FROM ranked WHERE rn = 1 ORDER BY id DESC
            """, (account, account, account))]

    def send(self, account, peer, client_id, ciphertext, digest):
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM chat_messages WHERE sender_id = ? AND client_id = ?",
                             (account, client_id)).fetchone()
            if row:
                status = "existing" if row["recipient_id"] == peer and row["body_digest"] == digest else "conflict"
                return status, dict(row)
            since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="microseconds")
            count = db.execute("SELECT COUNT(*) FROM chat_messages WHERE sender_id = ? AND created_at >= ?",
                               (account, since)).fetchone()[0]
            if count >= 30:
                return "rate_limited", None
            cursor = db.execute("""
                INSERT INTO chat_messages(sender_id,recipient_id,client_id,body_ciphertext,body_digest,created_at)
                VALUES(?,?,?,?,?,?)
            """, (account, peer, client_id, ciphertext, digest, _now()))
            row = db.execute("SELECT * FROM chat_messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
            return "created", dict(row)

    def mark_read(self, account, peer, through):
        with self.connection(write=True) as db:
            opened = db.execute("SELECT id FROM chat_messages WHERE id = ? AND recipient_id = ? AND sender_id = ?",
                                (through, account, peer)).fetchone()
            if not opened:
                return False
            db.execute("""UPDATE chat_messages SET read_at = ?
                WHERE recipient_id = ? AND sender_id = ? AND id <= ? AND read_at IS NULL""",
                       (_now(), account, peer, through))
            return True

    def subscriptions(self, account):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM chat_push_subscriptions WHERE account_id = ? LIMIT 5", (account,))]

    def save_subscription(self, account, endpoint_hash, ciphertext, preview):
        with self.connection(write=True) as db:
            exists = db.execute("SELECT 1 FROM chat_push_subscriptions WHERE account_id = ? AND endpoint_hash = ?",
                                (account, endpoint_hash)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM chat_push_subscriptions WHERE account_id = ?", (account,)).fetchone()[0]
            if not exists and count >= MAX_SUBSCRIPTIONS:
                return False
            db.execute("""INSERT INTO chat_push_subscriptions VALUES(?,?,?,?)
                ON CONFLICT(account_id,endpoint_hash) DO UPDATE SET
                subscription_ciphertext=excluded.subscription_ciphertext, preview=excluded.preview""",
                       (account, endpoint_hash, ciphertext, int(preview)))
            return True

    def delete_subscription(self, account, endpoint_hash):
        with self.connection(write=True) as db:
            db.execute("DELETE FROM chat_push_subscriptions WHERE account_id = ? AND endpoint_hash = ?",
                       (account, endpoint_hash))


class _SupabaseStore:
    """Only scoped, bounded queries; SQL RPCs do aggregation/atomic writes."""

    def __init__(self, client):
        self.client = client

    def messages(self, account, peer, before):
        rows = []
        # Two indexed directions avoid interpolating IDs into PostgREST or_ syntax.
        for sender, recipient in ((account, peer), (peer, account)):
            query = (self.client.table("chat_messages").select(MESSAGE_COLUMNS)
                     .eq("sender_id", sender).eq("recipient_id", recipient))
            if before is not None:
                query = query.lt("id", before)
            rows.extend(query.order("id", desc=True).limit(51).execute().data or [])
        return sorted(rows, key=lambda row: int(row["id"]), reverse=True)[:51]

    def events(self, account, after):
        return (self.client.table("chat_messages").select(MESSAGE_COLUMNS)
                .eq("recipient_id", account).gt("id", after)
                .order("id").limit(101).execute().data or [])

    def conversations(self, account):
        rows = []
        before = MAX_ID + 1
        while True:
            page = self.client.rpc("chat_conversations", {
                "p_account_id": account, "p_before": before, "p_limit": 200,
            }).execute().data or []
            if not page:
                return rows
            rows.extend(page)
            next_before = min(int(row["id"]) for row in page)
            if next_before >= before:
                raise ValueError("invalid conversation cursor")
            before = next_before
            # Continue even on a short page: server PostgREST row caps can be
            # smaller than our requested batch. An empty keyset page ends it.

    def send(self, account, peer, client_id, ciphertext, digest):
        result = self.client.rpc("chat_send_message", {
            "p_sender_id": account, "p_recipient_id": peer, "p_client_id": client_id,
            "p_body_ciphertext": ciphertext, "p_body_digest": digest,
        }).execute().data
        return result["status"], result.get("message")

    def mark_read(self, account, peer, through):
        return bool(self.client.rpc("chat_mark_read", {
            "p_account_id": account, "p_peer_id": peer, "p_through_id": through,
        }).execute().data)

    def subscriptions(self, account):
        return (self.client.table("chat_push_subscriptions")
                .select("account_id,endpoint_hash,subscription_ciphertext,preview")
                .eq("account_id", account).limit(MAX_SUBSCRIPTIONS).execute().data or [])

    def save_subscription(self, account, endpoint_hash, ciphertext, preview):
        return bool(self.client.rpc("chat_save_subscription", {
            "p_account_id": account, "p_endpoint_hash": endpoint_hash,
            "p_subscription_ciphertext": ciphertext, "p_preview": preview,
        }).execute().data)

    def delete_subscription(self, account, endpoint_hash):
        (self.client.table("chat_push_subscriptions").delete()
         .eq("account_id", account).eq("endpoint_hash", endpoint_hash).execute())


def _demo_key(directory):
    """Publish a fully written 0600 key with link(), never a partial/racy key."""
    key_path = directory / "chat.key"
    if not key_path.exists():
        fd, temporary = tempfile.mkstemp(prefix=".chat-key-", dir=str(directory))
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(Fernet.generate_key())
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(temporary, key_path)
            except FileExistsError:
                pass  # Another process published its complete key first.
        finally:
            os.unlink(temporary)
    fd = os.open(key_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("demo key must be private")
        return source.read(45)


class _Chat:
    def __init__(self, app, host):
        self.app = app
        self.host = host
        self._lock = threading.Lock()
        self._store = None
        self._fernet = None
        self._digest_key = None
        self._executor = None
        self._push_slots = threading.BoundedSemaphore(16)

    def fail(self, message, status=400):
        raise self.host.ApiError(message, status)

    def setting(self, name, default=None):
        return self.app.config.get(name, os.environ.get(name, default))

    def accounts(self):
        user = session.get("user")
        if not isinstance(user, dict) or user.get("role") not in ("Employee", "HR Admin"):
            self.fail("Sign in to use chat.", 401)
        try:
            rows = self.host.db_list("employees")
        except Exception:
            self.fail("Chat accounts are temporarily unavailable.", 503)
        if not isinstance(rows, list) or len(rows) > MAX_CONTACTS:
            self.fail("Chat account directory is unavailable.", 503)
        by_email = {}
        for row in rows:
            email = _email(row.get("email"))
            if email:
                by_email.setdefault(email, []).append(row)
        accounts = {}
        email_ids = {}
        for email, matches in by_email.items():
            # Ambiguous/invalid rows fail closed, including for configured admins.
            if len(matches) != 1:
                continue
            row = matches[0]
            employee_id = str(row.get("id") or "")
            if (not _EMPLOYEE_ID.fullmatch(employee_id)
                    or str(row.get("status") or "").strip().lower() == "exited"):
                continue
            account_id = "e:" + employee_id
            if account_id in accounts:
                self.fail("Chat account directory is unavailable.", 503)
            accounts[account_id] = {
                "id": account_id, "name": _label(row.get("full_name")) or email,
                "department": _label(row.get("department")),
                "employee_code": _label(row.get("employee_code"), 128),
            }
            email_ids[email] = account_id
        admins = {_email(email) for email in self.host.ADMIN_EMAILS}
        admins.discard("")
        if len(accounts) + len(admins) > MAX_CONTACTS:
            self.fail("Chat account directory is unavailable.", 503)
        for email in admins - by_email.keys():
            account_id = "a:" + email
            accounts[account_id] = {"id": account_id, "name": email,
                                    "department": "", "employee_code": ""}
            email_ids[email] = account_id
        account_id = email_ids.get(_email(user.get("email")))
        if not account_id:
            self.fail("This account is not eligible for chat.", 403)
        employee_id = user.get("employee_id")
        if account_id.startswith("e:"):
            if employee_id is None or str(employee_id) != account_id[2:]:
                self.fail("This account is not eligible for chat.", 403)
        elif user.get("role") != "HR Admin" or employee_id not in (None, ""):
            self.fail("This account is not eligible for chat.", 403)
        if self.host.supabase is not None and user.get("role") == "Employee":
            own_row = by_email[_email(user.get("email"))][0]
            if not own_row.get("password_hash"):
                self.fail("Set your own password in Me before using private chat.", 403)
        return accounts, accounts[account_id]

    def peer(self, peer_id):
        if len(peer_id) > 256 or peer_id not in g.chat_accounts or peer_id == g.chat_me["id"]:
            self.fail("Chat contact not found.", 404)
        return peer_id

    def same_origin(self):
        value = request.headers.get("Origin")
        if value is not None:
            try:
                if len(value) > 2048 or _origin(value) != _origin(request.host_url):
                    raise ValueError("foreign origin")
            except ValueError:
                self.fail("Cross-origin chat requests are not allowed.", 403)
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            self.fail("Cross-origin chat requests are not allowed.", 403)

    def csrf(self):
        saved = session.get("_chat_csrf")
        token = request.headers.get("X-Chat-CSRF", "")
        if (not isinstance(saved, dict) or saved.get("account_id") != g.chat_me["id"]
                or not isinstance(saved.get("token"), str) or not token.isascii()
                or len(token) > 128 or not secrets.compare_digest(token, saved["token"])):
            self.fail("Invalid chat CSRF token. Reload chat and try again.", 403)

    def bootstrap_token(self):
        saved = session.get("_chat_csrf")
        if (not isinstance(saved, dict) or saved.get("account_id") != g.chat_me["id"]
                or not isinstance(saved.get("token"), str) or len(saved["token"]) != 43):
            saved = {"account_id": g.chat_me["id"], "token": secrets.token_urlsafe(32)}
            session["_chat_csrf"] = saved
        return saved["token"]

    def _service_role(self):
        source = getattr(self.host, "supabase_key_source", None)
        if source not in ("SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY"):
            self.fail("Chat requires a Supabase SERVICE_ROLE key source; public/anon keys are not allowed.", 503)
        key = (getattr(self.host.supabase, "supabase_key", None)
               or getattr(self.host, "SUPABASE_SERVICE_KEY", None)
               or getattr(self.host, "SUPABASE_SECRET_KEY", None))
        valid = isinstance(key, str) and key.startswith("sb_secret_")
        if isinstance(key, str) and not valid:
            try:
                part = key.split(".")[1]
                payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
                valid = payload.get("role") == "service_role"
            except (ValueError, IndexError, TypeError, AttributeError):
                valid = False
        if not valid:
            self.fail("Chat requires a Supabase SERVICE_ROLE key; public/anon keys are not allowed.", 503)

    def storage(self):
        if self._store is not None:
            return self._store
        with self._lock:
            if self._store is not None:
                return self._store
            real = self.host.supabase is not None
            if real:
                self._service_role()
            key = self.setting("CHAT_ENCRYPTION_KEY")
            if not key and real:
                self.fail("Chat unavailable: CHAT_ENCRYPTION_KEY is required for Supabase.", 503)
            if real:
                secret = self.app.secret_key
                unsafe_secrets = {"keka-clone-secret-key-2026-super-secure", "change-this-to-a-random-secret-key"}
                if (not self.app.config.get("CHAT_SESSION_SECRET_CONFIGURED", True)
                        or not isinstance(secret, (str, bytes)) or len(secret) < 32 or secret in unsafe_secrets):
                    self.fail("Chat requires a strong, persistent FLASK_SECRET_KEY (at least 32 characters).", 503)
                admin_password = getattr(self.host, "ADMIN_PASSWORD", "")
                if not isinstance(admin_password, str) or len(admin_password) < 12 or admin_password == "demo123":
                    self.fail("Chat requires a unique ADMIN_PASSWORD of at least 12 characters.", 503)
            try:
                directory = None
                if not real:
                    directory = Path(self.setting("CHAT_DATA_DIR") or Path(self.app.root_path) / "data")
                    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if not key:
                        key = _demo_key(directory)
                if isinstance(key, str):
                    key = key.encode("ascii")
                fernet = Fernet(key)
            except Exception:
                self.fail("Chat encryption is unavailable. Check CHAT_ENCRYPTION_KEY or demo key permissions.", 503)
            try:
                store = _SupabaseStore(self.host.supabase) if real else _SQLiteStore(directory)
            except Exception:
                self.fail("Chat storage is temporarily unavailable.", 503)
            self._fernet = fernet
            self._digest_key = base64.urlsafe_b64decode(key)
            self._store = store
        return self._store

    def encrypt(self, text):
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, token):
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")

    def message(self, row):
        message_id = int(row["id"])
        if not 1 <= message_id <= MAX_ID:
            raise ValueError("invalid stored message ID")
        return {"id": message_id, "body": self.decrypt(row["body_ciphertext"]),
                "sender_id": row["sender_id"], "recipient_id": row["recipient_id"],
                "created_at": row["created_at"], "read_at": row.get("read_at")}

    def conversation_payload(self):
        conversations = []
        for row in self.storage().conversations(g.chat_me["id"]):
            conversations.append({"peer_id": row["peer_id"], "last_message": self.message(row),
                                  "unread_count": int(row["unread_count"])})
        return {"conversations": conversations,
                "unread_count": sum(item["unread_count"] for item in conversations)}

    def push_config(self):
        public = self.setting("CHAT_VAPID_PUBLIC_KEY")
        private = self.setting("CHAT_VAPID_PRIVATE_KEY")
        subject = self.setting("CHAT_VAPID_SUBJECT")
        return public, private, subject

    def push_status(self):
        public, private, subject = self.push_config()
        enabled = bool(public and private and subject)
        return {"enabled": enabled, "public_key": public if enabled else None}

    def queue_push(self, message):
        if not self.push_status()["enabled"] or not self._push_slots.acquire(blocking=False):
            return
        try:
            with self._lock:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-push")
            self._executor.submit(self._push, message)
        except Exception:
            self._push_slots.release()

    def _push(self, message):
        try:
            from pywebpush import WebPushException, webpush
            from requests import Session

            class ProviderSession(Session):
                def request(self, method, url, **kwargs):
                    # Even a provider redirect cannot send credentials/data to
                    # an unvalidated URL. Do not consult machine proxy settings.
                    kwargs["allow_redirects"] = False
                    return super().request(method, url, **kwargs)

            _, private, subject = self.push_config()
            store = self.storage()
            recipient = message["recipient_id"]
            with ProviderSession() as http:
                http.trust_env = False
                for row in store.subscriptions(recipient):
                    try:
                        subscription = _subscription(json.loads(self.decrypt(row["subscription_ciphertext"])), self.fail)
                        payload = {"title": "New chat message",
                                   "body": message["body"][:120] if row["preview"] else "You have a new message.",
                                   "peer_id": message["sender_id"], "message_id": message["id"],
                                   "recipient_id": recipient}
                        webpush(subscription_info=subscription, data=json.dumps(payload),
                                vapid_private_key=private, vapid_claims={"sub": subject},
                                timeout=3, ttl=300, requests_session=http)
                    except WebPushException as error:
                        response = getattr(error, "response", None)
                        if response is not None and getattr(response, "status_code", None) in (404, 410):
                            store.delete_subscription(recipient, row["endpoint_hash"])
                    except Exception:
                        # Never log subscription credentials, provider responses or bodies.
                        continue
        except Exception:
            pass  # Push failure cannot affect the committed chat message.
        finally:
            self._push_slots.release()


def init_chat(app, host_module):
    """Register routes without touching real storage or loading host configuration."""
    if "chat" in app.extensions:
        return app.extensions["chat"]
    chat = _Chat(app, host_module)
    api = Blueprint("private_chat", __name__)

    @api.errorhandler(Exception)
    def chat_error(error):
        if isinstance(error, host_module.ApiError):
            return jsonify(success=False, error=error.message), error.status
        if isinstance(error, HTTPException):
            return jsonify(success=False, error="Invalid chat request."), error.code
        # No raw exception text/tracebacks: storage/provider errors can contain
        # credentials, ciphertext, endpoint URLs or database configuration.
        return jsonify(success=False, error="Chat is temporarily unavailable."), 503

    @api.before_request
    def prepare_chat():
        chat.same_origin()
        if request.path == "/chat-sw.js":
            return None
        if len(request.query_string) > 2048:
            chat.fail("Chat request is too large.", 413)
        g.chat_accounts, g.chat_me = chat.accounts()
        if request.method in ("POST", "DELETE", "PUT", "PATCH"):
            chat.csrf()
        return None

    def query(allowed):
        if set(request.args) - allowed or any(len(request.args.getlist(k)) != 1 for k in request.args):
            chat.fail("Invalid chat query.", 400)

    @api.get("/api/chat/bootstrap")
    def bootstrap():
        query(set())
        payload = chat.conversation_payload()
        payload.update(me={"id": g.chat_me["id"], "name": g.chat_me["name"]},
                       csrf_token=chat.bootstrap_token(), push=chat.push_status(),
                       contacts=sorted((value for key, value in g.chat_accounts.items() if key != g.chat_me["id"]),
                                       key=lambda value: (value["name"].casefold(), value["id"])))
        return jsonify(payload)

    @api.get("/api/chat/conversations")
    def conversations():
        query(set())
        return jsonify(chat.conversation_payload())

    @api.get("/api/chat/messages/<path:peer_id>")
    def messages(peer_id):
        query({"before"})
        peer = chat.peer(peer_id)
        before = _number(request.args["before"], chat.fail) if "before" in request.args else None
        rows = chat.storage().messages(g.chat_me["id"], peer, before)
        return jsonify(messages=[chat.message(row) for row in reversed(rows[:50])], has_more=len(rows) > 50)

    @api.post("/api/chat/messages/<path:peer_id>")
    def send_message(peer_id):
        query(set())
        peer = chat.peer(peer_id)
        data = _json_object(chat.fail, {"body", "client_id"}, {"body", "client_id"})
        body, client_id = data["body"], data["client_id"]
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY:
            chat.fail("Message body must contain 1 to 4000 characters.", 400)
        try:
            body_bytes = body.encode("utf-8")
        except UnicodeError:
            chat.fail("Message body must be valid Unicode.", 400)
        try:
            if not isinstance(client_id, str) or len(client_id) != 36:
                raise ValueError("invalid UUID")
            client_id = str(uuid.UUID(client_id))
        except ValueError:
            chat.fail("client_id must be a UUID.", 400)
        store = chat.storage()
        digest = hmac.new(chat._digest_key, b"chat-body-v1\x00" + body_bytes, hashlib.sha256).hexdigest()
        status, row = store.send(g.chat_me["id"], peer, client_id, chat.encrypt(body), digest)
        if status == "conflict":
            chat.fail("client_id was already used for a different message.", 409)
        if status == "rate_limited":
            chat.fail("Chat send limit reached. Try again in a minute.", 429)
        if status not in ("created", "existing") or row is None:
            chat.fail("Chat storage is temporarily unavailable.", 503)
        result = chat.message(row)
        if status == "created":
            # Once the transaction commits, even queue/configuration failure must
            # not turn a successful send into an apparent failure/retry.
            try:
                chat.queue_push(result)
            except Exception:
                pass
        return jsonify(message=result), 201 if status == "created" else 200

    @api.post("/api/chat/messages/<path:peer_id>/read")
    def read_messages(peer_id):
        query(set())
        peer = chat.peer(peer_id)
        data = _json_object(chat.fail, {"through_id"}, {"through_id"})
        through = _number(data["through_id"], chat.fail)
        if not chat.storage().mark_read(g.chat_me["id"], peer, through):
            chat.fail("Opened message not found in this conversation.", 404)
        return jsonify(success=True)

    @api.get("/api/chat/events")
    def events():
        query({"after"})
        after = _number(request.args.get("after", "0"), chat.fail, allow_zero=True)
        rows = chat.storage().events(g.chat_me["id"], after)
        page = [chat.message(row) for row in rows[:100]]
        return jsonify(events=page, cursor=page[-1]["id"] if page else after, has_more=len(rows) > 100)

    @api.post("/api/chat/push-subscriptions")
    def save_subscription():
        query(set())
        data = _json_object(chat.fail, {"subscription", "preview"}, {"subscription"})
        preview = data.get("preview", False)
        if not isinstance(preview, bool):
            chat.fail("preview must be a boolean.", 400)
        subscription = _subscription(data["subscription"], chat.fail)
        store = chat.storage()
        endpoint_hash = hashlib.sha256(subscription["endpoint"].encode("utf-8")).hexdigest()
        ciphertext = chat.encrypt(json.dumps(subscription, separators=(",", ":")))
        if not store.save_subscription(g.chat_me["id"], endpoint_hash, ciphertext, preview):
            chat.fail("Too many push subscriptions. Remove an existing device first.", 409)
        return jsonify(success=True)

    @api.delete("/api/chat/push-subscriptions")
    def delete_subscription():
        query(set())
        data = _json_object(chat.fail, {"endpoint"}, {"endpoint"})
        endpoint = data["endpoint"]
        if not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 2048 or not endpoint.isascii():
            chat.fail("Invalid push endpoint.", 400)
        # Deletion never performs a network request; account scope is mandatory.
        endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        chat.storage().delete_subscription(g.chat_me["id"], endpoint_hash)
        return jsonify(success=True)

    @api.get("/chat-sw.js")
    def worker():
        response = send_from_directory(app.static_folder, "chat-sw.js", mimetype="application/javascript", max_age=0)
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    def secure_headers(response):
        if request.path == "/api/chat" or request.path.startswith("/api/chat/") or request.path == "/chat-sw.js":
            for header in list(response.headers.keys()):
                if header.lower().startswith("access-control-"):
                    del response.headers[header]
            response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-cache" if request.path == "/chat-sw.js" else "no-store"
        return response

    # Flask executes app after_request callbacks in reverse registration order.
    # Index zero therefore strips even headers appended by the host's CORS(*).
    app.after_request_funcs.setdefault(None, []).insert(0, secure_headers)
    app.register_blueprint(api)
    app.extensions["chat"] = chat
    return chat
