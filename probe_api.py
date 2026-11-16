"""Read-only probe: log in as HR Admin against a local server and dump endpoint shapes."""
import http.cookiejar
import json
import urllib.request

from dotenv import dotenv_values

BASE = "http://127.0.0.1:5001"
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
vals = dotenv_values(".env")
email = vals["ADMIN_EMAILS"].split(",")[0].strip()
password = vals["ADMIN_PASSWORD"]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
login = opener.open(urllib.request.Request(
    BASE + "/login",
    data=json.dumps({"email": email, "password": password}).encode(),
    headers={"Content-Type": "application/json"},
))
print("login", login.status)

for path in ["/api/session", "/api/leave-balances?employee_id=e0009",
             "/api/attendance?from=2026-11-16&to=2026-11-16&employee_id=e0009"]:
    try:
        payload = json.loads(opener.open(BASE + path).read().decode())
    except Exception as exc:                                   # noqa: BLE001
        print(path, "ERR", exc)
        continue
    print(path, "->", json.dumps(payload)[:900])
    try:
        payload = json.loads(opener.open(BASE + path).read().decode())
    except Exception as exc:                                   # noqa: BLE001
        print(path, "ERR", exc)
        continue
    if isinstance(payload, dict):
        print(path, "-> dict", list(payload)[:10])
        lists = [k for k, v in payload.items() if isinstance(v, list)]
        if lists:
            sample = payload[lists[0]]
            print("    list key:", lists[0], "len", len(sample), "sample", sample[0] if sample else None)
    else:
        print(path, "-> list len", len(payload), "sample", payload[0] if payload else None)
