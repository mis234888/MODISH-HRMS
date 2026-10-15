# Private team chat

Chat is part of the existing Flask dashboard. Open **Chat**, search a person's
name or employee code, select them, and send a message. Conversations are saved,
with unread counts, older-message pagination, timestamps, and read receipts.
Enter sends; Shift+Enter inserts a new line. A failed send retains its draft and
retry identifier so that a retry does not duplicate an already-delivered message.

## Install and try locally

Use your existing virtual environment and private `.env`:

```powershell
cd D:\updated3\keka-hrms-clone
python -m pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000/dashboard`. For a two-person check, use two browser
profiles (or a normal window and an incognito window), with different authorized
accounts. Tabs in one browser profile share the login cookie, so they are not two
independent users.

- **Demo mode:** messages use `data/chat.sqlite3`, not the resettable mock HR JSON.
  A private encryption key is created once at `data/chat.key`. Both are ignored by
  Git. Back up both together; losing the key means losing access to the messages.
- On Windows, restrict the data directory and key using the folder's **Security**
  permissions to the application owner. POSIX `0600` does not replace Windows ACLs.
- **Supabase mode:** follow the production steps below. It intentionally does not
  fall back to plaintext or local chat storage when configuration is missing.

## Production setup

1. Install `requirements.txt` in the deployment environment.
2. Run **`supabase_chat.sql`** in the Supabase SQL editor as an administrator.
   This is a separate additive migration; the existing HR setup SQL does not
   create the chat tables or functions. Do not expose them through Realtime or
   the generic HR report builder.
3. Configure a real **server-only** `SUPABASE_SERVICE_KEY` (service-role JWT or
   `sb_secret_...` key). An anon/publishable key is not enough. Never put the
   service key into browser JavaScript.
4. Set a strong, persistent `FLASK_SECRET_KEY` of at least 32 random characters
   and a unique `ADMIN_PASSWORD` of at least 12 characters. Known starter secrets
   and default admin passwords are rejected by production chat. Without a Flask
   secret the local app uses a random process-only secret; this is not suitable
   for multiple workers or persistent login sessions.
5. Give employees their own passwords through **Me → Sign-in security**. An
   employee using only the shared bootstrap password cannot use production chat.
   Exited accounts are denied on every chat API request.
6. Generate chat encryption and push keys **once**, into a new private file:

   ```powershell
   python tools/chat_keys.py --output .env.chat --subject mailto:your-admin@example.com
   ```

   The command refuses to overwrite an existing file and never prints the keys.
   `.env.chat` is ignored by Git and is **not loaded automatically**. Copy its
   settings into your private `.env` or deployment secret manager. If you only
   need chat, configure `CHAT_ENCRYPTION_KEY`; the VAPID settings are optional.
7. Enable HTTPS, set `SESSION_COOKIE_SECURE=true`, and restart all app workers.
   An HTTPS-terminating proxy must preserve the correct host and scheme. Configure
   trusted proxy handling for your hosting platform rather than accepting arbitrary
   forwarded headers. Chat rejects foreign-origin requests, including a proxy
   origin mismatch.
8. Back up the database **and encryption key** separately, with restricted access.
   All workers must share the same encryption and Flask session keys. Do not
   regenerate `CHAT_ENCRYPTION_KEY` or VAPID keys on each deploy. Key rotation needs
   an explicit migration/resubscription plan; it is not implemented here.

## Notifications and clickable popups

Open **Chat → Chat notifications → Enable notifications**, then allow the browser
prompt. Permission is only requested after this click, never automatically.

| App state | What happens |
| --- | --- |
| Focused, reading the conversation | New messages appear and are marked read when displayed. |
| Focused, elsewhere in the dashboard | A clickable in-app popup opens the matching conversation. |
| Dashboard tab hidden/minimized | An OS notification can appear after permission is granted. Without Web Push it relies on the tab polling. |
| Dashboard tab closed | Requires configured Web Push, HTTPS, a supported browser, and an explicitly enabled device subscription. |
| Browser fully quit/device offline/OS quiet mode | Delivery depends on browser/OS policy and network; it cannot be guaranteed. |

