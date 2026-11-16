"""End-to-end API test for the dashboard - runs against the demo (mock) data on port 5001.

The app now requires a signed-in session for every /api/ route except /api/health and
/api/login-hint, so this harness logs in as the configured HR Admin first. Every row it
creates is removed again at the end, which keeps the run repeatable against the same
persisted demo store.

Start the server it talks to with:
    $env:PORT=5001; $env:USE_MOCK_DATA="true"; python app.py
"""
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:5001'

# Print UTF-8 regardless of the console code page (the API returns emoji/rupee signs).
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

from dotenv import dotenv_values                                     # noqa: E402

_env = dotenv_values(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
ADMIN_EMAIL = (_env.get('ADMIN_EMAILS') or 'admin@company.com').split(',')[0].strip().lower()
ADMIN_PASSWORD = _env.get('ADMIN_PASSWORD') or 'demo123'

PASS, FAIL = [], []
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def check_html_balance():
    """Naive tag balance check for the dashboard template."""
    html = open('templates/dashboard.html', encoding='utf-8').read()
    counts = {}
    for tag in ('div', 'aside', 'main', 'header', 'nav', 'form', 'table', 'span', 'button'):
        opens = len(re.findall(r'<' + tag + r'[\s>]', html))
        closes = len(re.findall(r'</' + tag + r'>', html))
        counts[tag] = opens - closes
    bad = {k: v for k, v in counts.items() if v != 0}
    print('HTML TAG BALANCE:', 'OK' if not bad else f'MISMATCH {bad}')
    check('html tags balanced', not bad, bad)


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header('Content-Type', 'application/json')
    try:
        with _opener.open(req, data) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw  # non-JSON (HTML page)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except urllib.error.URLError as e:
        print(f'\nCannot reach {BASE} - start the demo server first '
              f'(PORT=5001, USE_MOCK_DATA=true).\n  {e}\n')
        raise SystemExit(2)


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} | {name} {('- ' + str(detail)) if detail and not cond else ''}")


def rows_of(payload, key=None):
    """Endpoints answer either a bare list or {key: [...]}; normalise both."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if key and isinstance(payload.get(key), list):
            return payload[key]
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value
    return []