For closed-tab notifications configure **all three**:

```dotenv
CHAT_VAPID_PUBLIC_KEY=<public key from the private generated file>
CHAT_VAPID_PRIVATE_KEY=<private key from the private generated file>
CHAT_VAPID_SUBJECT=mailto:your-admin@example.com
```

The root-scoped service worker is served at `/chat-sw.js`. Clicking a notification
focuses the dashboard and opens the sender's conversation, or opens
`/dashboard?chat=<account-id>` when no dashboard window exists. It never opens a
URL supplied by an external push payload.

**Message previews are off by default.** Enable **Show message previews** and
click **Update previews** to include a short message excerpt. This is an explicit
privacy tradeoff: previews may be visible on a lock screen. The preference is
account-specific; Web Push settings are per enabled device subscription. Turning
previews off hides them immediately on this device; use Update previews to also
update the server subscription.

Use **Disable notifications** to remove this account's device subscription.
Normal sign-out clears the worker account binding and displayed notifications.
Account switches must explicitly enable notifications again; subscriptions are
not silently reassigned. A device/browser profile has one active notification
account binding. Do not share an unlocked, signed-in browser profile.

## Security boundaries

- Message bodies and push subscription credentials are **Fernet-encrypted at
  rest**. This is **not end-to-end encryption**: the server decrypts messages to
  deliver them. Participants, timestamps, IDs, and unread metadata are not encrypted.
- Only the two participants can read a conversation through the chat API.
  An unrelated HR Admin is not given conversation access. An administrator
  without an employee row uses a separate admin identity, not the existing HR
  demo's fallback employee.
- Supabase chat tables/functions revoke browser-role access and use server-only
  RLS/grants. Application scoping remains essential because service-role access
  bypasses RLS. Chat is deliberately absent from custom HR reports.
- Writes require a session-bound CSRF token and same-origin validation. Responses
  are non-cacheable. Messages are rendered as text, not executable HTML.
- Sends are limited to 4,000 characters and 30 new messages/minute/account.
  UUID idempotency and throttling use database transactions across workers.
- Push endpoint validation restricts outbound calls to supported FCM, Mozilla,
  Apple, and Windows push providers. Push failure never undoes a saved message.
- Web Push is best-effort, using a bounded background queue and short network
  timeouts. An app restart or a full queue can drop an alert; unread messages stay
  saved. A durable notification queue is not included.
- Demo SQLite is for a local single-host deployment, not shared multi-host storage.
  Use Supabase in production. Demo mode is not a security certification; the wider
  HRMS still needs its own deployment/security review and account recovery policy.
- This release does not add attachments, groups, deletion/retention controls,
  E2EE, or chat access audit logs. Establish a company retention policy before
  storing sensitive employee conversations.

## Checks and rollout verification

```powershell
python -m unittest test_chat -v
node --check static/js/app.js
node --check static/js/chat.js
node --check static/chat-sw.js
python check_frontend_refs.py
```

The chat tests use temporary encrypted SQLite, synthetic accounts, mocked push,
and an isolated real Flask login/template integration. They do not read `.env`,
contact Supabase, send push messages, or touch existing HR data.

Before rollout, verify on the actual HTTPS deployment:

1. Two authorized users can exchange messages and reopen them after restart.
2. A third account cannot read either side's conversation.
3. Enable notifications and previews intentionally on the recipient device.
4. Hide the dashboard, then close its tab, and send a fresh message each time.
5. Click each alert and verify it opens the correct conversation.
6. Sign out/switch accounts and verify previous-account notifications stop.
7. Verify the Supabase SQL grants/RLS and database backup/restore procedure.

Live Supabase migration and real browser/OS Web Push delivery need deployment
credentials, HTTPS, and browser permission; isolated tests do not prove those.
