"""
Ekkaa HRMS - Python Flask + Supabase
Complete HRMS: Home, Me, Inbox, Employees, Org Chart, Documents, Attendance,
Leave, Timesheet, Payroll, Expenses, Hiring, Performance and Reports.

Works in two modes with the exact same routes:
  * Supabase  (Postgres through the supabase-py client)
  * Demo mode (in-memory store from mock_data.py, persisted to data/mock_store.json)
"""
import io
import json
import os
import secrets
import re
import uuid
import csv
import sys
from datetime import datetime, date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, render_template, request, jsonify, session, redirect,
                   url_for, flash, g, send_from_directory, Response)
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

# One wall clock for the whole app. app.py and mock_data.py both read it, because the host this runs
# on is not the office: see clock.py.
from clock import TZ_LABEL as APP_TZ_LABEL, now_local, offset_minutes, today

APP_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
MOCK_STORE_PATH = os.path.join(APP_DIR, "data", "mock_store.json")
MOCK_PERSIST = os.getenv("MOCK_PERSIST", "true").lower() != "false"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true")
app.config["CHAT_SESSION_SECRET_CONFIGURED"] = bool(os.getenv("FLASK_SECRET_KEY"))
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024        # 25 MB uploads
CORS(app)


def _asset_version(filename):
    """Cache-buster for static assets: the file's mtime, so a redeploy (or an edit
    during development) instantly produces a new /static/...?v=NNN URL and browsers
    stop serving the stale previous JS."""
    try:
        return str(int(os.path.getmtime(os.path.join(APP_DIR, "static", filename))))
    except OSError:
        return "1"


app.jinja_env.globals["asset_v"] = _asset_version("js/app.js")

# ---------------- Supabase setup ----------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET") or None
USE_MOCK = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

supabase = None
supabase_key_source = None
supabase_error = None

if SUPABASE_URL and not USE_MOCK:
    key_candidates = []
    if SUPABASE_SERVICE_KEY:
        key_candidates.append(("SUPABASE_SERVICE_KEY", SUPABASE_SERVICE_KEY))
    if SUPABASE_KEY:
        key_candidates.append(("SUPABASE_KEY", SUPABASE_KEY))
    for _key_name, _key_value in key_candidates:
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, _key_value)
            supabase_key_source = _key_name
            print(f"Connected to Supabase using {_key_name}: {SUPABASE_URL}")
            break
        except Exception as exc:                                          # noqa: BLE001
            supabase_error = str(exc)
            print(f"{_key_name} rejected by Supabase for {SUPABASE_URL}: {exc}")
    if supabase is None:
        print("Supabase credentials invalid; falling back to demo data")

if supabase is None:
    from mock_data import build_mock_db, MOCK_VERSION
    print("Using DEMO DATA (set SUPABASE_URL + keys and USE_MOCK_DATA=false to use the real DB)")

# ---------------- Access control ----------------
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "admin@company.com").split(",") if e.strip()}
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "demo123")
EMPLOYEE_PASSWORD = os.getenv("EMPLOYEE_PASSWORD", "demo123")

# The demo HR Admin login has no employee row of its own, so "self" actions fall back to this person.
DEFAULT_EMPLOYEE_EMAIL = os.getenv("DEFAULT_EMPLOYEE_EMAIL", "aarav.sharma@company.com")
if not os.getenv("ADMIN_EMAILS") or ADMIN_PASSWORD == "demo123":
    print("[WARN] Default credentials in use (ADMIN_EMAILS=admin@company.com / ADMIN_PASSWORD=demo123).")

MIN_PASSWORD_LENGTH = max(6, int(os.getenv("MIN_PASSWORD_LENGTH", "8")))

# --------------------------------------------------------------------- who sees what
# One access map for the whole app: the sidebar template, the browser module guard and the API
# decorators all read these lists, so a screen can never be hidden in one place and still be
# reachable in another. Employees get a self-service workspace; HR Admins get everything.
EMPLOYEE_MODULES = ["home", "me", "inbox", "attendance", "leave", "timesheet", "payroll",
                    "expenses", "documents", "performance", "orgchart", "chat"]
ADMIN_MODULES = ["employees", "hiring", "reports"]
ALL_MODULES = EMPLOYEE_MODULES + ADMIN_MODULES

# What an employee may change on their own profile in the Me section.
SELF_EDITABLE_FIELDS = {"phone", "personal_email", "address", "blood_group", "emergency_contact_name",
                        "emergency_contact_phone", "emergency_contact_relation", "work_location"}

# Columns that exist per Supabase table - unknown keys are stripped before a write so the
# demo-only display fields never break PostgREST.
SUPA_COLUMNS = {
    "departments": {"name", "description", "head_id"},
    "shifts": {"name", "start_time", "end_time", "grace_minutes"},
    "designations": {"title", "department_id", "level"},
    "employees": {"employee_code", "full_name", "email", "personal_email", "phone", "avatar", "gender",
                  "date_of_birth", "date_of_joining", "department_id", "designation_id", "manager_id",
                  "employment_type", "work_location", "status", "salary_ctc", "blood_group", "nationality",
                  "address", "pan_no", "uan_no", "pf_no", "bank_name", "bank_account_no", "ifsc_code",
                  "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
                  "password_hash",
                  "exit_date", "exit_reason"},
    "attendance": {"employee_id", "date", "clock_in", "clock_out", "work_hours", "break_minutes", "status",
                   "shift_id", "location", "note", "is_late", "regularization_status", "regularization_reason",
                   "clock_in_location", "clock_out_location"},
    "attendance_regularizations": {"employee_id", "date", "request_type", "clock_in_correction",
                                   "clock_out_correction", "reason", "status", "reviewer_id", "reviewed_at",
                                   "reviewer_remark", "requested_at" },
    "leave_types": {"name", "code", "color", "yearly_quota", "is_paid", "requires_approval"},
    "leave_balances": {"employee_id", "leave_type_id", "year", "total", "used", "pending"},
    "leave_requests": {"employee_id", "leave_type_id", "start_date", "end_date", "days", "half_day", "reason",
                       "status", "approver_id", "actioned_at", "admin_remark", "applied_at" },
    "holidays": {"name", "date", "type"},
    "payroll_structures": {"employee_id", "basic", "hra", "special_allowance", "pf", "esi",
                           "name", "allowances", "employer_pf",
                           "professional_tax", "tds", "ctc", "effective_from"},
    "payslips": {"employee_id", "month", "year", "period", "gross_earnings", "total_deductions", "net_pay",
                 "status", "payslip_url", "generated_at", "generated_by", "published_at", "paid_on",
                 "bonus", "deductions", "lop_days", "payable_days", "working_days", "notes" },
    "reimbursements": {"employee_id", "category", "amount", "date", "description", "receipt_url", "status",
                       "reviewer_remark", "created_at" },
    "jobs": {"title", "department_id", "location", "employment_type", "experience", "salary_range", "openings",
             "description", "status", "hiring_manager_id", "closed_at", "closure_reason", "posted_at"},
    "candidates": {"job_id", "full_name", "email", "phone", "experience_years", "current_ctc", "expected_ctc",
                   "stage", "rating", "source", "owner_id", "resume_url", "notes", "converted_employee_id", "applied_at", "current_role", "stage_changed_at" },
    "goals": {"employee_id", "title", "description", "category", "metric", "target", "progress", "status",
              "due_date", "created_at" },
    "performance_reviews": {"employee_id", "reviewer_id", "period", "cycle_start", "cycle_end", "due_date",
                            "self_rating", "manager_rating", "final_rating", "potential", "strengths",
                            "improvements", "comments", "status", "competencies", "created_at" },
    "feedbacks": {"from_employee_id", "to_employee_id", "message", "tags", "category", "is_anonymous",
                  "date", "created_at"},
    "checkins": {"employee_id", "manager_id", "date", "agenda", "notes", "next_steps", "status", "created_at" },
    "announcements": {"title", "content", "type", "created_by", "is_pinned", "date", "created_at" },
    "documents": {"employee_id", "title", "doc_type", "category", "purpose", "file_name", "file_url", "file_size",
                  "mime_type", "description", "uploaded_by", "valid_from", "valid_till", "visibility",
                  "status", "reviewer_id", "reviewed_at", "reviewer_remark", "uploaded_at", "notes" },
    "document_requests": {"employee_id", "doc_type", "reason", "due_date", "requested_by", "status",
                          "fulfilled_document_id", "created_at" },
    "projects": {"code", "name", "client", "manager_id", "billing_rate", "status"},
    "timesheets": {"employee_id", "week_starting", "status", "submitted_at", "approved_by", "approved_at",
                   "reviewer_remark", "total_hours", "billable_hours"},
    "timesheet_entries": {"timesheet_id", "employee_id", "project_id", "date", "hours", "billable", "task"},
}
# Display-only columns some deployments keep on `employees` from the older demo schema.
LEGACY_EMPLOYEE_COLUMNS = {"designation", "department", "manager", "avatar"}

# Tables the report builder may slice. Everything here is a real column set from
# SUPA_COLUMNS, so the picker can never offer a field the database does not have.
CUSTOM_REPORT_PRIORITY = ["employees", "attendance", "leave_requests", "payslips", "payroll_structures",
                          "reimbursements", "timesheet_entries", "documents", "candidates", "jobs",
                          "performance_reviews", "goals", "feedbacks", "checkins", "attendance_regularizations",
                          "document_requests", "timesheets", "projects", "leave_balances", "holidays",
                          "shifts", "departments", "designations", "leave_types", "announcements"]
CUSTOM_REPORT_DATASETS = ([t for t in CUSTOM_REPORT_PRIORITY if t in SUPA_COLUMNS]
                          + sorted(t for t in SUPA_COLUMNS if t not in CUSTOM_REPORT_PRIORITY))

# A document request is "open" under either spelling - older deployments seeded
# `Requested` while the app writes `Pending`.
OPEN_DOC_REQUESTS = ("in", ["Pending", "Requested"])


# =================================================================== demo store
class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


mock_db = None


def _load_mock():
    global mock_db
    if mock_db is not None:
        return mock_db
    if MOCK_PERSIST and os.path.exists(MOCK_STORE_PATH):
        try:
            blob = json.load(open(MOCK_STORE_PATH, encoding="utf-8"))
            if blob.get("_version") == MOCK_VERSION:
                mock_db = {k: v for k, v in blob.items() if not k.startswith("_")}
                print(f"Restored demo data from {os.path.relpath(MOCK_STORE_PATH, APP_DIR)}")
                return mock_db
            print("Demo data file is from an older version - regenerating")
        except Exception as exc:                                          # noqa: BLE001
            print(f"Could not read {MOCK_STORE_PATH}: {exc}")
    mock_db = build_mock_db()
    _save_mock()
    return mock_db


def _save_mock():
    if not MOCK_PERSIST or supabase or mock_db is None:
        return
    try:
        os.makedirs(os.path.dirname(MOCK_STORE_PATH), exist_ok=True)
        blob = dict(mock_db)
        blob["_version"] = MOCK_VERSION
        blob["_saved_at"] = now_local().isoformat()
        tmp = MOCK_STORE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, default=str)
        os.replace(tmp, MOCK_STORE_PATH)
    except Exception as exc:                                              # noqa: BLE001
        print(f"Demo store persist skipped: {exc}")


def reset_mock():
    global mock_db
    mock_db = build_mock_db()
    _save_mock()
    return mock_db


if supabase is None:
    _load_mock()


# =================================================================== data layer
def _matches(val, cond):
    if isinstance(cond, tuple):
        op, cmp_val = cond
        if op == ">=":
            return val is not None and str(val)[:10] >= str(cmp_val)[:10]
        if op == "<=":
            return val is not None and str(val)[:10] <= str(cmp_val)[:10]
        if op == "in":
            return val in cmp_val
        if op == "!=":
            return val != cmp_val
        return str(val) == str(cmp_val)
    if cond is None:
        return val in (None, "")
    return str(val) == str(cond)


def db_list(table, filters=None, order=None, descending=False, limit=None):
    """Read rows from Supabase when configured, otherwise from the demo store."""
    if supabase:
        def build(use_order, use_limit):
            query = supabase.table(table).select("*")
            for key, cond in (filters or {}).items():
                if isinstance(cond, tuple):
                    op, val = cond
                    if op == ">=":
                        query = query.gte(key, val)
                    elif op == "<=":
                        query = query.lte(key, val)
                    elif op == "in":
                        query = query.in_(key, list(val))
                    elif op == "!=":
                        query = query.neq(key, val)
                    else:
                        query = query.eq(key, val)
                elif cond is None:
                    query = query.is_(key, None)
                else:
                    query = query.eq(key, cond)
            if order and use_order:
                query = query.order(order, desc=descending)
            if limit and use_limit:
                query = query.limit(limit)
            return query

        # ordering is cosmetic, so a column this database lacks must never fail the whole screen;
        # filters are not cosmetic (they carry the row-level scoping) and are left to error loudly
        sql_order = order_is_usable(table, order) if order else True
        try:
            res = build(sql_order, sql_order or not order).execute()
        except Exception as exc:                                          # noqa: BLE001
            if order and sql_order and _names_missing_column(exc, order):
                mark_column_absent(table, order)                          # remembered: no repeat cost
                try:
                    res = build(False, False).execute()
                except Exception as retry_exc:                            # noqa: BLE001
                    exc = retry_exc
                else:
                    rows = _sort_rows([dict(r) for r in (res.data or [])], order, descending)
                    return rows[:limit] if limit else rows
            print(f"[db_list] {table}: {exc}")
            raise ApiError(_friendly_db_error(exc), 502) from exc
        rows = [dict(r) for r in (res.data or [])]
        if order and not sql_order:
            rows = _sort_rows(rows, order, descending)
            if limit:
                rows = rows[:limit]
        return rows
    rows = [dict(r) for r in _load_mock().get(table, [])]
    if filters:
        rows = [r for r in rows if all(_matches(r.get(k), v) for k, v in filters.items())]
    if order:
        rows.sort(key=lambda r: _sort_key(r.get(order)), reverse=descending)
    return rows[:limit] if limit else rows


def db_get(table, row_id):
    if row_id is None:
        return None
    if supabase:
        try:
            res = supabase.table(table).select("*").eq("id", row_id).limit(1).execute()
            return dict(res.data[0]) if res.data else None
        except Exception as exc:                                          # noqa: BLE001
            print(f"[db_get] {table}: {exc}")
            raise ApiError(_friendly_db_error(exc), 502) from exc
    for r in _load_mock().get(table, []):
        if str(r.get("id")) == str(row_id):
            return dict(r)
    return None


def _clean_for_table(table, payload):
    cols = SUPA_COLUMNS.get(table)
    out = {}
    for k, v in (payload or {}).items():
        if k == "id" or k.startswith("_"):
            continue
        if cols is None or k in cols or (table == "employees" and k in LEGACY_EMPLOYEE_COLUMNS):
            out[k] = v
    return out


def db_insert(table, payload):
    if supabase:
        clean = _clean_for_table(table, payload)
        try:
            res = supabase.table(table).insert(clean).execute()
            return dict(res.data[0]) if res.data else clean
        except Exception as exc:                                          # noqa: BLE001
            print(f"[db_insert] {table}: {exc}")
            raise ApiError(_friendly_db_error(exc), 400) from exc
    row = dict(payload)
    row["id"] = row.get("id") or uuid.uuid4().hex[:10]
    row.setdefault("created_at", str(today()))
    _load_mock().setdefault(table, []).append(row)
    _save_mock()
    return dict(row)


def db_update(table, row_id, payload):
    if supabase:
        clean = _clean_for_table(table, payload)
        try:
            res = supabase.table(table).update(clean).eq("id", row_id).execute()
        except Exception as exc:                                          # noqa: BLE001
            print(f"[db_update] {table}: {exc}")
            raise ApiError(_friendly_db_error(exc), 400) from exc
        if not res.data:
            raise ApiError(f"No {table} row with id {row_id}", 404)
        return dict(res.data[0])
    rows = _load_mock().setdefault(table, [])
    for i, r in enumerate(rows):
        if str(r.get("id")) == str(row_id):
            rows[i] = {**r, **payload}
            _save_mock()
            return dict(rows[i])
    raise ApiError(f"No {table} row with id {row_id}", 404)


def db_delete(table, row_id):
    if supabase:
        try:
            supabase.table(table).delete().eq("id", row_id).execute()
            return True
        except Exception as exc:                                          # noqa: BLE001
            print(f"[db_delete] {table}: {exc}")
            raise ApiError(_friendly_db_error(exc), 400) from exc
    rows = _load_mock().get(table, [])
    left = [r for r in rows if str(r.get("id")) != str(row_id)]
    if len(left) == len(rows):
        raise ApiError(f"No {table} row with id {row_id}", 404)
    _load_mock()[table] = left
    _save_mock()
    return True


def _friendly_db_error(exc):
    text = str(exc)
    lowered = text.lower()
    # name the missing object: "Your database is missing a column" told nobody *which* one,
    # and the screen looked like an app crash rather than a schema that is one version behind
    missing_col = re.search(r'column (?:[a-z_]+\.)?([a-z_0-9]+) does not exist', text, re.I)
    missing_rel = re.search(r'relation "?([a-z_0-9]+)"? does not exist', text, re.I)
    if missing_rel:
        return (f"Your database has no {missing_rel.group(1)} table. Run supabase_setup.sql in the "
                "Supabase SQL editor (it creates what is absent and never rewrites rows), then reload.")
    if missing_col or "could not find the" in lowered:
        which = missing_col.group(1) if missing_col else "a column"
        return (f"Your database is missing {which}. Run supabase_setup.sql in the Supabase SQL editor "
                "- it only adds what is missing and never touches existing rows - then reload. "
                "GET /api/schema-check lists every gap.")
    if "column" in lowered and "does not exist" in lowered:
        return ("Your database is missing a column this version needs. Run supabase_setup.sql in the "
                "Supabase SQL editor (it adds missing columns only), then reload. GET /api/schema-check "
                "lists every gap.")
    if "invalid input syntax for type uuid" in lowered:
        return "A record points at a row that no longer exists. Re-save it with a valid selection."
    if "duplicate key" in lowered:
        match = re.search(r"Key \(([^)]+)\)=\(([^)]+)\)", text)
        return f"Duplicate value: {match.group(1)} = {match.group(2)} already exists." if match else "That record already exists."
    return text[:400]


# =================================================================== formatting
def parse_day(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def fmt_day(value, fmt="%d %b %Y"):
    d = parse_day(value)
    if not d:
        return "-"
    out = d.strftime(fmt)
    return out.replace(" 0", " ") if "%d" in fmt else out


def norm_time(value):
    """`09:12` from an <input type=time> or a stray label -> the `HH:MM:SS` the TIME column keeps.

    Without this, a row edited through the UI holds "09:12" while every other row holds
    "09:12:00", and the two modes (Postgres normalises, the demo store does not) then disagree.
    """
    if value in (None, ""):
        return None
    text = str(value).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if not m:
        return text
    return f"{int(m.group(1)) % 24:02d}:{m.group(2)}:{m.group(3) or '00'}"


def fmt_time(value, fallback="-"):
    """Accept an ISO timestamp, a bare HH:MM[:SS] time, or a legacy '09:32 AM' label."""
    if not value:
        return fallback
    text = str(value)
    m = re.search(r"(?:[T ]|^)(\d{1,2}):(\d{2})", text)
    if not m:
        return text
    hh, mm = int(m.group(1)), int(m.group(2))
    tail = text.strip()[-2:].upper()
    if tail == "PM" and hh < 12:                       # a legacy "06:45 PM" label: trust the suffix
        hh += 12
    elif tail == "AM" and hh == 12:
        hh = 0
    suffix = "AM" if hh < 12 else "PM"
    return f"{hh % 12 or 12:02d}:{mm:02d} {suffix}"


def minutes_of(value):
    """Minutes since midnight for an ISO timestamp, HH:MM[:SS] or '09:32 AM'."""
    if not value:
        return None
    text = str(value)
    m = re.search(r"(?:[T ]|^)(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    hh = int(m.group(1))
    if text.strip()[-2:].upper() == "PM" and hh < 12:
        hh += 12
    elif text.strip()[-2:].upper() == "AM" and hh == 12:
        hh = 0
    return hh * 60 + int(m.group(2))


def comp_map(value):
    """Competency scores are stored as a JSON object so jsonb (Supabase) and the demo store agree."""
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except ValueError:
            return {}
    if not isinstance(value, dict):
        return {}
    return {str(k).strip(): round(money(v), 2) for k, v in value.items()}


def money(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def inr(v, decimals=0):
    return f"₹{money(v):,.{decimals}f}"


def initials(name):
    parts = [p for p in (name or "").replace(".", " ").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def shift_minutes(hhmmss, default=0):
    return minutes_of(hhmmss) if hhmmss else default


# ------------------------------------------------- reference maps (cached per request)
@app.before_request
def _init_request_cache():
    g._cache = {}


def _cached(name, fn):
    cache = getattr(g, "_cache", None)
    if cache is None:
        return fn()
    if name not in cache:
        cache[name] = fn()
    return cache[name]


def employees_map():
    return _cached("employees", lambda: {str(e.get("id")): e for e in db_list("employees")})


def dept_map():
    return _cached("depts", lambda: {str(d["id"]): d.get("name") for d in db_list("departments")})


def designation_map():
    return _cached("desigs", lambda: {str(d["id"]): d.get("title") for d in db_list("designations")})


def leave_type_map():
    return _cached("leave_types", lambda: {str(t["id"]): t for t in db_list("leave_types")})


def project_map():
    return _cached("projects", lambda: {str(p["id"]): p for p in db_list("projects")})


def shift_row():
    rows = _cached("shifts", lambda: db_list("shifts"))
    return rows[0] if rows else {"name": "General Shift", "start_time": "09:30:00", "end_time": "18:30:00",
                                 "grace_minutes": 15}


def employee_display(emp_id):
    if not emp_id:
        return None
    emp = employees_map().get(str(emp_id))
    if not emp:
        return None
    return {"id": emp.get("id"), "full_name": emp.get("full_name"), "employee_code": emp.get("employee_code"),
            "email": emp.get("email"), "avatar": emp.get("avatar") or initials(emp.get("full_name")),
            "department": emp.get("department") or dept_map().get(str(emp.get("department_id")), ""),
            "designation": emp.get("designation") or designation_map().get(str(emp.get("designation_id")), ""),
            "status": emp.get("status"), "work_location": emp.get("work_location")}


def enrich_employee_row(emp):
    """Add the friendly labels the UI expects (department name, designation, manager name, avatar)."""
    row = dict(emp)
    row["department"] = row.get("department") or dept_map().get(str(row.get("department_id")), "") or "-"
    row["designation"] = row.get("designation") or designation_map().get(str(row.get("designation_id")), "") or "-"
    if row.get("manager_id"):
        mgr = employees_map().get(str(row["manager_id"]))
        row["manager"] = (mgr or {}).get("full_name") or row.get("manager") or "-"
        row["manager_avatar"] = (mgr or {}).get("avatar") or initials((mgr or {}).get("full_name"))
        row["manager_id"] = str(row["manager_id"])
    else:
        row["manager"] = row.get("manager") if row.get("manager") not in ("-", None) else "-"
        row["manager_avatar"] = ""
    row["avatar"] = row.get("avatar") or initials(row.get("full_name"))
    row["tenure"] = tenure_label(row.get("date_of_joining"), row.get("exit_date"))
    row["date_of_joining_label"] = fmt_day(row.get("date_of_joining"))
    row["date_of_birth_label"] = fmt_day(row.get("date_of_birth"), "%d %b")
    if row.get("exit_date"):
        row["status"] = "Exited"
    row["has_own_password"] = bool(row.pop("password_hash", None))   # the hash never leaves the server
    return row


def tenure_label(joining, exit_day=None):
    start = parse_day(joining)
    if not start:
        return "-"
    end = parse_day(exit_day) or today()
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    months = max(months, 0)
    yrs, rem = divmod(months, 12)
    if yrs and rem:
        return f"{yrs} yr {rem} m"
    return f"{yrs} yr" if yrs else f"{rem} m"


def next_anniversary(dob, doj, kind):
    """Days until the next birthday / work anniversary."""
    base = parse_day(dob if kind == "birthday" else doj)
    if not base:
        return None
    ref = today()
    year = ref.year
    try:
        nxt = date(year, base.month, base.day)
    except ValueError:
        nxt = date(year, base.month, base.day - 1)
    if nxt < ref:
        try:
            nxt = date(year + 1, base.month, base.day)
        except ValueError:
            nxt = date(year + 1, base.month, base.day - 1)
    return {"date": nxt.isoformat(), "days_left": (nxt - ref).days, "turning": nxt.year - base.year,
            "years_completed": (nxt.year - base.year - 1) if nxt > ref and ref.month == base.month and ref.day == base.day
            else (nxt.year - base.year - (1 if nxt > ref else 0))}


# =================================================================== auth
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "Authentication required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = session.get("user")
        if not user:
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"success": False, "error": "Authentication required"}), 401
            return redirect(url_for("login"))
        if user.get("role") != "HR Admin":
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"success": False, "error": "This action is restricted to HR Admins."}), 403
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# /api/login-hint is the one API route the sign-in page may call before logging in, and only in demo mode.
PUBLIC_API_PATHS = {"/api/health", "/api/login-hint"}


@app.before_request
def require_auth_for_api():
    if request.path.startswith("/api/") and request.path not in PUBLIC_API_PATHS:
        if "user" not in session:
            return jsonify({"success": False, "error": "Authentication required - please log in"}), 401


def is_admin():
    return (session.get("user") or {}).get("role") == "HR Admin"


def modules_for_role(role):
    return list(ALL_MODULES) if role == "HR Admin" else list(EMPLOYEE_MODULES)


def allowed_modules():
    return modules_for_role((session.get("user") or {}).get("role"))


def verify_employee_password(emp, password):
    """The employee's own hash once they have set one; the shared bootstrap password until then.

    The fallback is what keeps the demo (and any account HR has not onboarded to passwords yet)
    signing in, while every account that sets its own stops sharing the bootstrap one.
    """
    if not password:
        return False
    stored = (emp or {}).get("password_hash") or ""
    if stored:
        try:
            return check_password_hash(stored, password)
        except Exception:                                     # hash written by another tool/version
            return False
    return password == EMPLOYEE_PASSWORD


def has_own_password(emp):
    return bool((emp or {}).get("password_hash"))


def new_temp_password():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "Ekkaa-" + "".join(secrets.choice(alphabet) for _ in range(8))


def hr_area(f):
    """For the areas of the app an employee must not reach at all (directory, hiring, reports)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            raise ApiError("This area is for HR Admins. Ask HR if you need this information.", 403)
        return f(*args, **kwargs)
    return decorated


def current_employee():
    """Employee record for the signed-in user (session id, then email, then the demo fallback)."""
    user = session.get("user") or {}
    emps = employees_map()
    emp_id = user.get("employee_id")
    if emp_id and str(emp_id) in emps:
        return emps[str(emp_id)]
    email = (user.get("email") or "").strip().lower()
    rows = db_list("employees")
    if email:
        for e in rows:
            if (e.get("email") or "").strip().lower() == email:
                return e
    # HR Admin logins without a payroll record act on DEFAULT_EMPLOYEE_EMAIL (demo convenience)
    fallback = next((e for e in rows if (e.get("email") or "").strip().lower() == DEFAULT_EMPLOYEE_EMAIL), None)
    return fallback or next((e for e in rows if e.get("status") != "Exited"), None)


def acting_employee_id():
    emp = current_employee()
    return (emp or {}).get("id")


def scoped_employee_id():
    """?employee_id is honoured for HR Admins only; employees are always scoped to themselves."""
    requested = request.args.get("employee_id") or (request.get_json(silent=True) or {}).get("employee_id")
    if is_admin():
        if requested and requested not in ("All", "all", ""):
            return requested
        return None                                     # None => every employee (admin view)
    return acting_employee_id()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify({"success": False, "error": err.message}), err.status


@app.errorhandler(404)
def handle_404(err):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Endpoint not found"}), 404
    return err


@app.errorhandler(Exception)
def handle_unexpected_error(err):
    """A crash inside an /api route still has to answer JSON.

    Without this Flask sends its HTML debug page, and the toast on the screen pasted the whole
    `<!doctype html> ... 500 Internal Server Error` at the user instead of a sentence they can act on.
    The traceback is logged, HTTP exceptions (404/405/redirects) pass through untouched, and pages
    keep Flask's own handling.
    """
    if isinstance(err, HTTPException):
        return err            # a 404/405 keeps its own status; re-raising here would wrap it into a 500
    if not request.path.startswith("/api/"):
        raise err             # pages keep Flask's normal error rendering
    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    detail = f"{type(err).__name__}: {err}" if app.debug else "The request failed unexpectedly."
    return jsonify({"success": False, "error": f"{detail} The server log has the traceback."}), 500


@app.errorhandler(413)
def handle_too_large(err):
    return jsonify({"success": False, "error": "That file is too large for the upload limit"}), 413


# =================================================================== pages
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data = request.get_json() if request.is_json else request.form
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        def _fail(msg="Access restricted - invalid email or password. Only authorized users can sign in."):
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 401
            flash(msg, "error")
            return redirect(url_for("login"))

        emp = next((e for e in db_list("employees") if (e.get("email") or "").strip().lower() == email), None)
        if emp is not None and (emp.get("status") or "Active") == "Exited":
            return _fail("This account is not active any more. Contact HR if you need access back.")
        if email in ADMIN_EMAILS:
            if password != ADMIN_PASSWORD and not (has_own_password(emp) and verify_employee_password(emp, password)):
                return _fail()
            role = "HR Admin"
        elif emp is not None and verify_employee_password(emp, password):
            role = "Employee"
        else:
            return _fail()

        name = (emp.get("full_name") if emp else None) or ("Admin User" if role == "HR Admin" else email.split("@")[0].title())
        avatar = ((emp.get("avatar") or "").strip() if emp else "") or initials(name)
        session.clear()
        session["user"] = {"email": email, "name": name, "role": role, "avatar": avatar,
                           "employee_id": (emp or {}).get("id"),
                           "department": dept_map().get(str((emp or {}).get("department_id")), ""),
                           "designation": designation_map().get(str((emp or {}).get("designation_id")), ""),
                           "employee_code": (emp or {}).get("employee_code"),
                           "modules": modules_for_role(role),
                           "must_set_password": role == "Employee" and not has_own_password(emp)}
        if request.is_json:
            return jsonify({"success": True, "redirect": "/dashboard", "role": role})
        return redirect(url_for("dashboard"))
    return render_template("login.html", mock_mode=supabase is None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = dict(session.get("user") or {})
    user["is_admin"] = is_admin()
    emp = current_employee() or {}
    user["employee_id"] = emp.get("id")
    user["full_name"] = emp.get("full_name") or user.get("name")
    user["designation"] = user.get("designation") or designation_map().get(str(emp.get("designation_id")), "") or "HR Admin"
    user["department"] = user.get("department") or dept_map().get(str(emp.get("department_id")), "") or "Human Resources"
    user["employee_code"] = user.get("employee_code") or emp.get("employee_code") or "-"
    user["avatar"] = user.get("avatar") or initials(user.get("full_name"))
    user["mock_mode"] = supabase is None
    user.setdefault("modules", allowed_modules())
    return render_template("dashboard.html", user=user)


# =================================================================== session / health
@app.route("/api/session")
def api_session():
    emp = current_employee()
    return jsonify({"user": session.get("user"), "is_admin": is_admin(), "modules": allowed_modules(),
                    # the browser's clock is the container's (UTC); the office's date is what every
                    # date default in the UI has to follow, so it is handed out with the session
                    "office_date": str(today()), "office_time": now_local().strftime("%H:%M:%S"),
                    "must_set_password": bool((session.get("user") or {}).get("must_set_password")),
                    "security": {"has_own_password": has_own_password(emp), "min_length": MIN_PASSWORD_LENGTH},
                    "employee": employee_display((emp or {}).get("id")), "mock_mode": supabase is None})


@app.route("/api/login-hint")
def api_login_hint():
    """Demo-mode convenience for the sign-in page: one employee email that exists in the sample data.
    Never reveals a password, and returns nothing at all once the app is on a real database."""
    if supabase is not None:
        return jsonify({"email": None, "name": None})
    for e in db_list("employees", order="full_name"):
        email = str(e.get("email") or "").strip().lower()
        if email and e.get("status") == "Active" and email not in ADMIN_EMAILS:
            return jsonify({"email": email, "name": e.get("full_name")})
    return jsonify({"email": None, "name": None})


def column_exists(table, column):
    """Ask PostgREST directly whether one column can be selected (True / False / None if unreadable).

    Comparing SUPA_COLUMNS with a sample row is only a *candidate* list: a nullable column that is
    NULL in every sampled row simply has no key, so it has to be confirmed before anyone is told to
    run SQL.
    """
    if not supabase:
        return None
    if column in _ABSENT_COLUMNS.get(table, ()):
        return False
    probed = _COLUMN_PROBE.get((table, column))
    if probed is not None:
        return probed
    try:
        supabase.table(table).select(column).limit(1).execute()
    except Exception as exc:                                              # noqa: BLE001
        if "does not exist" in str(exc).lower():
            mark_column_absent(table, column)
            _COLUMN_PROBE[(table, column)] = False
            return False
        return None                                                        # unreadable, not missing
    _COLUMN_PROBE[(table, column)] = True
    return True


def order_is_usable(table, column):
    """Can this database be asked to ORDER BY `column`? False means sort the rows in Python.

    A sample row answers it when the table has rows. An *empty* table answers nothing, which is how
    the first version of this guard still 502'd on the Performance tab: `feedbacks` and `checkins`
    hold no rows yet, so `sample_columns` came back unknown, the ORDER BY went through, and
    Postgres refused the `date` column the deployed schema does not have. So fall back to probing
    the single column, and remember the answer.
    """
    if not supabase:
        return True
    known = sample_columns(table)
    if known is not None:
        if column in known:
            return True
        mark_column_absent(table, column)
        return False
    return column_exists(table, column) is not False


@app.route("/api/schema-check")
@admin_required
def api_schema_check():
    """Compare the connected database with what this build of the app expects.

    This is the answer to the one question a "run supabase_setup.sql" toast should have asked
    back: is my schema actually behind, and by how much. Read-only; each candidate gap is
    confirmed with a direct probe so a column that is merely NULL is never reported as missing.
    """
    tables_missing, columns_missing, unverifiable = [], {}, []
    if not supabase:
        return jsonify({"mode": "demo", "tables_expected": len(SUPA_COLUMNS), "tables_missing": [],
                        "columns_missing": {}, "unverifiable": [], "gaps": 0, "up_to_date": True,
                        "advice": "Demo store: the tables are rebuilt from this build on boot, "
                                  "so there is nothing to migrate. Connect Supabase to use this check."})
    for table, wanted in sorted(SUPA_COLUMNS.items()):
        try:
            res = supabase.table(table).select("*").limit(500).execute()
        except Exception as exc:                                          # noqa: BLE001
            if "does not exist" in str(exc).lower():
                tables_missing.append(table)
            else:
                unverifiable.append({"table": table, "reason": _friendly_db_error(exc)[:160]})
            continue
        seen = set()
        for row in (res.data or []):
            seen.update(row.keys())
        for column in sorted(set(wanted) - seen):
            if column_exists(table, column) is False:
                columns_missing.setdefault(table, []).append(column)
    gaps = len(tables_missing) + sum(len(v) for v in columns_missing.values())
    return jsonify({
        "mode": "supabase",
        "tables_expected": len(SUPA_COLUMNS),
        "tables_missing": tables_missing,
        "columns_missing": {k: v for k, v in sorted(columns_missing.items())},
        "unverifiable": unverifiable,
        "gaps": gaps,
        "up_to_date": gaps == 0,
        "advice": ("Nothing to do - the database matches this version." if not gaps else
                   "Run supabase_setup.sql in the Supabase SQL editor. It is idempotent: it creates the "
                   "missing tables and adds only the columns listed here, and it never updates or deletes "
                   "rows you already have."),
    })


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timezone": APP_TZ_LABEL,
                    "office_time": now_local().strftime("%H:%M:%S"),
                    "wall_clock_offset_minutes": offset_minutes(),
                    "supabase_connected": supabase is not None, "mock_mode": supabase is None,
                    "supabase_key_source": supabase_key_source, "supabase_error": supabase_error,
                    "storage": (f"supabase:{SUPABASE_BUCKET}" if (supabase and SUPABASE_BUCKET) else "local:uploads"),
                    "timestamp": now_local().isoformat()})


# =================================================================== csv helper
def json_scalar(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v


def csv_response(name, columns, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c.replace("_", " ").title() for c in columns])
    for r in rows:
        writer.writerow([json_scalar(r.get(c)) for c in columns])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}_{today().isoformat()}.csv"})


# =================================================================== home / stats
def _attendance_on(rows, day):
    key = day.isoformat()
    return [r for r in rows if str(r.get("date") or "")[:10] == key]


def _on_leave_on(leaves, day):
    day_s = day.isoformat()
    out = {}
    for l in leaves:
        if l.get("status") != "Approved":
            continue
        if str(l.get("start_date") or "")[:10] <= day_s <= str(l.get("end_date") or l.get("start_date") or "")[:10]:
            out[str(l.get("employee_id"))] = l
    return out


def day_attendance(rows, day, grace_minutes=30):
    """Bucket one day of attendance records into present / wfh / half / absent / late."""
    buckets = {"present": [], "wfh": [], "half": [], "absent": [], "late": [], "on_leave": []}
    for r in _attendance_on(rows, day):
        st, eid = r.get("status"), str(r.get("employee_id"))
        if st == "On Leave":
            buckets["on_leave"].append(eid)
        if st == "Present":
            buckets["present"].append(eid)
        elif st == "Work From Home":
            buckets["wfh"].append(eid)
        elif st == "Half Day":
            buckets["half"].append(eid)
        elif st == "Absent":
            buckets["absent"].append(eid)
        ci = minutes_of(r.get("clock_in"))
        if ci is not None and ci > (9 * 60 + 30) and st in ("Present", "Work From Home", "Half Day"):
            buckets["late"].append(eid)
    return buckets


@app.route("/api/stats")
def api_stats():
    employees = db_list("employees")
    attendance = db_list("attendance")
    leaves = db_list("leave_requests")
    jobs = db_list("jobs")
    day = today()

    active = [e for e in employees if e.get("status") != "Exited" and not e.get("exit_date")]
    exited = [e for e in employees if e.get("status") == "Exited" or e.get("exit_date")]
    on_leave_map = _on_leave_on(leaves, day)
    buckets = day_attendance(attendance, day)

    active_ids = {str(e.get("id")) for e in active}
    on_leave_ids = sorted((set(list(on_leave_map)) | {str(e["id"]) for e in active if (e.get("status") or "").lower() == "on leave"}) & active_ids)
    attended = (set(buckets["present"]) | set(buckets["wfh"]) | set(buckets["half"])) & active_ids
    present_ids = sorted(attended - set(on_leave_ids))
    absent_ids = ((set(buckets["absent"]) | {str(e["id"]) for e in active if str(e["id"]) not in attended}) & active_ids) - set(on_leave_ids) - attended
    expected = max(len(active) - len(on_leave_ids) - len(set(buckets["half"]) & active_ids) * 0, 0)
    attendance_rate = min(100.0, round(len(present_ids) / expected * 100, 1)) if expected else 0.0

    month_start = day.replace(day=1)
    joined_this_month = [e for e in employees if month_start <= (parse_day(e.get("date_of_joining")) or month_start - timedelta(days=1)) <= day]
    exited_this_month = [e for e in exited if month_start <= (parse_day(e.get("exit_date")) or month_start - timedelta(days=1)) <= day]

    pending_leaves = [l for l in leaves if l.get("status") == "Pending"]
    pending_regs = [r for r in db_list("attendance_regularizations", {"status": "Pending"})]
    pending_expenses = [r for r in db_list("reimbursements", {"status": "Pending"})]
    pending_docs = [d for d in db_list("documents", {"status": "Pending"}) if d.get("visibility") != "Employee only"]
    ts_pending = [t for t in db_list("timesheets", {"status": "Submitted"})]
    open_jobs = [j for j in jobs if j.get("status") == "Open"]
    open_positions = sum(int(j.get("openings") or 0) for j in open_jobs)
    applicants = len([c for c in db_list("candidates") if c.get("stage") not in ("Rejected", "Hired")])

    if not is_admin():
        # An employee's counters describe their own queue, so the Inbox badge, the "waiting on
        # approval" card and the list the inbox renders cannot disagree with each other.
        me_id = str(acting_employee_id() or "")

        def _mine(rows):
            return [r for r in rows if str(r.get("employee_id")) == me_id]
        pending_leaves = _mine(pending_leaves)
        pending_regs = _mine(pending_regs)
        pending_expenses = _mine(pending_expenses)
        pending_docs = _mine(pending_docs)
        ts_pending = _mine(ts_pending)

    lt_map, emp_map = leave_type_map(), employees_map()

    # --- "Today" widget -------------------------------------------------
    birthdays, anniversaries, upcoming_birthdays = [], [], []
    for e in active:
        nb = next_anniversary(e.get("date_of_birth"), None, "birthday")
        if nb:
            person = {"name": e.get("full_name"), "avatar": e.get("avatar") or initials(e.get("full_name")),
                      "turning": nb["turning"], "employee_id": e.get("id")}
            if nb["days_left"] == 0:
                birthdays.append(person)
            elif nb["days_left"] <= 14:
                upcoming_birthdays.append({**person, "days_left": nb["days_left"]})
        na = next_anniversary(None, e.get("date_of_joining"), "anniversary")
        if na and na["days_left"] == 0 and na["years_completed"] > 0:
            anniversaries.append({"name": e.get("full_name"), "years": na["years_completed"],
                                  "avatar": e.get("avatar") or initials(e.get("full_name")), "employee_id": e.get("id")})
    upcoming_birthdays.sort(key=lambda x: x["days_left"])

    on_leave_today = []
    for eid in on_leave_ids:
        e = emp_map.get(str(eid)) or {}
        l = on_leave_map.get(str(eid)) or {}
        on_leave_today.append({"name": e.get("full_name", "Employee"), "avatar": e.get("avatar") or initials(e.get("full_name")),
                               "leave_type": (lt_map.get(str(l.get("leave_type_id"))) or {}).get("name") or l.get("leave_type") or "On Leave",
                               "end_date": (l.get("end_date") or "")[:10], "employee_id": eid})

    # --- department distribution ---------------------------------------
    dept_count = {}
    for e in active:
        dept = e.get("department") or dept_map().get(str(e.get("department_id"))) or "Unassigned"
        dept_count[dept] = dept_count.get(dept, 0) + 1

    # --- real attendance trend (last 14 days) ---------------------------
    off_days = {fmt_day(h.get("date"), "%Y-%m-%d") for h in db_list("holidays")}
    trend = {"labels": [], "present_pct": [], "present_count": [], "on_leave": [], "late": []}
    for offset in range(13, -1, -1):
        d = day - timedelta(days=offset)
        if d.weekday() == 6 or str(d) in off_days:     # Sundays and holidays are not working days
            continue
        b = day_attendance(attendance, d)
        on_leave_d = _on_leave_on(leaves, d)
        attended_d = ((set(b["present"]) | set(b["wfh"]) | set(b["half"])) - set(b["on_leave"])) & active_ids
        # people who were away are taken out of the denominator, exactly like the today card
        away = (set(b["on_leave"]) | set(on_leave_d)) & active_ids
        denom = max(len(active) - len(away), 1)
        trend["labels"].append(d.strftime("%a %d"))
        trend["present_count"].append(len(attended_d))
        trend["present_pct"].append(min(100.0, round(len(attended_d) / denom * 100, 1)))
        trend["on_leave"].append(len(away))
        trend["late"].append(len(b["late"]))
    yest = day - timedelta(days=1)
    yest_b = day_attendance(attendance, yest)
    yest_attended = (set(yest_b["present"]) | set(yest_b["wfh"]) | set(yest_b["half"])) & active_ids
    present_delta = len(present_ids) - len(yest_attended)

    # --- my clock state --------------------------------------------------
    my_emp = current_employee() or {}
    mine = next((r for r in _attendance_on(attendance, day) if str(r.get("employee_id")) == str(my_emp.get("id"))), None)
    shift = shift_row()
    start_min = minutes_of(shift.get("start_time")) or 570
    end_min = minutes_of(shift.get("end_time")) or 1110
    brk = int((mine or {}).get("break_minutes") or 45)
    my_ci = minutes_of((mine or {}).get("clock_in"))
    my_co = minutes_of((mine or {}).get("clock_out"))
    worked = 0.0
    if my_ci is not None:
        if my_co is not None:
            worked = round(max(0.0, (my_co - my_ci - brk) / 60), 2)
        else:
            # live elapsed time; demo rows carry an "as of" total for when the wall clock is behind them
            local = now_local()
            now_min = max(local.hour * 60 + local.minute, my_ci)
            worked = round(max((now_min - my_ci - brk) / 60, money((mine or {}).get("work_hours"))), 2)
    shift_hours = max(0.0, (end_min - start_min) / 60 - brk / 60)
    my_time = {
        "employee": employee_display(my_emp.get("id")),
        "date_label": day.strftime("%A, %d %b %Y"),
        "status": (mine or {}).get("status") or "Not clocked in",
        "clock_in": fmt_time((mine or {}).get("clock_in"), "--"),
        "clock_out": fmt_time((mine or {}).get("clock_out"), "--"),
        "clocked_in": bool(mine and mine.get("clock_in") and not mine.get("clock_out")),
        "clocked_out": bool(mine and mine.get("clock_out")),
        "worked_hours": worked,
        "break_minutes": brk if mine else 0,
        "required_hours": round(shift_hours, 1),
        "shortfall_minutes": max(0, int((shift_hours - worked) * 60)) if mine else int(shift_hours * 60),
        "overtime_hours": round(max(0.0, worked - shift_hours), 1),
        "is_late": bool((mine or {}).get("is_late")) or (my_ci or 0) > start_min + int(shift.get("grace_minutes") or 15),
        "shift_label": f"{shift.get('name', 'General Shift')} • {fmt_time(shift.get('start_time'))} - {fmt_time(shift.get('end_time'))}",
        "record_id": (mine or {}).get("id"),
        "regularization_status": (mine or {}).get("regularization_status") or "None",
        "clock_in_location": parse_punch_location((mine or {}).get("clock_in_location"))["label"],
        "clock_out_location": parse_punch_location((mine or {}).get("clock_out_location"))["label"],
    }

    holidays = sorted([h for h in db_list("holidays") if (parse_day(h.get("date")) or day) >= day], key=lambda x: str(x.get("date")))
    next_holiday = holidays[0] if holidays else None

    return jsonify({
        "total_employees": len(active),
        "exited_employees": len(exited),
        "joined_this_month": len(joined_this_month),
        "exited_this_month": len(exited_this_month),
        "present_today": len(present_ids),
        "wfh_today": len(set(buckets["wfh"]) - set(on_leave_ids)),
        "half_day_today": len(set(buckets["half"]) - set(on_leave_ids)),
        "absent_today": len(absent_ids),
        "late_today": len(set(buckets["late"]) - set(on_leave_ids)),
        "on_leave": len(on_leave_ids),
        "expected_today": expected,
        "attendance_rate": attendance_rate,
        "present_delta": present_delta,
        "pending_leaves": len(pending_leaves),
        "pending_regularizations": len(pending_regs),
        "pending_expenses": len(pending_expenses),
        "pending_documents": len(pending_docs),
        "pending_timesheets": len(ts_pending),
        "pending_total": len(pending_leaves) + len(pending_regs) + len(pending_expenses) + len(pending_docs) + len(ts_pending),
        "open_positions": open_positions,
        "open_jobs": len(open_jobs),
        "applicants": applicants,
        "department_distribution": dept_count,
        "attendance_trend": trend,
        "today": {
            "date_label": day.strftime("%A, %d %b %Y"),
            "short_label": day.strftime("%d %b"),
            "birthdays": birthdays,
            "anniversaries": anniversaries,
            "upcoming_birthdays": upcoming_birthdays[:4],
            "on_leave": on_leave_today,
            "holidays_left": len(holidays),
            "next_holiday": ({"name": next_holiday.get("name"), "date": (next_holiday.get("date") or "")[:10],
                              "days_left": (parse_day(next_holiday.get("date")) - day).days} if next_holiday else None),
        },
        "my_time": my_time,
        "pending_actions": build_pending_actions(lean=True),
    })


# =================================================================== lookups
_COLUMN_CACHE = {}


def sample_columns(table):
    """Column names the connected database really has, or None when it cannot be told.

    PostgREST will not expose information_schema, so one sample row is the cheapest honest answer:
    its keys are real columns. An empty table gives nothing back and the caller then behaves exactly
    as before. Cached per request-process because the answer cannot change under us.
    """
    if table in _COLUMN_CACHE:
        return _COLUMN_CACHE[table]
    found = None
    if supabase:
        try:
            res = supabase.table(table).select("*").limit(1).execute()
            if res.data:
                found = set(res.data[0].keys())
        except Exception:                                                # noqa: BLE001
            found = None
    _COLUMN_CACHE[table] = found
    return found


_COLUMN_PROBE = {}
_ABSENT_COLUMNS = {}


def _names_missing_column(exc, column):
    text = str(exc).lower()
    return "does not exist" in text and re.search(rf"\b{re.escape(column)}\b", text) is not None


def mark_column_absent(table, column):
    _ABSENT_COLUMNS.setdefault(table, set()).add(column)


def _sort_key(value):
    """A sort key that never raises, so an unsortable column cannot silently stay unsorted.

    Empty and missing values sort last; numbers rank with numbers, text and dates with text, and
    lists/dicts with their JSON. The rank prefix is what keeps the groups from ever being compared
    to each other: mixing a `date` with a string used to raise TypeError inside the sort, which the
    demo store swallowed and Postgres reported as a missing column.
    """
    if value is None or value == "":
        return (1, 0.0, "")
    if isinstance(value, bool):
        return (0, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    if isinstance(value, date):                    # datetime is a date subclass, so both land here
        return (0, 0.0, value.isoformat())
    if isinstance(value, (list, dict)):
        return (2, 0.0, json.dumps(value, sort_keys=True, default=str))
    text = str(value).strip()
    try:
        return (0, float(text), "")                # "9" before "10", not "10" before "9"
    except ValueError:
        return (0, 0.0, text)


def _sort_rows(rows, key, descending):
    return sorted(rows, key=lambda r: _sort_key(r.get(key)), reverse=descending)


@app.route("/api/departments")
def api_departments():
    depts = db_list("departments")
    emps = [e for e in db_list("employees") if e.get("status") != "Exited"]
    desigs = db_list("designations")
    out = []
    for d in depts:
        members = [e for e in emps if str(e.get("department_id")) == str(d.get("id"))]
        head = d.get("head_id")
        if not head:
            for e in members:
                title = (designation_map().get(str(e.get("designation_id")), "") or "").lower()
                if title.startswith("head of") or title in ("cto", "cfo", "coo", "ceo"):
                    head = e.get("id")
                    break
        out.append({"id": d.get("id"), "name": d.get("name"), "description": d.get("description"),
                    "head_id": str(head) if head else None,
                    "head": employee_display(head) or (employee_display(members[0]["id"]) if members else None),
                    "employee_count": len(members),
                    "openings": sum(int(j.get("openings") or 0) for j in
                                    db_list("jobs", {"department_id": d.get("id"), "status": "Open"})),
                    "designations": [x.get("title") for x in desigs if str(x.get("department_id")) == str(d.get("id"))]})
    return jsonify(out)


DEPARTMENT_FIELDS = {"name", "description", "head_id"}


def _clean_department(data, current=None):
    """Validate a department form into a write payload (name unique, head must be a person)."""
    name = (data.get("name") or "").strip()
    if not name:
        raise ApiError("A department needs a name")
    if len(name) > 60:
        raise ApiError("Keep the department name under 60 characters")
    clash = next((d for d in db_list("departments") if str(d.get("name")).strip().lower() == name.lower()
                  and str(d.get("id")) != str(current)), None)
    if clash:
        raise ApiError(f"{name} already exists (id {clash.get('id')}) - rename it or edit that one")
    payload = {"name": name, "description": (data.get("description") or "").strip()[:300] or None}
    head = data.get("head_id")
    if head in (None, "", "None", "All"):
        payload["head_id"] = None
    else:
        person = db_get("employees", head)
        if not person:
            raise ApiError("The department head must be one of the employees on the list")
        payload["head_id"] = str(head)
    return payload


@app.route("/api/departments", methods=["POST"])
@admin_required
def api_department_create():
    data = request.get_json(silent=True) or {}
    created = db_insert("departments", _clean_department(data))
    return jsonify({"success": True, "department": created,
                    "message": f"{created.get('name')} created - assign people to it from any employee's profile"})


@app.route("/api/departments/<row_id>", methods=["PUT", "DELETE"])
@admin_required
def api_department_row(row_id):
    dept = db_get("departments", row_id)
    if not dept:
        raise ApiError("Department not found", 404)
    if request.method == "DELETE":
        members = [e for e in db_list("employees") if str(e.get("department_id")) == str(row_id)
                   and e.get("status") != "Exited"]
        if members:
            raise ApiError(f"{dept.get('name')} still has {len(members)} person(s) in it - move them to another "
                           "department first (Edit on their profile) and then delete it")
        for table, key in (("designations", "department_id"), ("jobs", "department_id")):
            linked = [r for r in db_list(table) if str(r.get(key)) == str(row_id)]
            for r in linked:
                db_update(table, r["id"], {key: None})
        db_delete("departments", row_id)
        return jsonify({"success": True, "message": f"{dept.get('name')} deleted"})
    data = request.get_json(silent=True) or {}
    updated = db_update("departments", row_id, _clean_department(data, current=row_id))
    return jsonify({"success": True, "department": updated, "message": f"{updated.get('name')} saved"})


@app.route("/api/designations")
def api_designations():
    return jsonify([{"id": d.get("id"), "title": d.get("title"), "department_id": d.get("department_id"),
                     "level": d.get("level")} for d in db_list("designations")])


@app.route("/api/designations", methods=["POST"])
@admin_required
def api_designation_create():
    """Create a designation inline from the Add/Edit employee form: the HR Admin types a
    title that is not on the list yet. If the title already exists (case-insensitive) the
    existing row is returned instead, so the employee gets linked without a duplicate."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        raise ApiError("A designation needs a title")
    if len(title) > 60:
        raise ApiError("Keep the designation title under 60 characters")
    existing = next((d for d in db_list("designations")
                     if str(d.get("title") or "").strip().lower() == title.lower()), None)
    if existing:
        return jsonify({"success": True, "created": False, "designation": existing,
                        "message": f"Using the existing '{existing.get('title')}' designation"})
    dept = data.get("department_id")
    payload = {"title": title, "level": data.get("level") or None,
               "department_id": str(dept) if dept and db_get("departments", dept) else None}
    created = db_insert("designations", payload)
    return jsonify({"success": True, "created": True, "designation": created,
                    "message": f"'{title}' added to the designation list"})


@app.route("/api/shifts")
def api_shifts():
    return jsonify(db_list("shifts"))


@app.route("/api/holidays")
def api_holidays():
    rows = sorted(db_list("holidays"), key=lambda h: str(h.get("date") or ""))
    out = []
    for h in rows:
        d = parse_day(h.get("date"))
        out.append({"id": h.get("id"), "name": h.get("name"), "date": (h.get("date") or "")[:10],
                    "type": h.get("type"), "days_left": (d - today()).days if d else None})
    return jsonify(out)


@app.route("/api/leave-types")
def api_leave_types():
    return jsonify(db_list("leave_types"))


@app.route("/api/lookups")
def api_lookups():
    """One round trip for every dropdown on the page."""
    emps = [e for e in db_list("employees") if e.get("status") != "Exited"]
    return jsonify({
        "departments": db_list("departments"),
        "designations": db_list("designations"),
        "leave_types": db_list("leave_types"),
        "jobs": db_list("jobs"),
        "projects": db_list("projects"),
        "shifts": db_list("shifts"),
        "holidays": db_list("holidays"),
        "employees": [{"id": e.get("id"), "full_name": e.get("full_name"), "employee_code": e.get("employee_code"),
                       "department_id": e.get("department_id"), "designation_id": e.get("designation_id"),
                       "email": e.get("email"), "avatar": e.get("avatar") or initials(e.get("full_name")),
                       "manager_id": e.get("manager_id")} for e in emps],
        "doc_types": DOC_TYPES,
        "required_doc_types": REQUIRED_DOC_TYPES,
        "candidate_stages": CANDIDATE_STAGES,
        "expense_categories": EXPENSE_CATEGORIES,
        # Table/column inventory for the report builder - HR Admins only, and the
        # endpoint itself is @admin_required, so this only drives the picker UI.
        "custom_datasets": [{"table": t, "label": t.replace("_", " ").title(),
                             "columns": sorted(SUPA_COLUMNS[t] | {"id"})} for t in CUSTOM_REPORT_DATASETS] if is_admin() else [],
        "report_schemas": {t: sorted(SUPA_COLUMNS[t] | {"id"}) for t in CUSTOM_REPORT_DATASETS} if is_admin() else {},
        "is_admin": is_admin(),
    })


@app.route("/api/announcements")
def api_announcements():
    rows = sorted(db_list("announcements"), key=lambda a: (not a.get("is_pinned"), -int(a.get("id") or 0) if str(a.get("id") or "").isdigit() else 0))
    out = []
    for a in rows:
        out.append({"id": a.get("id"), "title": a.get("title"), "content": a.get("content"), "type": a.get("type"),
                    "is_pinned": bool(a.get("is_pinned")), "date": fmt_day(a.get("date") or a.get("created_at")),
                    "created_by": a.get("created_by") or "HR"})
    return jsonify(out)


@app.route("/api/announcements", methods=["POST"])
@admin_required
def api_announcement_create():
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        raise ApiError("A headline is required")
    row = {"title": data["title"].strip(), "content": (data.get("content") or "").strip(),
           "type": data.get("type") or "Update", "created_by": session["user"]["name"],
           "is_pinned": bool(data.get("is_pinned")), "date": str(today()),
           "created_at": str(today())}
    return jsonify({"success": True, "announcement": db_insert("announcements", row)})


@app.route("/api/announcements/<row_id>", methods=["PUT", "DELETE"])
@admin_required
def api_announcement_update(row_id):
    if request.method == "DELETE":
        db_delete("announcements", row_id)
        return jsonify({"success": True})
    data = request.get_json(silent=True) or {}
    return jsonify({"success": True, "announcement": db_update("announcements", row_id, data)})


# =================================================================== employees
@app.route("/api/employees")
@hr_area
def api_employees():
    filters = {}
    if request.args.get("department_id"):
        filters["department_id"] = request.args["department_id"]
    rows = db_list("employees", filters or None, order="full_name")
    include_exited = request.args.get("include_exited") in ("1", "true", "yes")
    out = [enrich_employee_row(e) for e in rows if include_exited or (e.get("status") != "Exited" and not e.get("exit_date"))]
    q = (request.args.get("q") or "").strip().lower()
    if q:
        out = [e for e in out if q in " ".join(str(e.get(k) or "") for k in
               ("full_name", "employee_code", "email", "department", "designation", "work_location", "status")).lower()]
    status = request.args.get("status")
    if status and status != "All":
        out = [e for e in out if (e.get("status") or "") == status]
    return jsonify(out)


@app.route("/api/employees/export")
@hr_area
def api_employees_export():
    rows = [enrich_employee_row(e) for e in db_list("employees", order="full_name")]
    cols = ["employee_code", "full_name", "email", "phone", "gender", "date_of_birth", "date_of_joining",
            "department", "designation", "manager", "employment_type", "work_location", "status", "salary_ctc",
            "tenure"]
    return csv_response("employee_directory", cols, rows)


@app.route("/api/employees/<row_id>")
def api_employee_detail(row_id):
    row = db_get("employees", row_id)
    if not row:
        raise ApiError("Employee not found", 404)
    emp = enrich_employee_row(row)
    day = today()
    direct = [enrich_employee_row(e) for e in db_list("employees", {"manager_id": row_id}) if e.get("status") != "Exited"]
    att = [a for a in db_list("attendance", {"employee_id": row_id}) if str(a.get("date") or "")[:7] == day.strftime("%Y-%m")]
    leaves = [enrich_leave_row(l) for l in db_list("leave_requests", {"employee_id": row_id})]
    docs = [d for d in db_list("documents", {"employee_id": row_id})]
    goals = [enrich_goal(x) for x in db_list("goals", {"employee_id": row_id})]
    reviews = [enrich_review(x) for x in db_list("performance_reviews", {"employee_id": row_id})]
    claims = [c for c in db_list("reimbursements", {"employee_id": row_id})]
    att_days = sum(1 for a in att if a.get("status") in ("Present", "Work From Home"))
    # one balance builder for the whole app, so this modal and /api/leave-balances can never disagree
    balances = compute_leave_balances(row_id, day.year)["balances"]
    hours = round(sum(money(a.get("work_hours")) for a in att), 1)
    return jsonify({
        "employee": emp,
        "manager": employee_display(row.get("manager_id")),
        "direct_reports": direct,
        "snapshot": {"attendance_days_this_month": att_days, "hours_this_month": hours,
                     "leaves_this_year": sum(1 for l in leaves if str(l.get("start_date") or "")[:4] == str(day.year) and l.get("status") != "Rejected"),
                     "pending_leaves": sum(1 for l in leaves if l.get("status") == "Pending"),
                     "pending_claims": sum(1 for c in claims if c.get("status") == "Pending"),
                     "documents": len(docs), "documents_pending": sum(1 for d in docs if d.get("status") == "Pending"),
                     "open_goals": sum(1 for g_ in goals if g_.get("status") in ("On Track", "At Risk", "Not Started")),
                     "reviews": len(reviews)},
        "leave_balances": balances,
        "recent_attendance": [{"date": (a.get("date") or "")[:10], "status": a.get("status"),
                               "clock_in": fmt_time(a.get("clock_in")), "clock_out": fmt_time(a.get("clock_out")),
                               "work_hours": money(a.get("work_hours")), "location": a.get("location")}
                              for a in sorted(att, key=lambda x: str(x.get("date")), reverse=True)[:14]],
        "recent_leaves": leaves[:8],
        "documents": docs,
        "goals": goals,
        "reviews": reviews[:4],
    })


EMPLOYEE_FIELDS = {"employee_code", "full_name", "email", "personal_email", "phone", "gender", "date_of_birth",
                   "date_of_joining", "department_id", "designation_id", "manager_id", "employment_type",
                   "work_location", "status", "salary_ctc", "avatar", "blood_group", "nationality", "address",
                   "pan_no", "uan_no", "pf_no", "bank_name", "bank_account_no", "ifsc_code",
                   "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation", "exit_date",
                   "exit_reason"}


@app.route("/api/employees", methods=["POST"])
@admin_required
def api_employee_create():
    data = request.get_json(silent=True) or {}
    for field in ("full_name", "email"):
        if not (data.get(field) or "").strip():
            raise ApiError(f"{field.replace('_', ' ').title()} is required")
    email = data["email"].strip().lower()
    if any((e.get("email") or "").strip().lower() == email for e in db_list("employees")):
        raise ApiError(f"{email} is already in the directory")
    code = (data.get("employee_code") or "").strip().upper() or next_employee_code()
    row = {k: v for k, v in data.items() if k in EMPLOYEE_FIELDS}
    row.update({"email": email, "employee_code": code, "avatar": initials(data["full_name"].strip()),
                "status": data.get("status") or "Active", "date_of_joining": data.get("date_of_joining") or str(today())})
    starter = (data.get("starter_password") or "").strip()
    if starter:
        if len(starter) < MIN_PASSWORD_LENGTH:
            raise ApiError(f"A starter password needs at least {MIN_PASSWORD_LENGTH} characters")
        row["password_hash"] = generate_password_hash(starter)
    created = db_insert("employees", row)
    seed_leave_balances(created)
    return jsonify({"success": True, "employee": enrich_employee_row(created),
                    "message": f"{row['full_name']} can sign in with "
                               + (f"{email} and the starter password you set" if starter
                                  else f"{email} and the shared demo password, and should set their own in Me")})


def next_employee_code():
    nums = []
    for e in db_list("employees"):
        m = re.search(r"(\d+)$", str(e.get("employee_code") or ""))
        if m:
            nums.append(int(m.group(1)))
    return f"EKKA{max(nums or [0]) + 1:03d}"


def seed_leave_balances(employee):
    """Give a new joiner a prorated allowance for the current year."""
    year = today().year
    joining = parse_day(employee.get("date_of_joining")) or today()
    fraction = max(0.0, min(1.0, (date(year, 12, 31) - joining).days / 365))
    for lt in db_list("leave_types"):
        quota = int(lt.get("yearly_quota") or 0)
        if not quota:
            continue
        total = max(1, round(quota * fraction)) if fraction < 1 else quota
        db_insert("leave_balances", {"employee_id": employee["id"], "leave_type_id": lt["id"], "year": year,
                                     "total": total, "used": 0, "pending": 0})


@app.route("/api/employees/<row_id>", methods=["PUT"])
def api_employee_update(row_id):
    data = request.get_json(silent=True) or {}
    existing = db_get("employees", row_id)
    if not existing:
        raise ApiError("Employee not found", 404)
    allowed = EMPLOYEE_FIELDS if is_admin() else SELF_EDITABLE_FIELDS
    payload, blocked = {}, [k for k in data if k not in allowed]
    for k, v in data.items():
        if k in allowed:
            payload[k] = v
    if not payload:
        raise ApiError("Nothing to update")
    if blocked and not is_admin():
        raise ApiError(f"Your profile does not allow editing: {', '.join(sorted(blocked))}. Ask HR to change these.")
    if "email" in payload and not (payload["email"] or "").strip():
        raise ApiError("Email cannot be blank")
    updated = db_update("employees", row_id, payload)
    return jsonify({"success": True, "employee": enrich_employee_row(updated),
                    "message": "Profile updated", "changed": sorted(payload.keys())})


@app.route("/api/employees/<row_id>", methods=["DELETE"])
@admin_required
def api_employee_delete(row_id):
    emp = db_get("employees", row_id)
    if not emp:
        raise ApiError("Employee not found", 404)
    if any(str(e.get("manager_id")) == str(row_id) for e in db_list("employees")):
        raise ApiError("This person has direct reports - reassign them first")
    if str(row_id) == str(acting_employee_id()):
        raise ApiError("You cannot remove your own record")
    if supabase:
        db_update("employees", row_id, {"status": "Exited", "exit_date": str(today()),
                                       "exit_reason": "Removed from directory"})
        return jsonify({"success": True, "soft_delete": True,
                        "message": f"{emp.get('full_name')} marked as exited (history preserved)"})
    db_delete("employees", row_id)
    for table, key in (("leave_balances", "employee_id"), ("attendance", "employee_id")):
        for r in [r for r in _load_mock().get(table, []) if str(r.get(key)) == str(row_id)]:
            db_delete(table, r["id"])
    return jsonify({"success": True, "message": f"{emp.get('full_name')} removed"})


# =================================================================== org chart
def would_create_cycle(all_rows, manager_id, candidate):
    """True if making `manager_id` report to `candidate` would create a loop.

    A loop exists exactly when the proposed manager sits inside that employee's own
    subtree - i.e. walking up from the candidate lands back on the employee.
    """
    by_id = {str(r.get("id")): r for r in all_rows}
    target, cursor, seen = str(manager_id), str(candidate or ""), set()
    while cursor and cursor in by_id:
        if cursor == target:
            return True
        if cursor in seen:
            return True
        seen.add(cursor)
        cursor = str(by_id[cursor].get("manager_id") or "")
    return False


@app.route("/api/orgchart")
def api_orgchart():
    employees = [e for e in db_list("employees", order="full_name")
                 if e.get("status") != "Exited" and not e.get("exit_date")]
    by_id = {str(e.get("id")): e for e in employees}
    # a name in manager_id (legacy rows) is resolved to the matching employee id
    by_name = {(e.get("full_name") or "").strip().lower(): str(e.get("id")) for e in employees}
    for e in employees:
        mgr = e.get("manager_id")
        if mgr and str(mgr) not in by_id:
            resolved = by_name.get(str(mgr).strip().lower())
            if resolved:
                e["manager_id"] = resolved
    children = {}
    for e in employees:
        parent = str(e.get("manager_id") or "")
        if parent and parent in by_id and parent != str(e.get("id")):
            children.setdefault(parent, []).append(e)
        else:
            children.setdefault("__root__", []).append(e)

    def build(node, depth=0):
        kids = sorted(children.get(str(node.get("id")), []), key=lambda x: (x.get("full_name") or ""))
        sub = [build(k, depth + 1) for k in kids]
        return {"id": node.get("id"), "name": node.get("full_name"), "code": node.get("employee_code"),
                "email": node.get("email"), "avatar": node.get("avatar") or initials(node.get("full_name")),
                "designation": node.get("designation") or designation_map().get(str(node.get("designation_id")), ""),
                "department": node.get("department") or dept_map().get(str(node.get("department_id")), ""),
                "department_id": node.get("department_id"), "work_location": node.get("work_location"),
                "depth": depth, "total_reports": count_descendants(node, children),
                "children": sub}

    def count_descendants(node, mapping):
        total = 0
        stack = list(mapping.get(str(node.get("id")), []))
        while stack:
            cur = stack.pop()
            total += 1
            stack.extend(mapping.get(str(cur.get("id")), []))
        return total

    roots = sorted(children.get("__root__", []), key=lambda x: x.get("full_name") or "")
    # seniority: roots with the most reports first
    roots.sort(key=lambda r: -count_descendants(r, children))
    tree = [build(r) for r in roots]

    levels = {}
    def walk(nodes):
        for n in nodes:
            levels[n["depth"]] = levels.get(n["depth"], 0) + 1
            walk(n["children"])
    walk(tree)

    managers = {str(n["id"]): n for n in tree}
    def collect(nodes):
        for n in nodes:
            managers[str(n["id"])] = n
            collect(n["children"])
    collect(tree)
    orphaned = [e for e in employees if str(e.get("manager_id") or "") and str(e.get("manager_id")) not in by_id]
    depts = []
    for d in db_list("departments"):
        members = [e for e in employees if str(e.get("department_id")) == str(d.get("id"))]
        head = next((e for e in members if (designation_map().get(str(e.get("designation_id")), "") or "").lower().startswith("head of")),
                    (max(members, key=lambda e: count_descendants(e, children)) if members else None))
        depts.append({"id": d.get("id"), "name": d.get("name"), "description": d.get("description"),
                      "head_id": str(head.get("id")) if head else None,
                      "head": employee_display(head.get("id")) if head else None,
                      "count": len(members),
                      "members": [{"id": e.get("id"), "name": e.get("full_name"), "code": e.get("employee_code"),
                                   "designation": e.get("designation") or designation_map().get(str(e.get("designation_id")), ""),
                                   "avatar": e.get("avatar") or initials(e.get("full_name")),
                                   "manager": (employees_map().get(str(e.get("manager_id") or ""), {}) or {}).get("full_name"),
                                   "is_head": bool(head and str(e.get("id")) == str(head.get("id")))}
                                  for e in sorted(members, key=lambda x: (x.get("full_name") or ""))],
                      "locations": sorted({e.get("work_location") for e in members if e.get("work_location")})})
    return jsonify({"tree": tree, "departments": depts,
                    "stats": {"total": len(employees), "top_level": len(tree),
                              "managers": sum(1 for e in employees if str(e.get("id")) in children and children[str(e.get("id"))]),
                              "individual_contributors": sum(1 for e in employees if not children.get(str(e.get("id")))),
                              "max_depth": max(levels) if levels else 0,
                              "unassigned_manager": len(orphaned), "by_level": levels},
                    "orphaned": [employee_display(e.get("id")) for e in orphaned]})


@app.route("/api/orgchart/assign-manager", methods=["POST"])
@admin_required
def api_orgchart_assign():
    data = request.get_json(silent=True) or {}
    employee_id, manager_id = data.get("employee_id"), data.get("manager_id")
    if not employee_id:
        raise ApiError("Pick an employee first")
    if str(employee_id) == str(manager_id or ""):
        raise ApiError("An employee cannot report to themselves")
    if manager_id and not db_get("employees", manager_id):
        raise ApiError("That manager no longer exists")
    if manager_id and would_create_cycle(db_list("employees"), employee_id, manager_id):
        raise ApiError("That would create a reporting loop - pick someone outside this person's team")
    updated = db_update("employees", employee_id, {"manager_id": manager_id or None})
    return jsonify({"success": True, "employee": enrich_employee_row(updated),
                    "message": f"Reporting line updated for {updated.get('full_name')}"})


# =================================================================== documents
DOC_TYPES = [
    {"type": "Aadhaar Card", "purpose": "Identity and KYC verification", "mandatory": True, "expiry": False, "category": "Identity"},
    {"type": "PAN Card", "purpose": "Tax identity for salary processing", "mandatory": True, "expiry": False, "category": "Identity"},
    {"type": "Educational Certificates", "purpose": "Proof of qualification on record", "mandatory": True, "expiry": False, "category": "Education"},
    {"type": "Offer Letter", "purpose": "Signed employment terms", "mandatory": True, "expiry": False, "category": "Employment"},
    {"type": "Appointment Letter", "purpose": "Confirmed appointment and designation", "mandatory": False, "expiry": False, "category": "Employment"},
    {"type": "Experience Letter", "purpose": "Previous employer relieving proof", "mandatory": False, "expiry": False, "category": "Employment"},
    {"type": "Cancelled Cheque", "purpose": "Salary account verification", "mandatory": True, "expiry": False, "category": "Finance"},
    {"type": "Bank Statement", "purpose": "Account confirmation for payroll", "mandatory": False, "expiry": False, "category": "Finance"},
    {"type": "Photo ID", "purpose": "Badge and premises access", "mandatory": False, "expiry": False, "category": "Identity"},
    {"type": "Passport", "purpose": "Travel and visa documentation", "mandatory": False, "expiry": True, "category": "Identity"},
    {"type": "Driving License", "purpose": "Vehicle authorization for field roles", "mandatory": False, "expiry": True, "category": "Compliance"},
    {"type": "Professional Certification", "purpose": "Role-required licence or certificate", "mandatory": False, "expiry": True, "category": "Compliance"},
    {"type": "Medical Fitness Certificate", "purpose": "Pre-employment health clearance", "mandatory": False, "expiry": True, "category": "Compliance"},
    {"type": "Non-Disclosure Agreement", "purpose": "Signed confidentiality undertaking", "mandatory": True, "expiry": False, "category": "Legal"},
    {"type": "Relieving Letter", "purpose": "Last employer release date proof", "mandatory": False, "expiry": False, "category": "Employment"},
    {"type": "Salary Slip (previous)", "purpose": "Compensation history for CTC validation", "mandatory": False, "expiry": False, "category": "Finance"},
    {"type": "Other", "purpose": "Any additional supporting document", "mandatory": False, "expiry": False, "category": "General"},
]
REQUIRED_DOC_TYPES = [d["type"] for d in DOC_TYPES if d["mandatory"]]
DOC_VISIBILITIES = ["HR only", "Manager + HR", "Self + HR", "Company"]


def doc_type_meta(doc_type):
    return next((d for d in DOC_TYPES if d["type"] == doc_type), {"purpose": "", "mandatory": False, "expiry": False, "category": "General"})


DOC_FIELDS = {"employee_id", "title", "doc_type", "category", "purpose", "file_name", "file_url", "file_size",
              "mime_type", "description", "uploaded_by", "valid_from", "valid_till", "visibility", "status",
              "reviewer_id", "reviewer_remark", "reviewed_at", "uploaded_at", "notes"}


def _human_size(num):
    num = money(num)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def enrich_document(d):
    row = dict(d)
    meta = doc_type_meta(row.get("doc_type") or "")
    row["category"] = row.get("category") or meta.get("category") or "General"
    row["purpose"] = row.get("purpose") or meta.get("purpose") or "Supporting document"
    row["mandatory"] = bool(meta.get("mandatory"))
    row["expiry_required"] = bool(meta.get("expiry"))
    row["employee"] = employee_display(row.get("employee_id"))
    row["uploaded_by_person"] = employee_display(row.get("uploaded_by")) if row.get("uploaded_by") and str(row.get("uploaded_by")) in employees_map() else None
    row["uploaded_by_label"] = row.get("uploaded_by_person", {}).get("full_name") if row.get("uploaded_by_person") else (row.get("uploaded_by") or "Employee")
    row["reviewer"] = employee_display(row.get("reviewer_id"))
    row["size_bytes"] = int(money(row.get("file_size")))
    row["size_label"] = _human_size(row.get("file_size"))
    row["uploaded_label"] = fmt_day(row.get("uploaded_at") or row.get("created_at"))
    row["valid_from_label"] = fmt_day(row.get("valid_from")) if row.get("valid_from") else "-"
    row["valid_till_label"] = fmt_day(row.get("valid_till")) if row.get("valid_till") else "-"
    row["has_file"] = bool(row.get("file_url") or row.get("file_name"))
    till = parse_day(row.get("valid_till"))
    row["expiry_days_left"] = (till - today()).days if till else None
    if row["expiry_days_left"] is not None:
        row["expiry_state"] = ("Expired" if row["expiry_days_left"] < 0 else
                              "Expiring soon" if row["expiry_days_left"] <= 60 else "Valid")
    else:
        row["expiry_state"] = "No expiry"
    row["download_url"] = f"/api/documents/{row.get('id')}/download" if row.get("has_file") else None
    return row


def can_see_document(d, viewer_emp):
    """Visibility rules: HR sees all; managers see their team; employees see their own."""
    if is_admin():
        return True
    visibility = d.get("visibility") or "HR only"
    own = viewer_emp and str(d.get("employee_id")) == str(viewer_emp.get("id"))
    if own and visibility in ("Self + HR", "Manager + HR", "Company"):
        return True
    if visibility == "Company":
        return True
    if visibility == "Manager + HR" and viewer_emp:
        team = {str(e.get("id")) for e in db_list("employees", {"manager_id": viewer_emp.get("id")})}
        if str(d.get("employee_id")) in team:
            return True
    return False


@app.route("/api/documents")
def api_documents():
    viewer = current_employee()
    rows = [enrich_document(d) for d in db_list("documents", order="uploaded_at", descending=True)]
    if not is_admin():
        rows = [d for d in rows if can_see_document(d, viewer)]
    emp_id = request.args.get("employee_id")
    if emp_id and emp_id not in ("All", ""):
        rows = [d for d in rows if str(d.get("employee_id")) == emp_id]
    for arg, key in (("status", "status"), ("category", "category"), ("doc_type", "doc_type"),
                     ("department", "department"), ("expiry", "expiry_state")):
        val = request.args.get(arg)
        if val and val != "All":
            if key == "department":
                rows = [d for d in rows if (d.get("employee") or {}).get("department") == val]
            else:
                rows = [d for d in rows if d.get(key) == val]
    q = (request.args.get("q") or "").strip().lower()
    if q:
        rows = [d for d in rows if q in " ".join(str(d.get(k) or "") for k in
               ("title", "doc_type", "purpose", "category", "description")).lower()
               or q in ((d.get("employee") or {}).get("full_name") or "").lower()]
    if request.args.get("expiring") == "soon":
        rows = [d for d in rows if d.get("expiry_state") in ("Expired", "Expiring soon")]
    return jsonify(rows)


@app.route("/api/documents/meta")
def api_documents_meta():
    """Owner list, category taxonomy and the per-employee compliance checklist."""
    viewer = current_employee()
    all_rows = [enrich_document(d) for d in db_list("documents")]
    rows = [d for d in all_rows if is_admin() or can_see_document(d, viewer)]
    by_employee = {}
    for d in rows:
        by_employee.setdefault(str(d.get("employee_id")), []).append(d)
    checklist = []
    if is_admin():
        for e in [e for e in db_list("employees") if e.get("status") != "Exited"]:
            have = by_employee.get(str(e.get("id")), [])
            verified = [d for d in have if d.get("status") == "Verified"]
            missing = [t for t in REQUIRED_DOC_TYPES if t not in {d.get("doc_type") for d in have}]
            unverified = [d.get("doc_type") for d in have if d.get("status") == "Pending"]
            expiring = [d.get("doc_type") for d in have if d.get("expiry_state") in ("Expired", "Expiring soon")]
            pct = round(len([t for t in REQUIRED_DOC_TYPES if t not in missing]) / len(REQUIRED_DOC_TYPES) * 100)
            checklist.append({"employee": employee_display(e.get("id")), "verified": len(verified),
                              "total_uploaded": len(have), "missing": missing, "unverified": unverified,
                              "expiring": expiring, "completion_pct": pct,
                              "requests_pending": len([r for r in db_list("document_requests", {"employee_id": e.get("id"),
                                                                 "status": OPEN_DOC_REQUESTS})])})
        checklist.sort(key=lambda c: c["completion_pct"])
    counts = {"total": len(rows), "pending": len([d for d in rows if d.get("status") == "Pending"]),
              "verified": len([d for d in rows if d.get("status") == "Verified"]),
              "rejected": len([d for d in rows if d.get("status") == "Rejected"]),
              "expiring_soon": len([d for d in rows if d.get("expiry_state") == "Expiring soon"]),
              "expired": len([d for d in rows if d.get("expiry_state") == "Expired"]),
              "storage_bytes": sum(d["size_bytes"] for d in rows)}
    by_category, by_type = {}, {}
    for d in rows:
        by_category[d["category"]] = by_category.get(d["category"], 0) + 1
        by_type[d.get("doc_type") or "Other"] = by_type.get(d.get("doc_type") or "Other", 0) + 1
    return jsonify({"doc_types": DOC_TYPES, "required_doc_types": REQUIRED_DOC_TYPES, "visibilities": DOC_VISIBILITIES,
                    "categories": sorted({d["category"] for d in DOC_TYPES}), "counts": counts,
                    "by_category": by_category, "by_type": by_type, "checklist": checklist,
                    "storage_label": _human_size(counts["storage_bytes"]), "my_documents": rows[:8],
                    "storage_mode": (f"Supabase Storage bucket: {SUPABASE_BUCKET}" if (supabase and SUPABASE_BUCKET) else f"local folder: {os.path.basename(UPLOAD_DIR)}/")})


def store_bytes(file_storage, employee_id, doc_type, notes):
    """Persist an upload. Supabase Storage when a bucket is configured, else the local uploads folder."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file_storage.filename or "document")
    name = f"{now_local().strftime('%Y%m%d%H%M%S')}_{safe}"
    rel = f"documents/{employee_id or 'shared'}/{name}"
    raw = file_storage.read()
    if supabase and SUPABASE_BUCKET:
        try:
            supabase.storage.from_(SUPABASE_BUCKET).upload(rel, raw, {"content_type": file_storage.mimetype or "application/octet-stream", "upsert": "true"})
            return {"file_url": rel, "file_name": safe, "file_size": len(raw), "mime_type": file_storage.mimetype,
                    "storage": "supabase"}
        except Exception as exc:                                          # noqa: BLE001
            print(f"Supabase Storage upload failed, saving locally: {exc}")
    folder = os.path.join(UPLOAD_DIR, "documents", str(employee_id or "shared"))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "wb") as fh:
        fh.write(raw)
    return {"file_url": f"documents/{employee_id or 'shared'}/{name}", "file_name": safe, "file_size": len(raw),
            "mime_type": file_storage.mimetype, "storage": "local"}


@app.route("/api/documents", methods=["POST"])
def api_document_upload():
    """Accepts multipart/form-data (with a file) or JSON (metadata only)."""
    if request.files:
        data = request.form
        file_storage = request.files.get("file")
    else:
        data = request.get_json(silent=True) or {}
        file_storage = None
    owner = data.get("employee_id") or (acting_employee_id() or "")
    if not is_admin() and data.get("employee_id") and str(data["employee_id"]) != str(acting_employee_id()):
        raise ApiError("Only HR Admins can upload a document on behalf of someone else", 403)
    if not owner:
        raise ApiError("No employee profile is linked to this login, so there is nowhere to file this document")
    doc_type = data.get("doc_type") or "Other"
    meta = doc_type_meta(doc_type)
    title = (data.get("title") or "").strip() or f"{doc_type} - {fmt_day(today(), '%d %b %Y')}"
    purpose = (data.get("purpose") or "").strip() or meta.get("purpose") or "Supporting document"
    if not (data.get("description") or "").strip() and not file_storage:
        raise ApiError("Add a file or tell us what this record is for")
    till = data.get("valid_till")
    if meta.get("expiry") and not till:
        raise ApiError(f"{doc_type} has an expiry date - please fill in 'Valid till'")
    row = {"employee_id": owner, "title": title, "doc_type": doc_type, "category": data.get("category") or meta.get("category"),
           "purpose": purpose, "description": (data.get("description") or "").strip(),
           "valid_from": data.get("valid_from") or None, "valid_till": till or None,
           "visibility": data.get("visibility") or "Self + HR", "status": "Verified" if is_admin() else "Pending",
           "uploaded_by": acting_employee_id() or session["user"].get("email") or "HR",
           "uploaded_at": str(today()), "created_at": str(today()),
           "notes": (data.get("notes") or "").strip()}
    if file_storage and file_storage.filename:
        row.update(store_bytes(file_storage, owner, doc_type, row["description"]))
    elif data.get("file_url"):
        row.update({"file_url": data["file_url"], "file_name": data.get("file_name") or "linked file"})
    created = db_insert("documents", {k: v for k, v in row.items() if k in DOC_FIELDS})
    # a Pending request for the same document type is auto-fulfilled
    for req in db_list("document_requests", {"employee_id": owner, "doc_type": doc_type, "status": OPEN_DOC_REQUESTS}):
        db_update("document_requests", req["id"], {"status": "Fulfilled", "fulfilled_document_id": created.get("id")})
    return jsonify({"success": True, "document": enrich_document(created),
                    "message": f"{title} filed for {employee_display(owner)['full_name']}" +
                               ("" if is_admin() else " - pending HR verification")})


@app.route("/api/documents/<row_id>", methods=["PUT", "DELETE"])
def api_document_update(row_id):
    doc = db_get("documents", row_id)
    if not doc:
        raise ApiError("Document not found", 404)
    data = request.get_json(silent=True) or {}
    if request.method == "DELETE":
        if not (is_admin() or str(doc.get("employee_id")) == str(acting_employee_id())):
            raise ApiError("You can only remove your own documents", 403)
        if doc.get("status") == "Verified" and not is_admin():
            raise ApiError("A verified document is part of the official record - contact HR to replace it", 403)
        # Remove the stored file too, not just the metadata row. The file may live in
        # Supabase Storage (cloud mode) or on the local disk (local mode) depending on
        # which storage was active when it was uploaded - clean up wherever it is.
        target = doc.get("file_url")
        if target:
            local_path = os.path.join(UPLOAD_DIR, target)
            if supabase and SUPABASE_BUCKET and not os.path.exists(local_path):
                try:
                    supabase.storage.from_(SUPABASE_BUCKET).remove([target])
                except Exception as exc:                                      # noqa: BLE001
                    print(f"[document delete] could not remove {target} from storage: {exc}")
            elif os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError as exc:                                        # noqa: BLE001
                    print(f"[document delete] could not remove local file {local_path}: {exc}")
        db_delete("documents", row_id)
        return jsonify({"success": True, "message": "Document removed"})
    if not is_admin():
        if str(doc.get("employee_id")) != str(acting_employee_id()):
            raise ApiError("You can only edit your own documents", 403)
        allowed = {"title", "description", "purpose", "valid_from", "valid_till", "visibility", "doc_type", "category"}
        payload = {k: v for k, v in data.items() if k in allowed}
        if doc.get("status") == "Verified" and payload.get("doc_type"):
            raise ApiError("A verified document cannot change type - upload a replacement instead", 403)
        payload["status"] = "Pending"
        return jsonify({"success": True, "document": enrich_document(db_update("documents", row_id, payload)),
                        "message": "Document updated and sent back for verification"})
    action = data.get("action")
    payload = {k: v for k, v in data.items() if k in DOC_FIELDS}
    if action in ("Verified", "Rejected"):
        payload.update({"status": action, "reviewer_id": acting_employee_id(), "reviewed_at": str(today())})
        if action == "Rejected" and not (data.get("reviewer_remark") or "").strip():
            raise ApiError("Tell the employee why the document was rejected")
    updated = db_update("documents", row_id, payload)
    return jsonify({"success": True, "document": enrich_document(updated),
                    "message": f"Marked {action}" if action else "Document updated"})


@app.route("/api/documents/<row_id>/download")
def api_document_download(row_id):
    doc = db_get("documents", row_id)
    if not doc:
        raise ApiError("Document not found", 404)
    if not can_see_document(doc, current_employee()):
        raise ApiError("HR has restricted who can open this document", 403)
    target = doc.get("file_url")
    if not target:
        raise ApiError("This record has no file attached - it is metadata only", 404)
    if supabase and SUPABASE_BUCKET and not os.path.exists(os.path.join(UPLOAD_DIR, target)):
        try:
            res = supabase.storage.from_(SUPABASE_BUCKET).download(target)
            filename = doc.get("file_name") or os.path.basename(target)
            return Response(res, mimetype=doc.get("mime_type") or "application/octet-stream",
                            headers={"Content-Disposition": f'inline; filename="{filename}"'})
        except Exception as exc:                                          # noqa: BLE001
            raise ApiError(f"Could not fetch the file from storage: {exc}", 502) from exc
    folder, filename = os.path.split(target)
    stored = os.path.join(UPLOAD_DIR, folder) if folder else UPLOAD_DIR
    if not os.path.isdir(stored):
        raise ApiError("The stored file is no longer on disk (uploads are kept locally in demo mode)", 404)
    return send_from_directory(stored, filename, as_attachment=False, download_name=doc.get("file_name") or filename)


DOC_REQUEST_FIELDS = {"employee_id", "doc_type", "reason", "due_date", "requested_by", "status", "fulfilled_document_id"}


@app.route("/api/document-requests")
def api_document_requests():
    rows = []
    viewer = current_employee()
    for r in db_list("document_requests", order="due_date"):
        if not is_admin() and str(r.get("employee_id")) != str((viewer or {}).get("id")):
            continue
        rows.append({**r, "employee": employee_display(r.get("employee_id")),
                     "doc_purpose": doc_type_meta(r.get("doc_type") or "").get("purpose"),
                     "due_label": fmt_day(r.get("due_date")), "requester": r.get("requested_by") or "HR",
                     "overdue": bool(parse_day(r.get("due_date")) and parse_day(r.get("due_date")) < today() and r.get("status") == "Pending"),
                     "has_document": any(str(d.get("employee_id")) == str(r.get("employee_id")) and d.get("doc_type") == r.get("doc_type")
                                         for d in db_list("documents"))})
    return jsonify(rows)


@app.route("/api/document-requests", methods=["POST"])
def api_document_request_create():
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id") or acting_employee_id()
    if not is_admin():
        employee_id = acting_employee_id()
    if not employee_id:
        raise ApiError("Select an employee to request a document from")
    if not data.get("doc_type"):
        raise ApiError("Choose the document you need")
    if not (data.get("reason") or "").strip():
        raise ApiError("Add a short note telling the employee why this is needed")
    row = {"employee_id": employee_id, "doc_type": data["doc_type"], "reason": data["reason"].strip(),
           "due_date": data.get("due_date") or str(today() + timedelta(days=7)),
           "requested_by": session["user"]["name"], "status": "Pending", "created_at": str(today())}
    created = db_insert("document_requests", row)
    return jsonify({"success": True, "request": created,
                    "message": f"{data['doc_type']} requested from {employee_display(employee_id)['full_name']}"})


@app.route("/api/document-requests/<row_id>", methods=["PUT", "DELETE"])
def api_document_request_update(row_id):
    req = db_get("document_requests", row_id)
    if not req:
        raise ApiError("Request not found", 404)
    if request.method == "DELETE":
        if not is_admin():
            raise ApiError("Only HR Admins can withdraw a request", 403)
        db_delete("document_requests", row_id)
        return jsonify({"success": True})
    data = request.get_json(silent=True) or {}
    payload = {}
    if is_admin():
        payload = {k: v for k, v in data.items() if k in DOC_REQUEST_FIELDS} or {"status": data.get("status", "Pending")}
    elif data.get("status") in ("Fulfilled", "Withdrawn") and str(req.get("employee_id")) == str(acting_employee_id()):
        # the employee can mark their own request as done (by uploading) or decline it
        payload = {"status": data["status"]}
    else:
        raise ApiError("Only HR Admins can change this request", 403)
    updated = db_update("document_requests", row_id, payload)
    return jsonify({"success": True, "request": updated, "message": "Request updated"})


# =================================================================== attendance
def month_bounds(month_str):
    """(first, last) day of a `YYYY-MM` period - or a 400, never a 500 from a bad filter.

    The picker sends `2026-09`; a hand-typed URL sends `2026/9`. Both are fine. `nonsense`,
    `13` and `2026-13` used to reach `int()`/`date()` and come back as an internal error,
    because the old helper unpacked a dash and `date()` rejects month 13 - so a junk filter
    on /api/attendance/summary was a 500 while the screen itself looked perfectly healthy.
    """
    bits = [b for b in re.split(r"[^0-9]+", str(month_str or "").strip()) if b]
    if len(bits) < 2:
        raise ApiError("Month filter must look like 2026-09")
    try:
        first = date(int(bits[0]), int(bits[1]), 1)
    except ValueError:
        raise ApiError("Month filter must look like 2026-09")
    nxt = date(first.year + 1, 1, 1) if first.month == 12 else date(first.year, first.month + 1, 1)
    return first, nxt - timedelta(days=1)


# ------------------------------------------------- punch location (GPS on clock in/out)
# Every punch captures where the employee was standing. The browser asks for a one-shot
# GPS pin (W3C device-location API) and reverse-geocodes it; the JSON below is what gets
# persisted in attendance.clock_in_location / attendance.clock_out_location, so a cell is:
#   {"lat": 28.6139, "lng": 77.209, "accuracy": 9.5, "address": "Connaught Place, New Delhi"}
# and a punch with no pin is simply {"address": "Office"}.
def punch_location_payload(latitude=None, longitude=None, accuracy=None, address=None, typed=None):
    """Normalize one punch's location fields into the JSON string stored on the row."""
    lat = lng = None
    try:
        lat = float(latitude) if latitude not in (None, "") else None
        lng = float(longitude) if longitude not in (None, "") else None
    except (TypeError, ValueError):
        lat = lng = None
    if lat is not None and not -90 <= lat <= 90:
        lat = None
    if lng is not None and not -180 <= lng <= 180:
        lng = None
    if typed and str(typed).strip():                       # the old free-text Location box wins
        return json.dumps({"address": str(typed).strip()[:140]})
    if lat is None or lng is None:                          # no pin: never block a punch
        return json.dumps({"address": "Office"})
    obj = {"lat": round(lat, 6), "lng": round(lng, 6)}
    try:
        if accuracy not in (None, ""):
            obj["accuracy"] = round(float(accuracy), 1)
    except (TypeError, ValueError):
        pass
    if address and str(address).strip():
        obj["address"] = str(address).strip()[:140]
    return json.dumps(obj, separators=(",", ":"))


def parse_punch_location(raw):
    """Read a stored punch-location cell back and answer with a friendly label + map bits.

    Falls back gracefully: plain legacy text ("Delhi office") and anything unparseable
    are treated as an address with no coordinates.
    """
    obj = None
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw) if raw.strip().startswith(("{", "[")) else None
        except ValueError:
            obj = None
        if obj is None:
            obj = {"address": raw.strip()}
    elif isinstance(raw, dict):
        obj = dict(raw)
    if not isinstance(obj, dict):
        return {"label": None, "address": None, "lat": None, "lng": None, "accuracy": None}
    try:
        lat = float(obj["lat"]) if obj.get("lat") not in (None, "") else None
        lng = float(obj["lng"]) if obj.get("lng") not in (None, "") else None
        accuracy = float(obj["accuracy"]) if obj.get("accuracy") not in (None, "") else None
    except (TypeError, ValueError):
        lat = lng = accuracy = None
    address = str(obj.get("address") or "").strip() or None
    if lat is not None and lng is not None:
        label = address or f"{lat:.5f}, {lng:.5f}"
    else:
        label = address or (None if not obj.get("address") else "Office")
    return {"label": label or None, "address": address, "lat": lat, "lng": lng, "accuracy": accuracy}


def enrich_attendance_row(a, employees=None):
    row = dict(a)
    emp = (employees or employees_map()).get(str(row.get("employee_id"))) or {}
    row["employee_name"] = emp.get("full_name", "Unknown")
    row["employee_code"] = emp.get("employee_code", "-")
    row["employee_avatar"] = emp.get("avatar") or initials(emp.get("full_name"))
    row["department"] = emp.get("department") or dept_map().get(str(emp.get("department_id")), "-")
    row["date_label"] = fmt_day(row.get("date"))
    row["clock_in_label"] = fmt_time(row.get("clock_in"), "--:--")
    row["clock_out_label"] = fmt_time(row.get("clock_out"), "--:--")
    row["late_minutes"] = max(0, (minutes_of(row.get("clock_in")) or 570) - 570) if row.get("clock_in") else 0
    if not row.get("clock_out") and row.get("clock_in"):
        row["worked_label"] = "In progress"
    else:
        hours = money(row.get("work_hours"))
        row["worked_label"] = f"{hours:.1f} h" if hours else "-"
    row["regularization_status"] = row.get("regularization_status") or "None"
    for side, key in (("in", "clock_in_location"), ("out", "clock_out_location")):
        loc = parse_punch_location(row.get(key))
        row[f"clock_{side}_location_label"] = loc["label"]
        row[f"clock_{side}_lat"] = loc["lat"]
        row[f"clock_{side}_lng"] = loc["lng"]
        row[f"clock_{side}_accuracy"] = loc["accuracy"]
        row[f"clock_{side}_map"] = (
            f"https://maps.google.com/?q={loc['lat']:.6f},{loc['lng']:.6f}" if loc["lat"] is not None else None
        )
    # the single Location column keeps a readable value for older rows / CSV / HR entries
    if not row.get("location") and row.get("clock_in_location"):
        row["location"] = parse_punch_location(row.get("clock_in_location"))["label"] or "Office"
    return row


def working_days_between(first, last, holidays=None, employee=None):
    """Mon-Fri days in [first, last] minus gazetted holidays, clipped to a person's employment.

    The same rule `payroll_days` and `mock_data.month_working_days` use, so the register a person
    reads and the divisor payroll uses cannot drift apart. `employee` trims the window to the
    joining and exit dates: nobody is marked absent before they joined or after they left.
    """
    if holidays is None:
        holidays = db_list("holidays")
    off = {str(h.get("date"))[:10] for h in holidays}
    if employee:
        joining, exit_day = parse_day(employee.get("date_of_joining")), parse_day(employee.get("exit_date"))
        if joining and joining > first:
            first = joining
        if exit_day and exit_day < last:
            last = exit_day
    return [first + timedelta(days=i) for i in range(max(0, (last - first).days + 1))
            if (first + timedelta(days=i)).weekday() < 5 and (first + timedelta(days=i)).isoformat() not in off]


def attendance_roster(emp_id, employees):
    """Who the attendance screen answers for: one person when the URL asks for one, else everybody."""
    if emp_id:
        one = employees.get(str(emp_id))
        return [one] if one else []
    return [e for e in employees.values() if e.get("status") != "Exited" and not e.get("exit_date")]


def missing_attendance_rows(first, last, rows, employees=None, holidays=None, leaves=None,
                            regularizations=None):
    """Synthetic rows for working days that are already behind us and carry no punch.

    This is the hole the register used to have: nobody punches, no row is written, and the day
    (22/09, say) simply does not exist on any screen. A register answers for every working day -
    Present, On Leave, Absent, week off - so a past working day with no punch is `Absent`. Only
    days up to *yesterday* are filled: today's punch may still come, and tomorrow cannot be absent
    yet. A day covered by an approved leave reads `On Leave`; one with a *pending* regularization
    request is left alone, because the request, not a verdict, is what should show. These rows are
    display-only - nothing is written to the database - and `payroll_days()` docks them as Absent so
    a slip matches the screen: file a regularization to win the day back.
    """
    if employees is None:
        employees = attendance_roster(None, employees_map())
    if holidays is None:
        holidays = db_list("holidays")
    if leaves is None:
        leaves = db_list("leave_requests")
    if regularizations is None:
        regularizations = db_list("attendance_regularizations")
    punched = {(str(r.get("employee_id")), str(r.get("date"))[:10]) for r in rows}
    awaiting = {(str(r.get("employee_id")), str(r.get("date"))[:10])
                for r in regularizations if r.get("status") == "Pending"}
    covered = set()
    for leave in leaves:
        if leave.get("status") != "Approved":
            continue
        start = parse_day(leave.get("start_date"))
        end = parse_day(leave.get("end_date") or leave.get("start_date"))
        if not start or not end:
            continue
        for d in working_days_between(start, end, holidays):
            covered.add((str(leave.get("employee_id")), d.isoformat()))
    cutoff = min(last, today() - timedelta(days=1))            # today is not absent yet
    out = []
    for emp in employees:
        eid = str(emp.get("id"))
        for d in working_days_between(first, cutoff, holidays, employee=emp):
            key = (eid, d.isoformat())
            if key in punched or key in awaiting:
                continue
            on_leave = key in covered
            out.append({"id": f"absent:{eid}:{d.isoformat()}", "employee_id": emp.get("id"),
                        "date": d.isoformat(), "clock_in": None, "clock_out": None, "work_hours": 0.0,
                        "break_minutes": None, "status": "On Leave" if on_leave else "Absent",
                        "is_late": False, "regularization_status": "None", "synthetic": True,
                        "note": "Approved leave on this day." if on_leave
                                else "No attendance was marked on this working day, so it reads as absent."})
    return out


@app.route("/api/attendance")
def api_attendance():
    emp_id = scoped_employee_id()
    month = request.args.get("month") or today().strftime("%Y-%m")
    first, last = month_bounds(month)
    if request.args.get("from") or request.args.get("to"):
        start = parse_day(request.args.get("from") or request.args.get("to"))
        end = parse_day(request.args.get("to") or request.args.get("from"))
        if not start or not end:
            raise ApiError("from/to must look like 2026-09-01")
        first, last = (start, end) if start <= end else (end, start)
    filters = {"date": (">=", str(first))}
    if emp_id:
        filters["employee_id"] = emp_id
    rows = db_list("attendance", filters)
    rows = [r for r in rows if parse_day(r.get("date")) and parse_day(r.get("date")) <= last]
    emps = employees_map()
    # the register answers for every working day: a past day with no punch comes back as Absent
    rows = rows + missing_attendance_rows(first, last, rows, employees=attendance_roster(emp_id, emps))
    out = [enrich_attendance_row(r, emps) for r in rows]
    out.sort(key=lambda r: (r.get("date") or "", r.get("employee_name") or ""), reverse=True)
    return jsonify({"rows": out, "month": month, "month_label": first.strftime("%B %Y"),
                    "from_date": str(first), "to_date": str(last), "scoped_to": emp_id})


@app.route("/api/attendance/summary")
def api_attendance_summary():
    emp_id = request.args.get("employee_id") or (None if is_admin() else acting_employee_id())
    month = request.args.get("month") or today().strftime("%Y-%m")
    first, last = month_bounds(month)
    filters = {"date": (">=", str(first))}
    if emp_id:
        filters["employee_id"] = emp_id
    rows = [r for r in db_list("attendance", filters) if parse_day(r.get("date")) and parse_day(r.get("date")) <= last]
    emps, holidays = employees_map(), db_list("holidays")
    rows = rows + missing_attendance_rows(first, last, rows, employees=attendance_roster(emp_id, emps),
                                          holidays=holidays)
    by_status, total_hours, overtime_hours, late, half_days, absent = {}, 0.0, 0.0, 0, 0, 0
    per_day = {}
    for r in rows:
        status = r.get("status") or "Other"
        by_status[status] = by_status.get(status, 0) + 1
        hours = money(r.get("work_hours"))
        total_hours += hours
        overtime_hours += max(0.0, hours - 8)
        late += 1 if r.get("is_late") else 0
        half_days += 1 if status == "Half Day" else 0
        absent += 1 if status == "Absent" else 0
        per_day[str(r.get("date"))[:10]] = status
    working = working_days_between(first, last, holidays)        # a holiday is not a day to answer for
    days = [str(r.get("date"))[:10] for r in rows if r.get("status") in ("Present", "Work From Home", "Half Day")]
    return jsonify({
        "employee_id": emp_id, "month": month, "month_label": first.strftime("%B %Y"),
        "days_marked": len(days), "working_days": len(working),
        "pending_days": len([d for d in working if d.isoformat() not in per_day]),
        "present": by_status.get("Present", 0), "wfh": by_status.get("Work From Home", 0),
        "half_days": half_days, "absent": absent, "on_leave": by_status.get("On Leave", 0),
        "total_hours": round(total_hours, 1), "overtime_hours": round(overtime_hours, 1),
        "late_days": late, "avg_hours": round(total_hours / len(days), 2) if days else 0,
        "by_status": by_status, "calendar": per_day,
        "regularization_pending": len([r for r in db_list("attendance_regularizations")
                                       if r.get("status") == "Pending" and (not emp_id or str(r.get("employee_id")) == str(emp_id))]),
    })


@app.route("/api/attendance/clock", methods=["POST"])
def api_attendance_clock():
    """Clock in / clock out for the signed-in employee (what the Home time tracker calls)."""
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    employee_id = data.get("employee_id")
    if not is_admin() or not employee_id:
        employee_id = acting_employee_id()
    if not employee_id:
        raise ApiError("No employee profile is linked to this account, so there is nothing to clock")
    now = now_local()
    today_s = str(now.date())
    shift = shift_row()
    grace = int(shift.get("grace_minutes") or 15)
    existing = next((r for r in db_list("attendance", {"employee_id": employee_id, "date": today_s})), None)
    stamp = now.strftime("%H:%M:%S")
    if action in ("in", "clock_in"):
        ci = (existing or {}).get("clock_in")
        co = (existing or {}).get("clock_out")
        # a row left over from before the one-punch-per-day rule: out recorded before in. Reopen it
        # instead of leaving the person stuck with a clock-out they cannot undo or complete.
        broken = bool(ci and co and (minutes_of(co) or 0) < (minutes_of(ci) or 0))
        if ci and not co:
            raise ApiError(f"You are already clocked in since {fmt_time(ci)}")
        if ci and co and not broken:
            raise ApiError(f"Today is already closed - in {fmt_time(ci)}, out {fmt_time(co)}. "
                           "If a punch is wrong, use Attendance -> Regularization or ask HR to edit the record.")
        late = (now.hour * 60 + now.minute) > (minutes_of(shift.get("start_time")) or 570) + grace
        # every punch pins where the employee stood: GPS from the browser (or a typed location)
        loc_in = punch_location_payload(data.get("lat"), data.get("lng"),
                                        data.get("accuracy"), data.get("address"),
                                        typed=data.get("location"))
        loc_in_label = parse_punch_location(loc_in)["label"] or "Office"
        payload = {"employee_id": employee_id, "date": today_s, "clock_in": stamp,
                   "status": "Present", "is_late": bool(late), "location": loc_in_label,
                   "clock_in_location": loc_in,
                   "shift_id": shift.get("id"), "break_minutes": 0, "work_hours": 0,
                   "note": "Self clock-in" if (loc_in_label == "Office" and not data.get("location"))
                           else f"Clock-in from {loc_in_label}"}
        if broken:
            payload["clock_out"] = None
            payload["note"] = "Reopened: the recorded clock-out was before the clock-in"
        row = db_update("attendance", existing["id"], payload) if existing else db_insert("attendance", payload)
        return jsonify({"success": True, "action": "in", "time": fmt_time(stamp), "late": bool(late),
                        "attendance": enrich_attendance_row(row),
                        "message": f"Clocked in at {fmt_time(stamp)}" + (" - you are marked late" if late else "")
                                   + (" - the broken record for today was reopened" if broken else "")})
    if action in ("out", "clock_out"):
        if not existing or not existing.get("clock_in"):
            raise ApiError("You need to clock in first")
        if existing.get("clock_out") and (minutes_of(existing.get("clock_in")) or 0) <= (minutes_of(existing.get("clock_out")) or 0):
            raise ApiError(f"You already clocked out at {fmt_time(existing.get('clock_out'))} - today is closed. "
                           "Ask HR to edit the record if the time is wrong.")
        start = minutes_of(existing.get("clock_in")) or 0
        end = max(now.hour * 60 + now.minute, start)
        brk = int(money(existing.get("break_minutes") or 45))
        hours = round(max(money(existing.get("work_hours")), (end - start - brk) / 60), 2)
        loc_out = punch_location_payload(data.get("lat"), data.get("lng"),
                                         data.get("accuracy"), data.get("address"),
                                         typed=data.get("location"))
        row = db_update("attendance", existing["id"], {"clock_out": stamp, "work_hours": hours,
                                                       "status": "Present" if hours >= 4 else "Half Day",
                                                       "clock_out_location": loc_out})
        return jsonify({"success": True, "action": "out", "time": fmt_time(stamp), "hours": hours,
                        "attendance": enrich_attendance_row(row),
                        "message": f"Clocked out at {fmt_time(stamp)} - {hours:.1f} hours worked today"})
    raise ApiError("Unknown clock action (use 'in' or 'out')")


@app.route("/api/attendance/entry", methods=["POST"])
@admin_required
def api_attendance_entry():
    """HR manually marks or edits one attendance day (used for back-dated corrections)."""
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id")
    day = data.get("date")
    if not employee_id or not day:
        raise ApiError("Employee and date are both required")
    status = data.get("status") or "Present"
    if status not in ("Present", "Absent", "Half Day", "Work From Home", "On Leave"):
        raise ApiError(f"'{status}' is not a valid attendance status")
    existing = next((r for r in db_list("attendance", {"employee_id": employee_id, "date": day})), None)
    ci, co = norm_time(data.get("clock_in")), norm_time(data.get("clock_out"))
    hours = money(data.get("work_hours"))
    if ci and co and not hours:
        ci_min, co_min = minutes_of(ci), minutes_of(co)
        if ci_min is not None and co_min is not None:
            hours = round(max(0.0, (co_min - ci_min - int(money(data.get("break_minutes") or 45)))) / 60, 1)
    # a corrected punch also moves the late mark, or the day stays "late" forever
    late_min = minutes_of(ci) if ci else minutes_of((existing or {}).get("clock_in"))
    shift = shift_row()
    start_min = minutes_of(shift.get("start_time")) or 570
    is_late = late_min > start_min + int(shift.get("grace_minutes") or 15) if late_min is not None else None
    payload = {"employee_id": employee_id, "date": str(day)[:10], "status": status,
               "clock_in": ci or None, "clock_out": co or None, "work_hours": hours,
               "break_minutes": int(money(data.get("break_minutes") or 0)), "location": data.get("location"),
               "note": data.get("note"), "regularization_status": "Approved" if data.get("via_regularization") else (existing or {}).get("regularization_status") or "None"}
    if is_late is not None:
        payload["is_late"] = is_late
    row = db_update("attendance", existing["id"], payload) if existing else db_insert("attendance", payload)
    return jsonify({"success": True, "attendance": enrich_attendance_row(row),
                    "message": f"Attendance for {employee_display(employee_id)['full_name']} on {fmt_day(day)} updated"})


# ------------------------------------------------ regularization (HR-approved corrections)
REG_FIELDS = {"employee_id", "date", "request_type", "clock_in_correction", "clock_out_correction", "reason",
              "status", "reviewer_id", "reviewed_at", "reviewer_remark"}


def enrich_regularization(r):
    row = dict(r)
    row["employee"] = employee_display(row.get("employee_id"))
    row["date_label"] = fmt_day(row.get("date"))
    row["reviewer"] = employee_display(row.get("reviewer_id"))
    row["clock_in_label"] = fmt_time(row.get("clock_in"), "--:--")
    row["clock_out_label"] = fmt_time(row.get("clock_out"), "--:--")
    row["requested_label"] = fmt_day(row.get("created_at"))
    row["current"] = {"clock_in": fmt_time(row.get("clock_in")), "clock_out": fmt_time(row.get("clock_out")),
                      "status": row.get("attendance_status")}
    return row


@app.route("/api/regularizations")
def api_regularizations():
    emp_id = scoped_employee_id()
    filters = {} if not emp_id else {"employee_id": emp_id}
    if request.args.get("status") and request.args["status"] != "All":
        filters["status"] = request.args["status"]
    rows = []
    for r in db_list("attendance_regularizations", filters, order="date", descending=True):
        att = next((a for a in db_list("attendance", {"employee_id": r.get("employee_id"), "date": str(r.get("date"))[:10]})), None)
        if att:
            r = {**r, "clock_in": att.get("clock_in"), "clock_out": att.get("clock_out"), "attendance_status": att.get("status")}
        rows.append(enrich_regularization(r))
    return jsonify(rows)


@app.route("/api/regularizations", methods=["POST"])
def api_regularization_create():
    """Employees must give a reason - it is mandatory and goes to the approver."""
    data = request.get_json(silent=True) or {}
    employee_id = acting_employee_id()
    if not employee_id:
        raise ApiError("No employee profile is linked to this account")
    day = parse_day(data.get("date"))
    if not day:
        raise ApiError("Pick the attendance date you want corrected")
    if day > today():
        raise ApiError("You cannot regularize a date in the future")
    reason = (data.get("reason") or "").strip()
    if len(reason) < 10:
        raise ApiError("A reason of at least 10 characters is required - your approver needs to know why")
    att = next((a for a in db_list("attendance", {"employee_id": employee_id, "date": str(day)}) ), None)
    if att and att.get("clock_in") and att.get("clock_out") and not (data.get("clock_in_correction") or data.get("clock_out_correction")):
        raise ApiError("That day already has a complete record - choose the new in/out times you want instead")
    row = {"employee_id": employee_id, "date": str(day), "request_type": data.get("request_type") or
           ("Missing punch" if not (att or {}).get("clock_in") else "Update punch"),
           "clock_in_correction": data.get("clock_in_correction") or None,
           "clock_out_correction": data.get("clock_out_correction") or None,
           "reason": reason, "status": "Pending", "created_at": str(today())}
    created = db_insert("attendance_regularizations", row)
    if att:
        db_update("attendance", att["id"], {"regularization_status": "Pending"})
    return jsonify({"success": True, "regularization": enrich_regularization(created),
                    "message": f"Correction requested for {fmt_day(day)} - sent to your manager and HR"})


@app.route("/api/regularizations/<row_id>/action", methods=["POST"])
@admin_required
def api_regularization_action(row_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    reg = db_get("attendance_regularizations", row_id)
    if not reg:
        raise ApiError("Request not found", 404)
    if action not in ("approve", "reject"):
        raise ApiError("Use 'approve' or 'reject'")
    if action == "reject" and not (data.get("remark") or "").strip():
        raise ApiError("Add a remark so the employee knows why it was rejected")
    day = str(reg.get("date"))[:10]
    att = next((a for a in db_list("attendance", {"employee_id": reg.get("employee_id"), "date": day})), None)
    if action == "approve":
        shift = shift_row()
        start_min = minutes_of(shift.get("start_time")) or 570
        end_min = minutes_of(shift.get("end_time")) or 1110
        grace = int(shift.get("grace_minutes") or 15)
        brk = int(money((att or {}).get("break_minutes") or 45))
        # a correction only replaces the punch it names; the rest of the day stays as recorded
        comin = reg.get("clock_in_correction") or (att or {}).get("clock_in")
        cimin = reg.get("clock_out_correction") or (att or {}).get("clock_out")
        payload = {"regularization_status": "Approved", "status": att.get("status") if att else "Present",
                   "note": (f"Regularized: {reg.get('reason') or ''}").strip()[:200]}
        if reg.get("clock_in_correction"):
            payload["clock_in"] = norm_time(reg["clock_in_correction"])
            payload["is_late"] = (minutes_of(payload["clock_in"]) or start_min) > start_min + grace
        if reg.get("clock_out_correction"):
            payload["clock_out"] = norm_time(reg["clock_out_correction"])
        hours = 0.0
        if reg.get("clock_in_correction") or reg.get("clock_out_correction"):
            in_m = minutes_of(payload.get("clock_in") or comin)
            out_m = minutes_of(payload.get("clock_out") or cimin)
            hours = round(max(0.0, ((out_m if out_m is not None else end_min)
                                    - (in_m if in_m is not None else start_min) - brk)) / 60, 1)
            payload["work_hours"] = hours     # without this the day kept its old (often 0) total
        if not att:
            payload.update({"employee_id": reg.get("employee_id"), "date": day, "status": "Present",
                            "work_hours": hours or 8, "break_minutes": brk, "location": "Office"})
        else:
            # a day with corrected punches is no longer an absence; WFH / On Leave stay as HR set them
            current = (att or {}).get("status")
            if hours and (payload.get("clock_in") or payload.get("clock_out")):
                if current not in ("Work From Home", "On Leave"):
                    payload["status"] = "Present" if hours >= 4 else "Half Day"
            elif current == "Absent":
                # approving a correction with no times of its own still means "this day is fine"
                payload["status"] = "Present"
                if not money(att.get("work_hours")):
                    payload["work_hours"] = round(max(0.0, (end_min - start_min - brk) / 60), 1)
        row = db_update("attendance", att["id"], payload) if att else db_insert("attendance", payload)
        db_update("attendance_regularizations", row_id, {
            "status": "Approved", "reviewer_id": acting_employee_id(), "reviewed_at": str(today()),
            "reviewer_remark": (data.get("remark") or "Approved by HR").strip()[:250]})
        return jsonify({"success": True, "attendance": enrich_attendance_row(row),
                        "message": f"Approved - attendance for {fmt_day(day)} is corrected"})
    db_update("attendance_regularizations", row_id, {"status": "Rejected", "reviewer_id": acting_employee_id(),
                                                      "reviewed_at": str(today()), "reviewer_remark": data.get("remark")})
    if att:
        db_update("attendance", att["id"], {"regularization_status": "Rejected"})
    return jsonify({"success": True, "message": f"Request rejected - the employee sees your remark: {data.get('remark')}"})


@app.route("/api/regularizations/<row_id>", methods=["DELETE"])
def api_regularization_delete(row_id):
    reg = db_get("attendance_regularizations", row_id)
    if not reg:
        raise ApiError("Request not found", 404)
    if not is_admin() and str(reg.get("employee_id")) != str(acting_employee_id()):
        raise ApiError("You can only withdraw your own requests", 403)
    if reg.get("status") != "Pending":
        raise ApiError("Only pending requests can be withdrawn")
    att = next((a for a in db_list("attendance", {"employee_id": reg.get("employee_id"), "date": str(reg.get("date"))[:10]})), None)
    if att:
        db_update("attendance", att["id"], {"regularization_status": "None"})
    db_delete("attendance_regularizations", row_id)
    return jsonify({"success": True, "message": "Request withdrawn"})


# =================================================================== leave
def enrich_leave_row(l):
    row = dict(l)
    lt = leave_type_map().get(str(row.get("leave_type_id"))) or {}
    row["leave_type_label"] = lt.get("name") or row.get("leave_type") or "Leave"
    row["leave_color"] = lt.get("color") or "#64748b"
    row["is_paid"] = lt.get("is_paid", True)
    row["employee"] = employee_display(row.get("employee_id"))
    row["approver"] = employee_display(row.get("approver_id"))
    row["start_label"] = fmt_day(row.get("start_date"))
    row["end_label"] = fmt_day(row.get("end_date")) or row["start_label"]
    row["days"] = money(row.get("days") or 1)
    row["period_label"] = row["start_label"] if row["start_label"] == row["end_label"] else f"{row['start_label']} - {row['end_label']}"
    return row


@app.route("/api/leave-balances")
def api_leave_balances():
    return jsonify(compute_leave_balances(request.args.get("employee_id") or scoped_employee_id()))


def compute_leave_balances(employee_id, year=None):
    year = int(year or today().year)
    lt_map, out = leave_type_map(), []
    # `pending` is always derived from the requests themselves, never trusted from the quota row,
    # so the Me page, the Leave tab and the Home card can never disagree.
    pending_days = {}
    for l in db_list("leave_requests"):
        if l.get("status") != "Pending":
            continue
        key = (str(l.get("employee_id")), str(l.get("leave_type_id")))
        pending_days[key] = pending_days.get(key, 0) + money(l.get("days") or 1)
    if employee_id:
        employee_ids = [employee_id]
    else:
        employee_ids = [e.get("id") for e in db_list("employees") if e.get("status") != "Exited"]
    balance_rows = db_list("leave_balances")
    by_employee = {}
    for b in balance_rows:
        if str(b.get("year") or year) != str(year):
            continue
        by_employee.setdefault(str(b.get("employee_id")), []).append(b)
    for eid in employee_ids:
        rows = by_employee.get(str(eid), [])
        balances = []
        for b in rows:
            lt = lt_map.get(str(b.get("leave_type_id")), {})
            total = int(b.get("total") or lt.get("yearly_quota") or 0)
            used = int(b.get("used") or 0)
            pending = int(round(pending_days.get((str(eid), str(b.get("leave_type_id"))), 0)))
            balances.append({"employee_id": eid, "leave_type_id": b.get("leave_type_id"),
                             "leave_type": lt.get("name", "-"), "name": lt.get("name", "-"),
                             "code": lt.get("code"), "color": lt.get("color"),
                             "is_paid": lt.get("is_paid", True), "total": total, "used": used, "pending": pending,
                             "remaining": max(total - used - pending, 0),
                             "used_pct": min(100, round(used / total * 100)) if total else 0})
        out.append({"employee_id": eid, "employee": employee_display(eid), "year": year, "balances": balances})
    if employee_id:
        return out[0] if out else {"employee_id": employee_id, "employee": employee_display(employee_id),
                                   "year": year, "balances": []}
    return out


@app.route("/api/leave-requests")
def api_leave_requests():
    emp_id = scoped_employee_id()
    filters = {} if not emp_id else {"employee_id": emp_id}
    if request.args.get("status") and request.args["status"] != "All":
        filters["status"] = request.args["status"]
    rows = [enrich_leave_row(l) for l in db_list("leave_requests", filters, order="start_date", descending=True)]
    return jsonify(rows)


@app.route("/api/leave-requests", methods=["POST"])
def api_leave_request_create():
    data = request.get_json(silent=True) or {}
    employee_id = acting_employee_id()
    if not employee_id:
        raise ApiError("No employee profile is linked to this account, so leave cannot be applied for")
    start, end = parse_day(data.get("start_date")), parse_day(data.get("end_date"))
    if not start:
        raise ApiError("Select the first day of your leave")
    if not end:
        raise ApiError("Select the last day of your leave")
    if end < start:
        raise ApiError("The end date is before the start date")
    if start < today():
        raise ApiError("Past dates cannot be applied for - raise an attendance regularization instead")
    if not (data.get("reason") or "").strip():
        raise ApiError("Tell your approver the reason for this leave")
    lt_map = leave_type_map()
    lt_id = data.get("leave_type_id") or data.get("leave_type")
    lt = lt_map.get(str(lt_id)) or next((t for t in lt_map.values() if (t.get("name") or "") == str(lt_id)), None)
    if not lt:
        raise ApiError("Choose a leave type")
    days = (end - start).days + 1
    if data.get("half_day"):
        days -= 0.5
    overlaps = [l for l in db_list("leave_requests", {"employee_id": employee_id})
                if l.get("status") in ("Approved", "Pending")
                and str(l.get("start_date"))[:10] <= str(end) and str(l.get("end_date") or l.get("start_date"))[:10] >= str(start)]
    if overlaps:
        raise ApiError(f"You already have a {overlaps[0].get('status').lower()} leave covering {fmt_day(overlaps[0].get('start_date'))}")
    balances = next((b for b in compute_leave_balances(employee_id)["balances"] if str(b["leave_type_id"]) == str(lt["id"])), None)
    if balances and days > balances["remaining"]:
        raise ApiError(f"Only {balances['remaining']} {lt['name']} day(s) left - you asked for {days}")
    row = {"employee_id": employee_id, "leave_type_id": lt["id"], "start_date": str(start), "end_date": str(end),
           "days": days, "half_day": bool(data.get("half_day")), "reason": data["reason"].strip(),
           "status": "Pending", "created_at": str(today())}
    if lt.get("requires_approval") is False:
        row["status"] = "Approved"
        row["actioned_at"] = str(today())
        row["admin_remark"] = "Auto-approved (this leave type needs no approval)"
    created = db_insert("leave_requests", row)
    if created.get("status") == "Pending":
        bump_balance(employee_id, lt["id"], "pending", days)
    else:
        bump_balance(employee_id, lt["id"], "used", days)
    manager = (employees_map().get(str(employee_id)) or {}).get("manager_id")
    return jsonify({"success": True, "leave": enrich_leave_row(created),
                    "message": f"{days} day(s) of {lt['name']} applied for" +
                               (f" - sent to {employee_display(manager)['full_name']}" if manager else "")})


def bump_balance(employee_id, leave_type_id, field, delta):
    """Move `delta` days onto `used` / `pending` for this year's quota row.

    Additive on purpose: applying adds to `pending`, approving moves those days from
    `pending` onto `used`, rejecting or cancelling takes them back off `pending`.
    """
    year = today().year
    row = next((b for b in db_list("leave_balances", {"employee_id": employee_id, "leave_type_id": leave_type_id,
                                                       "year": year})), None)
    if not row:
        lt = leave_type_map().get(str(leave_type_id), {})
        row = db_insert("leave_balances", {"employee_id": employee_id, "leave_type_id": leave_type_id, "year": year,
                                           "total": int(lt.get("yearly_quota") or 0), "used": 0, "pending": 0})
    total = int(money(row.get("total")))
    value = max(0, int(money(row.get(field))) + int(delta))
    if field == "used":
        value = min(value, max(total, value))          # never report more used than the quota allows
    db_update("leave_balances", row["id"], {field: value})
    return row


@app.route("/api/leave-requests/<row_id>/action", methods=["POST"])
@admin_required
def api_leave_action(row_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    leave = db_get("leave_requests", row_id)
    if not leave:
        raise ApiError("Leave request not found", 404)
    if action not in ("approve", "reject"):
        raise ApiError("Use 'approve' or 'reject'")
    if action == "reject" and not (data.get("remark") or "").strip():
        raise ApiError("Add a remark - the employee is shown why their leave was rejected")
    if leave.get("status") != "Pending":
        raise ApiError(f"This request was already {leave.get('status').lower()}")
    days = money(leave.get("days") or 1)
    db_update("leave_requests", row_id, {"status": "Approved" if action == "approve" else "Rejected",
                                         "approver_id": acting_employee_id(), "actioned_at": str(today()),
                                         "admin_remark": (data.get("remark") or ("Approved" if action == "approve" else "Rejected")).strip()})
    # release the reservation either way; only an approval consumes the quota
    bump_balance(leave.get("employee_id"), leave.get("leave_type_id"), "pending", -days)
    if action == "approve":
        bump_balance(leave.get("employee_id"), leave.get("leave_type_id"), "used", days)
        stamp = str(leave.get("start_date"))[:10]
        for offset in range(int(money((parse_day(leave.get("end_date")) or parse_day(stamp)) and
                                    ((parse_day(leave.get("end_date")) - parse_day(leave.get("start_date"))).days + 1)) or 1)):
            day = (parse_day(stamp) + timedelta(days=offset))
            if day.weekday() >= 5:
                continue
            existing = next((a for a in db_list("attendance", {"employee_id": leave.get("employee_id"), "date": str(day)})), None)
            payload = {"status": "On Leave", "clock_in": None, "clock_out": None, "work_hours": 0,
                       "note": f"Approved {leave_type_map().get(str(leave.get('leave_type_id')), {}).get('name', 'leave')}"}
            if existing:
                db_update("attendance", existing["id"], payload)
            else:
                db_insert("attendance", {"employee_id": leave.get("employee_id"), "date": str(day), **payload})
    return jsonify({"success": True, "message": f"Leave {action}d for {employee_display(leave.get('employee_id'))['full_name']}"})


@app.route("/api/leave-requests/<row_id>/cancel", methods=["POST"])
def api_leave_cancel(row_id):
    leave = db_get("leave_requests", row_id)
    if not leave:
        raise ApiError("Leave request not found", 404)
    if not is_admin() and str(leave.get("employee_id")) != str(acting_employee_id()):
        raise ApiError("You can only cancel your own leave", 403)
    if leave.get("status") not in ("Pending", "Approved"):
        raise ApiError(f"A {leave.get('status').lower()} request cannot be cancelled")
    days = money(leave.get("days") or 1)
    bump_balance(leave.get("employee_id"), leave.get("leave_type_id"),
                  "pending" if leave.get("status") == "Pending" else "used", -days)
    db_update("leave_requests", row_id, {"status": "Cancelled", "actioned_at": str(today()),
                                         "admin_remark": "Cancelled by " + session["user"]["name"]})
    for a in db_list("attendance", {"employee_id": leave.get("employee_id"), "status": "On Leave"}):
        if str(leave.get("start_date"))[:10] <= str(a.get("date"))[:10] <= str(leave.get("end_date"))[:10]:
            db_update("attendance", a["id"], {"status": "Absent", "note": "Leave cancelled", "work_hours": 0})
    return jsonify({"success": True, "message": "Leave cancelled and the days are back in your balance"})


# =================================================================== me / profile
@app.route("/api/me")
def api_me():
    emp = current_employee()
    if not emp:
        return jsonify({"employee": None, "notice": "This login is not linked to an employee record yet"})
    emp = enrich_employee_row(emp)
    day = today()
    leaves = [enrich_leave_row(l) for l in db_list("leave_requests", {"employee_id": emp["id"]})]
    att_rows = [a for a in db_list("attendance", {"employee_id": emp["id"]}) if str(a.get("date") or "") >= str(day - timedelta(days=29))]
    month_att = [a for a in db_list("attendance", {"employee_id": emp["id"]}) if str(a.get("date") or "")[:7] == day.strftime("%Y-%m")]
    # the month card answers for absent days too: a past working day with no punch is Absent
    month_first, month_last = month_bounds(day.strftime("%Y-%m"))
    month_absent = missing_attendance_rows(month_first, month_last, month_att, employees=[emp])
    month_seen = {str(a.get("date"))[:10] for a in month_att + month_absent}
    month_open = len([d for d in working_days_between(month_first, month_last, employee=emp)
                      if d.isoformat() not in month_seen])
    docs = [enrich_document(d) for d in db_list("documents", {"employee_id": emp["id"]})]
    claims = db_list("reimbursements", {"employee_id": emp["id"]})
    reviews = [enrich_review(r) for r in db_list("performance_reviews", {"employee_id": emp["id"]})]
    goals = [enrich_goal(gg) for gg in db_list("goals", {"employee_id": emp["id"]})]
    ts = db_list("timesheets", {"employee_id": emp["id"]}, order="week_starting", descending=True)
    hrs = sum(money(a.get("work_hours")) for a in att_rows)
    return jsonify({
        "employee": emp,
        "is_self_admin": is_admin(),
        "editable_fields": sorted(SELF_EDITABLE_FIELDS),
        "notice": "HR Admin - every field on this profile is editable" if is_admin() else
                  "You can update contact, address, emergency and work-location fields. Anything else needs HR.",
        "counts": {"attendance_days_30": len([a for a in att_rows if a.get("status") in ("Present", "Work From Home")]),
                   "hours_30": round(hrs, 1), "leaves_used_year": round(sum(money(l.get("days")) for l in leaves if l.get("status") == "Approved" and str(l.get("start_date"))[:4] == str(day.year)), 1),
                   "leaves_pending": len([l for l in leaves if l.get("status") == "Pending"]),
                   "documents": len(docs), "pending_documents": len([d for d in docs if d.get("status") == "Pending"]),
                   "open_claims": len([c for c in claims if c.get("status") == "Pending"]),
                   "open_goals": len([g_ for g_ in goals if g_.get("status") in ("On Track", "At Risk", "Not Started")]),
                   "timesheets_pending": len([t for t in ts if t.get("status") in ("Draft", "Submitted")])},
        "manager": employee_display(emp.get("manager_id")) if emp.get("manager_id") else None,
        "skip_level": employee_display((employees_map().get(str(emp.get("manager_id")), {}) or {}).get("manager_id")),
        "colleagues": len([e for e in db_list("employees") if str(e.get("department_id")) == str(emp.get("department_id")) and e.get("status") != "Exited"]),
        "direct_reports": [employee_display(e.get("id")) for e in db_list("employees", {"manager_id": emp["id"]}) if e.get("status") != "Exited"],
        "leave_balances": compute_leave_balances(emp["id"])["balances"],
        "attendance_30": [enrich_attendance_row(a) for a in sorted(att_rows, key=lambda x: str(x.get("date")), reverse=True)],
        "attendance_month": {"days": len(month_att), "present": len([a for a in month_att if a.get("status") == "Present"]),
                             "wfh": len([a for a in month_att if a.get("status") == "Work From Home"]),
                             "on_leave": len([a for a in month_att if a.get("status") == "On Leave"]),
                             "absent": len([a for a in month_att + month_absent if a.get("status") == "Absent"]),
                             "pending_days": month_open,
                             "late": len([a for a in month_att if a.get("is_late")]),
                             "hours": round(sum(money(a.get("work_hours")) for a in month_att), 1),
                             "month_label": day.strftime("%B %Y")},
        "leaves": leaves[:10], "documents": docs, "claims": claims[:8], "reviews": reviews[:4], "goals": goals,
        "payslips": [enrich_payslip(p) for p in db_list("payslips", {"employee_id": emp["id"]})][:6],
        "timesheets": ts[:6],
        "next_birthday": next_anniversary(emp.get("date_of_birth"), None, "birthday"),
        "next_anniversary": next_anniversary(None, emp.get("date_of_joining"), "anniversary"),
    })


@app.route("/api/me", methods=["PUT"])
def api_me_update():
    return api_employee_update(acting_employee_id() or "")


@app.route("/api/me/password", methods=["POST"])
def api_me_password():
    """Change your own password. The current one is always verified, including on the
    shared bootstrap password, so nobody can be locked in by someone else."""
    data = request.get_json(silent=True) or {}
    emp = current_employee()
    if not emp:
        raise ApiError("This login is not linked to an employee record, so there is no password here to change")
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""
    if not verify_employee_password(emp, current):
        raise ApiError("That is not your current password", 403)
    if len(new) < MIN_PASSWORD_LENGTH:
        raise ApiError(f"Use at least {MIN_PASSWORD_LENGTH} characters for the new password")
    if new == current:
        raise ApiError("The new password has to be different from the current one")
    db_update("employees", emp["id"], {"password_hash": generate_password_hash(new)})
    user = session.get("user") or {}
    user["must_set_password"] = False
    session["user"] = user
    return jsonify({"success": True, "message": "Password updated - use it next time you sign in"})


@app.route("/api/employees/<row_id>/reset-password", methods=["POST"])
@admin_required
def api_employee_reset_password(row_id):
    """HR hands out a one-time password; the employee replaces it in Me."""
    emp = db_get("employees", row_id)
    if not emp:
        raise ApiError("Employee not found", 404)
    temp = (request.get_json(silent=True) or {}).get("password") or new_temp_password()
    if len(temp) < MIN_PASSWORD_LENGTH:
        raise ApiError(f"A temporary password needs at least {MIN_PASSWORD_LENGTH} characters")
    db_update("employees", emp["id"], {"password_hash": generate_password_hash(temp)})
    who = (employee_display(emp["id"]) or {}).get("full_name") or "They"
    return jsonify({"success": True, "temp_password": temp, "employee": who,
                    "message": f"{who} can sign in with this password now - share it once and ask them to change it"})


@app.route("/api/employees/<row_id>/self-edit-fields")
@admin_required
def api_employee_self_fields(row_id):
    return jsonify(sorted(SELF_EDITABLE_FIELDS))


# =================================================================== timesheet
def enrich_timesheet(ts, entries=None, projects=None):
    pmap = projects if projects is not None else project_map()
    rows = entries if entries is not None else db_list("timesheet_entries", {"timesheet_id": ts.get("id")})
    by_day = {}
    for e in rows:
        day = str(e.get("date"))[:10]
        by_day.setdefault(day, []).append({"id": e.get("id"), "project_id": e.get("project_id"),
                                           "project": (pmap.get(str(e.get("project_id"))) or {}).get("name", "Internal"),
                                           "project_code": (pmap.get(str(e.get("project_id"))) or {}).get("code"),
                                           "billing_rate": money((pmap.get(str(e.get("project_id"))) or {}).get("billing_rate")),
                                           "hours": money(e.get("hours")), "billable": bool(e.get("billable")),
                                           "task": e.get("task") or ""})
    total = round(sum(money(e.get("hours")) for e in rows), 2)
    billable = round(sum(money(e.get("hours")) for e in rows if e.get("billable")), 2)
    return {**ts, "employee": employee_display(ts.get("employee_id")), "entries": by_day,
            "entry_count": len(rows), "total_hours": total, "billable_hours": billable,
            "billable_pct": round(billable / total * 100) if total else 0,
            "utilization_pct": round(total / 40 * 100) if total else 0,
            "week_label": f"{fmt_day(ts.get('week_starting'), '%d %b')} - {fmt_day(parse_day(ts.get('week_starting')) + timedelta(days=4), '%d %b %Y')}",
            "reviewer": employee_display(ts.get("approved_by")),
            "submitted_label": fmt_day(ts.get("submitted_at")), "approved_label": fmt_day(ts.get("approved_at"))}


def week_start(value):
    d = parse_day(value) or today()
    monday = d - timedelta(days=d.weekday())
    if monday > today():
        monday = today() - timedelta(days=today().weekday())
    return monday


@app.route("/api/timesheet")
def api_timesheet():
    view = request.args.get("view", "me")
    week = week_start(request.args.get("week"))
    week_s = str(week)
    projects = db_list("projects")
    pmap = {str(p["id"]): p for p in projects}
    if view == "team" and is_admin():
        sheets = [enrich_timesheet(t, projects=pmap) for t in db_list("timesheets", {"week_starting": week_s})]
        if request.args.get("employee_id"):
            sheets = [t for t in sheets if str(t.get("employee_id")) == request.args["employee_id"]]
        submitted = [t for t in sheets if t.get("status") in ("Submitted", "Approved")]
        return jsonify({"view": "team", "week": week_s, "week_label": sheets[0]["week_label"] if sheets else week_s,
                        "projects": projects, "timesheets": sheets,
                        "summary": {"team_size": len(sheets), "submitted": len(submitted),
                                    "awaiting_review": len([t for t in sheets if t.get("status") == "Submitted"]),
                                    "total_hours": round(sum(t["total_hours"] for t in sheets), 1),
                                    "billable_hours": round(sum(t["billable_hours"] for t in sheets), 1),
                                    "unapproved": len([t for t in sheets if t.get("status") != "Approved"])}})
    employee_id = request.args.get("employee_id") if is_admin() else None
    employee_id = employee_id or acting_employee_id()
    if not employee_id:
        raise ApiError("This login has no employee record to log time against")
    sheet = next((t for t in db_list("timesheets", {"employee_id": employee_id, "week_starting": week_s})), None)
    if sheet is None:
        sheet = {"employee_id": employee_id, "week_starting": week_s, "status": "Draft",
                 "submitted_at": None, "approved_by": None, "approved_at": None, "reviewer_remark": None}
    payload = enrich_timesheet(sheet, projects=pmap)
    payload["is_new"] = sheet.get("id") is None
    days = [{"date": str(week + timedelta(days=i)), "label": (week + timedelta(days=i)).strftime("%a"),
             "day_num": (week + timedelta(days=i)).strftime("%d %b"),
             "is_weekend": (week + timedelta(days=i)).weekday() >= 5,
             "is_future": (week + timedelta(days=i)) > today(),
             "entries": payload["entries"].get(str(week + timedelta(days=i)), [])} for i in range(7)]
    approved = [t for t in db_list("timesheets", {"employee_id": employee_id}) if t.get("status") == "Approved"]
    return jsonify({"view": "me", "week": week_s, "week_label": payload["week_label"], "timesheet": payload,
                    "days": days, "projects": [{"id": p["id"], "name": p["name"], "code": p.get("code"),
                                                "client": p.get("client"), "billing_rate": money(p.get("billing_rate")),
                                                "manager_id": p.get("manager_id"), "status": p.get("status")} for p in projects],
                    "locked": payload.get("status") in ("Approved",),
                    "can_review": is_admin(),
                    "stats": {"this_week": payload["total_hours"], "billable_week": payload["billable_hours"],
                              "avg_week": round(sum(money(t.get("total_hours")) for t in approved) / len(approved), 1) if approved else 0,
                              "weeks_logged": len([t for t in db_list("timesheets", {"employee_id": employee_id}) if t.get("status") != "Draft"]),
                              "awaiting_review": len([t for t in db_list("timesheets", {"employee_id": employee_id}) if t.get("status") == "Submitted"]),
                              "utilization": round(sum(money(t.get("billable_hours")) for t in approved) /
                                                    max(sum(money(t.get("total_hours")) for t in approved), 1) * 100) if approved else 0}})


@app.route("/api/timesheet/save", methods=["POST"])
def api_timesheet_save():
    """Upsert the whole week's grid: rows replace that week's entries."""
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id") if is_admin() else None
    employee_id = employee_id or acting_employee_id()
    if not employee_id:
        raise ApiError("This login has no employee record to log time against")
    week = str(week_start(data.get("week")))
    sheet = next((t for t in db_list("timesheets", {"employee_id": employee_id, "week_starting": week})), None)
    if sheet and sheet.get("status") == "Approved" and not is_admin():
        raise ApiError("This week is approved and locked. Ask HR to reopen it if something is wrong.")
    rows = []
    for entry in data.get("entries") or []:
        hours = money(entry.get("hours"))
        if hours <= 0:
            continue
        day = str(entry.get("date") or "")[:10]
        if not day or parse_day(day) is None:
            raise ApiError("Every time entry needs a valid date")
        if not entry.get("project_id"):
            raise ApiError(f"Pick a project for {fmt_day(day)}")
        if hours > 16:
            raise ApiError(f"{hours:.1f} hours on {fmt_day(day)} is more than a day allows")
        rows.append({"date": day, "project_id": entry["project_id"], "hours": hours,
                     "billable": bool(entry.get("billable")), "task": (entry.get("task") or "").strip()[:250]})
    totals = round(sum(r["hours"] for r in rows), 2)
    billable_total = round(sum(r["hours"] for r in rows if r["billable"]), 2)
    payload = {"employee_id": employee_id, "week_starting": week, "status": "Draft",
               "total_hours": totals, "billable_hours": billable_total}
    if sheet:
        sheet = db_update("timesheets", sheet["id"], payload)
    else:
        payload.update({"submitted_at": None, "approved_by": None, "approved_at": None, "reviewer_remark": None})
        sheet = db_insert("timesheets", payload)
    for entry_id in {e.get("id") for e in db_list("timesheet_entries", {"timesheet_id": sheet["id"]})}:
        db_delete("timesheet_entries", entry_id)
    for r in rows:
        db_insert("timesheet_entries", {"timesheet_id": sheet["id"], "employee_id": employee_id, **r})
    return jsonify({"success": True, "timesheet": enrich_timesheet(sheet, projects=project_map()),
                    "message": f"{totals:.1f} hours saved for the week of {fmt_day(week, '%d %b')}"})


@app.route("/api/timesheet/submit", methods=["POST"])
def api_timesheet_submit():
    data = request.get_json(silent=True) or {}
    week = str(week_start(data.get("week")))
    employee_id = acting_employee_id()
    sheet = next((t for t in db_list("timesheets", {"employee_id": employee_id, "week_starting": week})), None)
    if not sheet:
        raise ApiError("Log your hours before submitting the week")
    if sheet.get("status") == "Submitted":
        raise ApiError("This week is already with your approver")
    if sheet.get("status") == "Approved":
        raise ApiError("This week is already approved")
    entries = db_list("timesheet_entries", {"timesheet_id": sheet["id"]})
    total = round(sum(money(e.get("hours")) for e in entries), 1)
    if total < 20:
        raise ApiError(f"Only {total} hours logged - add the rest of the week or raise a note with HR before submitting")
    updated = db_update("timesheets", sheet["id"], {"status": "Submitted", "submitted_at": str(today()),
                                                     "total_hours": total,
                                                     "billable_hours": round(sum(money(e.get("hours")) for e in entries if e.get("billable")), 1)})
    return jsonify({"success": True, "timesheet": enrich_timesheet(updated),
                    "message": f"Week of {fmt_day(week, '%d %b')} submitted for approval ({total} h)"})


@app.route("/api/timesheets/<row_id>/action", methods=["POST"])
@admin_required
def api_timesheet_action(row_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    sheet = db_get("timesheets", row_id)
    if not sheet:
        raise ApiError("Timesheet not found", 404)
    if action not in ("approve", "reject", "reopen"):
        raise ApiError("Use 'approve', 'reject' or 'reopen'")
    if action == "reject" and not (data.get("remark") or "").strip():
        raise ApiError("Tell the employee what to fix")
    status = {"approve": "Approved", "reject": "Rejected", "reopen": "Draft"}[action]
    updated = db_update("timesheets", row_id, {"status": status,
                                              "approved_by": acting_employee_id() if action == "approve" else None,
                                              "approved_at": str(today()) if action == "approve" else None,
                                              "reviewer_remark": (data.get("remark") or "").strip() or None})
    return jsonify({"success": True, "timesheet": enrich_timesheet(updated),
                    "message": f"{employee_display(sheet.get('employee_id'))['full_name']}'s week of {fmt_day(sheet.get('week_starting'), '%d %b')} {status.lower()}"})


@app.route("/api/timesheet/history")
def api_timesheet_history():
    employee_id = request.args.get("employee_id") if is_admin() else None
    employee_id = employee_id or acting_employee_id()
    filters = {"employee_id": employee_id} if employee_id else {}
    rows = [enrich_timesheet(t, projects=project_map()) for t in db_list("timesheets", filters, order="week_starting", descending=True)]
    return jsonify(rows[:60])


@app.route("/api/timesheet/export")
def api_timesheet_export():
    employee_id = request.args.get("employee_id") if is_admin() else None
    employee_id = employee_id or acting_employee_id()
    sheets = {str(t["id"]): t for t in db_list("timesheets", {"employee_id": employee_id} if employee_id else None)}
    rows = []
    pmap = project_map()
    emap = employees_map()
    for e in db_list("timesheet_entries"):
        sheet = sheets.get(str(e.get("timesheet_id")))
        if not sheet:
            continue
        emp = emap.get(str(sheet.get("employee_id")), {})
        rows.append({"employee": emp.get("full_name"), "employee_code": emp.get("employee_code"),
                     "week": sheet.get("week_starting"), "date": e.get("date"),
                     "project": (pmap.get(str(e.get("project_id"))) or {}).get("name"),
                     "task": e.get("task"), "hours": e.get("hours"),
                     "billable": "Yes" if e.get("billable") else "No", "status": sheet.get("status")})
    return csv_response("timesheet_export", list(rows[0].keys()) if rows else ["employee"], rows)


@app.route("/api/projects")
def api_projects():
    entries = db_list("timesheet_entries")
    sheets = {str(t.get("id")): t for t in db_list("timesheets")}
    this_week = str(week_start(None))
    rows = []
    for p in db_list("projects"):
        mine = [e for e in entries if str(e.get("project_id")) == str(p.get("id"))]
        people = sorted({(employee_display(sheets.get(str(e.get("timesheet_id")), {}).get("employee_id")) or {}).get("full_name")
                         for e in mine if sheets.get(str(e.get("timesheet_id")))}, key=str)
        rows.append({**p, "manager": employee_display(p.get("manager_id")), "team": [n for n in people if n],
                     "team_size": len([n for n in people if n]),
                     "total_hours": round(sum(money(e.get("hours")) for e in mine), 1),
                     "billable_hours": round(sum(money(e.get("hours")) for e in mine if e.get("billable")), 1),
                     "hours_this_week": round(sum(money(e.get("hours")) for e in mine
                                                    if sheets.get(str(e.get("timesheet_id")), {}).get("week_starting") == this_week), 1),
                     "billable_value": round(sum(money(e.get("hours")) for e in mine if e.get("billable")) * money(p.get("billing_rate")), 0),
                     "contributors": len({str(sheets.get(str(e.get("timesheet_id")), {}).get("employee_id")) for e in mine if sheets.get(str(e.get("timesheet_id")))})})
    return jsonify(rows)


PROJECT_STATUSES = ("Active", "On Hold", "Completed", "Closed")


def _project_code(name):
    """A short unique code for a project, derived from its name.

    `projects.code` is `not null` and carries a unique index, so a generated code has to be checked
    against the rows on file here instead of arriving as a Postgres constraint error.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(name or "")) if w]
    one = re.sub(r"[^A-Z0-9]", "", words[0].upper())[:4] if words else "PRJ"
    two = re.sub(r"[^A-Z0-9]", "", words[1].upper())[:5] if len(words) > 1 else ""
    base = (f"PRJ-{one}-{two}" if two else f"PRJ-{one}")[:20].strip("-")
    taken = {str(p.get("code") or "").strip().upper() for p in db_list("projects")}
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}"[:20].strip("-") in taken:
        n += 1
    return f"{base}-{n}"[:20].strip("-")


def _clean_project(data, current=None, existing=None):
    """Validate a project form into a write payload.

    A PUT only has to carry what it touched (the "mark this Completed" action sends one key), so any
    field left out of the body is taken from the row on file - the same rule the salary structures
    follow, and for the same reason: a partial form must not blank anything.
    """
    def field(key):
        return data.get(key) if key in data else (existing or {}).get(key)

    name = str(field("name") or "").strip()
    if not name:
        raise ApiError("A project needs a name")
    if len(name) > 60:
        raise ApiError("Keep the project name under 60 characters")
    rows = db_list("projects")
    twin = next((q for q in rows if str(q.get("name")).strip().lower() == name.lower()
                 and str(q.get("id")) != str(current)), None)
    if twin:
        raise ApiError(f"A project called {name} already exists (code {twin.get('code')}) - log your hours against "
                       "that one, or name this one differently")
    code = re.sub(r"[^A-Z0-9-]+", "-", str(field("code") or "").strip().upper()).strip("-")[:20]
    if code in ("", "NONE", "NULL"):
        code = _project_code(name)
    if len(code) < 3:
        raise ApiError(f"Code {code or '(blank)'} is too short - three characters minimum, something like CLNT-ACME")
    clash = next((q for q in rows if str(q.get("code") or "").strip().upper() == code.upper()
                  and str(q.get("id")) != str(current)), None)
    if clash:
        raise ApiError(f"{code} is already the code for {clash.get('name')} - pick another one")
    rate = money(field("billing_rate"))
    if rate < 0:
        raise ApiError("A billing rate cannot be negative - use 0 for internal work")
    status = str(field("status") or "Active").strip()
    if status not in PROJECT_STATUSES:
        raise ApiError("Project status must be one of " + ", ".join(PROJECT_STATUSES))
    payload = {"name": name, "code": code, "client": str(field("client") or "").strip()[:60] or None,
               "billing_rate": round(rate, 2), "status": status}
    manager = field("manager_id")
    if manager in (None, "", "None", "All"):
        payload["manager_id"] = (existing or {}).get("manager_id") if current else None
    else:
        if not db_get("employees", manager):
            raise ApiError("The project manager has to be someone on the employee list")
        payload["manager_id"] = str(manager)
    return payload


def project_mutable(project):
    """An HR Admin, or the person the project is filed under, may change it.

    Seeded projects already name a manager, so a manager fixes a typo themselves instead of raising
    a ticket; anything with no manager at all falls back to HR.
    """
    if is_admin():
        return True
    me = acting_employee_id()
    return bool(me) and bool(project.get("manager_id")) and str(me) == str(project.get("manager_id"))


@app.route("/api/projects", methods=["POST"])
def api_project_create():
    """People open their own projects - a fixed list of five is what made the grid unusable."""
    data = request.get_json(silent=True) or {}
    payload = _clean_project(data)
    me = acting_employee_id()
    if not payload.get("manager_id") and me:
        payload["manager_id"] = str(me)          # whoever raised it owns it until HR says otherwise
    created = db_insert("projects", payload)
    return jsonify({"success": True, "project": created,
                    "message": f"{created.get('name')} is on the project list - pick it in the grid and log against it"})


@app.route("/api/projects/<row_id>", methods=["PUT", "DELETE"])
def api_project_row(row_id):
    project = db_get("projects", row_id)
    if not project:
        raise ApiError("Project not found", 404)
    if not project_mutable(project):
        manager = (employee_display(project.get("manager_id")) or {}).get("full_name")
        who = f"the project manager ({manager})" if manager else "an HR Admin"
        raise ApiError(f"Only {who} can change {project.get('name')} - ask them, or have HR reassign the project first", 403)
    if request.method == "DELETE":
        entries = [e for e in db_list("timesheet_entries") if str(e.get("project_id")) == str(row_id)]
        if entries:
            hours = round(sum(money(e.get("hours")) for e in entries), 1)
            many = "entry" if len(entries) == 1 else "entries"
            raise ApiError(f"{project.get('name')} already has {len(entries)} logged {many} worth {hours} h - mark it "
                           "Completed instead, so the time people claimed keeps somewhere to live")
        db_delete("projects", row_id)
        return jsonify({"success": True, "message": f"{project.get('name')} is off the project list"})
    data = request.get_json(silent=True) or {}
    updated = db_update("projects", row_id, _clean_project(data, current=row_id, existing=project))
    return jsonify({"success": True, "project": updated,
                    "message": f"{updated.get('name')} saved - {updated.get('status')}, code {updated.get('code')}"})


# =================================================================== payroll
PAYROLL_STATUSES = ("Draft", "Published", "Paid")
# (column, payslip label) - the order here is the order a payslip prints them in.
PAYROLL_EARNINGS = (("basic", "Basic"), ("hra", "HRA"), ("special_allowance", "Special Allowance"))
PAYROLL_DEDUCTIONS = (("pf", "Provident Fund"), ("esi", "ESI"),
                      ("professional_tax", "Professional Tax"), ("tds", "TDS / Income Tax"))
# Attendance statuses that cost pay, and how much of a day each one costs.
LOP_WEIGHTS = {"Absent": 1.0, "Absent - Unauthorised": 1.0, "Half Day": 0.5, "Half-day": 0.5}


def allowance_map(value):
    """Extra monthly earnings on a structure, stored as a jsonb object like `competencies`.

    Postgres sorts jsonb keys, so the column cannot carry a display order; sorting in Python means
    the same structure prints in the same order in demo mode and in the cloud.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except ValueError:
            return {}
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, amount in value.items():
        label = str(key).strip()[:40]
        if label:
            out[label] = round(money(amount), 2)
    return dict(sorted(out.items()))


def structure_lines(structure):
    """(earnings lines, deduction lines, monthly gross, monthly deductions) for one structure."""
    if not structure:
        return [], [], 0.0, 0.0
    earn = [{"label": label, "amount": round(money(structure.get(col)), 2)} for col, label in PAYROLL_EARNINGS]
    earn += [{"label": label, "amount": amount}
             for label, amount in allowance_map(structure.get("allowances")).items() if amount]
    ded = [{"label": label, "amount": round(money(structure.get(col)), 2)} for col, label in PAYROLL_DEDUCTIONS]
    return earn, ded, round(sum(x["amount"] for x in earn), 2), round(sum(x["amount"] for x in ded), 2)


def current_structure(employee_id, on=None):
    """The payroll structure that pays this person on a date (default: today).

    A person may hold several - one per revision - and the latest one that has already begun is the
    live one. Sorted here rather than with an ORDER BY so a stale deployment missing a column cannot
    break payroll the way it once broke the feedback list.
    """
    if not employee_id:
        return {}
    rows = [s for s in db_list("payroll_structures", {"employee_id": employee_id})]
    if not rows:
        return {}
    day = str(on or today())[:10]
    live = [s for s in rows if str(s.get("effective_from") or "")[:10] <= day]
    return max(live or rows, key=lambda s: (str(s.get("effective_from") or ""), str(s.get("id"))))


def enrich_structure(structure, employee=None):
    """A structure plus every figure the UI would otherwise have to compute (and get wrong)."""
    if not structure:
        return {}
    emp = employee if employee is not None else (employee_display(structure.get("employee_id")) or {})
    earn, ded, gross, total_ded = structure_lines(structure)
    employer_pf = round(money(structure.get("employer_pf")), 2)
    stored_ctc = money(structure.get("ctc"))
    derived_ctc = round((gross + employer_pf) * 12, 2)
    ctc = stored_ctc or derived_ctc
    net = round(gross - total_ded, 2)
    row = dict(structure)
    row.update({
        "employee": emp or None, "employee_name": (emp or {}).get("full_name"),
        "department": (emp or {}).get("department"), "designation": (emp or {}).get("designation"),
        "earnings": earn, "deductions": ded, "allowances": allowance_map(structure.get("allowances")),
        "allowance_labels": ", ".join(allowance_map(structure.get("allowances"))) or "—",
        "monthly_gross": gross, "monthly_deductions": total_ded, "monthly_net": net,
        "monthly": gross,                                  # the key the structures table already reads
        "monthly_gross_label": inr(gross), "monthly_net_label": inr(net),
        "employer_pf": employer_pf, "derived_ctc": derived_ctc,
        "ctc": ctc, "ctc_label": inr(ctc), "ctc_drift": round(stored_ctc - derived_ctc, 2) if stored_ctc else 0.0,
        "name": structure.get("name") or "Standard", "effective_from_label": fmt_day(structure.get("effective_from")),
        "net_pct_of_gross": round(net / gross * 100) if gross else 0,
        "form": {col: money(structure.get(col)) for col, _ in PAYROLL_EARNINGS + PAYROLL_DEDUCTIONS}
                | {"employer_pf": employer_pf, "ctc": stored_ctc, "name": structure.get("name") or "Standard",
                   "effective_from": str(structure.get("effective_from") or "")[:10] or str(today()),
                   "allowances": [{"label": k, "amount": v} for k, v in allowance_map(structure.get("allowances")).items()]},
    })
    return row


def amount_in_words(value):
    """Money as an Indian payslip writes it: Rupees Twelve Lakh Fifty Thousand Only."""
    ones = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen "
            "Fifteen Sixteen Seventeen Eighteen Nineteen").split()
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(n):
        return ones[n] if n < 20 else (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()

    def three(n):
        bits = ([f"{ones[n // 100]} Hundred"] if n // 100 else []) + ([two(n % 100)] if n % 100 else [])
        return " ".join(bits)

    amount = round(money(value), 2)
    whole = int(amount)
    if whole <= 0 and amount <= 0:
        return "Rupees Zero Only"
    crore, rest = divmod(whole, 10 ** 7)
    lakh, rest = divmod(rest, 10 ** 5)
    thousand, rest = divmod(rest, 10 ** 3)
    hundred, rem = divmod(rest, 100)
    parts = []
    if crore:
        parts.append(three(crore) + " Crore")
    if lakh:
        parts.append(three(lakh) + " Lakh")
    if thousand:
        parts.append(three(thousand) + " Thousand")
    if hundred:
        parts.append(f"{ones[hundred]} Hundred")
    if rem:
        parts.append(two(rem))
    paise = int(round((amount - whole) * 100))
    out = "Rupees " + " ".join(parts)
    if paise:
        out += f" and {two(paise)} Paise"
    return out + " Only"


def compute_payout(structure, extra_earnings=0, extra_deductions=0, paid_days=26, total_days=26):
    """Gross, deductions and net for one month, including loss of pay.

    Allowances on the structure are part of gross and are also the base for LOP: a per-day rate that
    ignored an allowance would quietly overpay anyone with unpaid days.
    """
    earn, ded, gross_fixed, ded_fixed = structure_lines(structure)
    extra_earnings, extra_deductions = round(money(extra_earnings), 2), round(money(extra_deductions), 2)
    gross = round(gross_fixed + extra_earnings, 2)
    lwp = 0.0
    total_days, paid_days = money(total_days), money(paid_days)
    if total_days > 0 and paid_days < total_days:
        lwp = round(gross_fixed / max(total_days, 1) * min(total_days - paid_days, total_days), 2)
    deductions = round(ded_fixed + extra_deductions + lwp, 2)
    earnings = list(earn)
    if extra_earnings:
        earnings.append({"label": "Bonus / Arrears", "amount": extra_earnings})
    deductions_lines = list(ded)
    if lwp:
        deductions_lines.append({"label": f"Loss of Pay ({round(total_days - paid_days, 2)} d)", "amount": lwp})
    if extra_deductions:
        deductions_lines.append({"label": "Other Recovery", "amount": extra_deductions})
    return {"earnings": earnings, "deductions": deductions_lines, "gross": gross,
            "deductions_total": deductions, "net": round(gross - deductions, 2), "lwp": lwp,
            "fixed_gross": gross_fixed}


def payroll_period(data=None, args=None):
    """(year, month) for a payroll call, from ?period= / ?month=&year= or a JSON body.

    Every shape a person or the report builder can type is accepted - '2026-08', '2026/08', month 8,
    month '8' - and anything else is a 400 that says what was expected instead of a 500 from int().
    """
    data, args = data or {}, args or request.args
    raw = str(data.get("period") or args.get("period") or args.get("month") or "").strip()
    year = data.get("year") or args.get("year")
    year, month = (int(year) if str(year or "").isdigit() else None), None
    if raw:
        bits = [b for b in re.split(r"[^0-9]+", raw) if b]
        if not bits:
            raise ApiError("period must look like 2026-08 (or pass month 1-12 with a year)")
        try:
            numbers = [int(b) for b in bits]
        except ValueError:
            raise ApiError("period must look like 2026-08 (or pass month 1-12 with a year)")
        if len(numbers) >= 2:
            year, month = numbers[-2], numbers[-1]
        elif len(numbers) == 1:
            month = numbers[0]
            if month > 31:                      # '202608' is a period someone pasted from a URL
                year, month = month // 100, month % 100
    if month is None and data.get("month") not in (None, ""):
        month = int(money(data.get("month")))
    if month is not None and not 1 <= month <= 12:
        raise ApiError("month must be between 1 and 12")
    if year is not None and not 2000 <= year <= 2100:
        raise ApiError("year must be between 2000 and 2100")
    if month is None:
        raise ApiError("Pick the month you mean, for example 2026-08")
    if year is None:
        year = today().year
    return year, month


def month_end(year, month):
    return date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)


def unpaid_leave_days(employee_id, year, month):
    """ISO dates this person was on approved *paid* leave for, and those on approved unpaid leave.

    Payroll needs both: unpaid days are loss of pay, paid days must not be counted as absences even
    when attendance still says 'On Leave'.
    """
    types = {str(t.get("id")): t for t in db_list("leave_types")}
    first, last = date(year, month, 1), month_end(year, month)
    paid, unpaid = set(), set()
    for req in db_list("leave_requests", {"employee_id": employee_id, "status": "Approved"}):
        start, end = parse_day(req.get("start_date")), parse_day(req.get("end_date")) or parse_day(req.get("start_date"))
        if not start:
            continue
        kind = types.get(str(req.get("leave_type_id"))) or {}
        bucket = unpaid if kind and not kind.get("is_paid", True) else paid
        day, stop = max(start, first), min(end or start, last)
        while day <= stop:
            bucket.add(day.isoformat())
            day += timedelta(days=1)
    return paid, unpaid


def payroll_days(employee, year, month, through=None):
    """Working, payable and lost days for one person-month, read from the register.

    Only Mon-Fri days that are not gazetted holidays count, and the window starts on the joining date
    and stops on the exit date so a mid-month joiner is not paid (or docked) for days they were not
    employed for. A working day that is already over with no punch on file is Absent - the verdict the
    attendance screen shows - and it costs a day's pay. Three things keep that from punishing anyone by
    accident: today is never docked (the punch may still come, only days up to yesterday count), a day
    with a *pending* regularization request is left alone until it is decided, and approved **paid**
    leave keeps the day off the list. Unpaid leave on an unpunched day is loss of pay, exactly as it is
    when a row says On Leave.
    """
    first, last = date(year, month, 1), month_end(year, month)
    off = {str(h.get("date"))[:10] for h in db_list("holidays") if str(h.get("date"))[:7] == f"{year:04d}-{month:02d}"}
    working = [first + timedelta(days=i) for i in range((last - first).days + 1)
               if (first + timedelta(days=i)).weekday() < 5 and (first + timedelta(days=i)).isoformat() not in off]
    joining, exit_day = parse_day(employee.get("date_of_joining")), parse_day(employee.get("exit_date"))
    if joining:
        working = [d for d in working if d >= joining]
    if exit_day:
        working = [d for d in working if d <= exit_day]
    if through:
        working = [d for d in working if d <= through]
    rows = db_list("attendance", {"employee_id": employee.get("id")})
    attendance = {str(a.get("date"))[:10]: a for a in rows}
    _, unpaid = unpaid_leave_days(employee.get("id"), year, month)
    # the register's verdict for a day nobody punched, so a slip and the attendance screen agree
    unpunched = {str(r.get("date"))[:10]: r for r in missing_attendance_rows(
        first, last, rows, employees=[employee], holidays=[{"date": d} for d in off],
        leaves=db_list("leave_requests", {"employee_id": employee.get("id")}),
        regularizations=db_list("attendance_regularizations", {"employee_id": employee.get("id")}))}
    lop, lost = 0.0, []
    for day in working:
        iso = day.isoformat()
        row = attendance.get(iso) or unpunched.get(iso)
        if not row:
            continue              # a day still to come, or one whose regularization is not decided yet
        status = str(row.get("status") or "").strip()
        weight = LOP_WEIGHTS.get(status)
        if weight is None and status == "On Leave" and iso in unpaid:
            weight = 1.0
        if weight:
            lop += weight
            lost.append({"date": iso, "label": fmt_day(day), "days": weight,
                         "kind": status if status != "On Leave" else "Unpaid leave"})
    return {"working_days": len(working), "lop_days": round(lop, 2),
            "payable_days": round(len(working) - lop, 2), "lost_days": lost,
            "holidays": len(off), "note": f"{len(working)} working day(s), {round(lop, 2)} lost"}


def enrich_payslip(p):
    row = dict(p)
    row["employee"] = employee_display(row.get("employee_id"))
    year, month = int(money(row.get("year"))), int(money(row.get("month")))
    try:
        month_name = datetime.strptime(str(month).zfill(2), "%m").strftime("%B")
    except (TypeError, ValueError):
        month_name = str(row.get("month"))
    row["period"] = row.get("period") or (f"{year:04d}-{month:02d}" if year and month else "")
    row["period_label"] = f"{month_name} {year}"
    row["net_pay_label"] = inr(row.get("net_pay"))
    row["gross_earnings_label"] = inr(row.get("gross_earnings"))
    row["total_deductions_label"] = inr(row.get("total_deductions"))
    row["bonus_label"] = inr(row.get("bonus")) if money(row.get("bonus")) else ""
    row["paid_on_label"] = fmt_day(row.get("paid_on") or row.get("generated_at"))
    row["net_pct_of_gross"] = round(money(row.get("net_pay")) / money(row.get("gross_earnings")) * 100) \
        if money(row.get("gross_earnings")) else 0
    working, payable, lop = money(row.get("working_days")), money(row.get("payable_days")), money(row.get("lop_days"))
    row["days_label"] = f"{payable:g} of {working:g} paid · {lop:g} LOP" if working else "—"
    row["lop_days"] = round(lop, 2)
    row["net_in_words"] = amount_in_words(row.get("net_pay"))
    row["is_draft"] = str(row.get("status") or "Draft") == "Draft"
    row["status_label"] = {"Draft": "Draft - not released", "Published": "Published", "Paid": "Paid"}.get(
        str(row.get("status") or "Draft"), str(row.get("status") or "Draft"))
    return row


def payslip_for(employee_id, year, month):
    rows = db_list("payslips", {"employee_id": employee_id, "year": year, "month": month})
    return rows[0] if rows else None


def month_year_from_args():
    """Read the ?month=&year= pair shared by the payroll routes.

    Kept for the two endpoints that already used it; `payroll_period` is the same reader with a
    `period` shape and a body, which is what the run and the register use.
    """
    year_raw = (request.args.get("year") or "").strip()
    month = year = None
    raw_month = (request.args.get("month") or "").strip()
    bits = [b for b in re.split(r"[^0-9]+", raw_month) if b]
    if raw_month and not bits:      # "september" is a mistake, not an absent filter
        raise ApiError("month must be a number 1-12 or a period like 2026-08")
    if bits:
        try:
            month = int(bits[-1])
            if len(bits) > 1:
                year = int(bits[-2])
        except ValueError:
            raise ApiError("month must be a number 1-12 or a period like 2026-08")
        if not 1 <= month <= 12:
            raise ApiError("month must be between 1 and 12")
    if year_raw:
        if not year_raw.isdigit():
            raise ApiError("year must be a four digit number")
        year = int(year_raw)
    return year, month


@app.route("/api/payslips")
def api_payslips():
    employee_id = scoped_employee_id()
    # ?period=2026-09 is what the payroll screens hold on to; month/year stay for the older links
    if request.args.get("period"):
        year, month = payroll_period(args=request.args)
    else:
        year, month = month_year_from_args()
    filters = dict({"employee_id": employee_id} if employee_id else {})
    if year and month:      # `period` is a real column, so this is one equality test, not a scan
        filters["period"] = f"{year:04d}-{month:02d}"
    rows = db_list("payslips", filters or None, order="year", descending=True)
    if month and not (year and month):
        rows = [r for r in rows if int(money(r.get("month")) or 0) == month]
    if year and not month:
        rows = [r for r in rows if int(money(r.get("year")) or 0) == year]
    if not employee_id and request.args.get("employee_id"):
        rows = [r for r in rows if str(r.get("employee_id")) == str(request.args.get("employee_id")).strip()]
    out = [enrich_payslip(r) for r in rows]
    if not is_admin():
        out = [r for r in out if str(r.get("status") or "Draft") != "Draft"]
    return jsonify(sorted(out, key=lambda r: (str(r.get("period")), str((r.get("employee") or {}).get("full_name"))),
                          reverse=True))


@app.route("/api/payslips/<row_id>/detail")
def api_payslip_detail(row_id):
    slip = db_get("payslips", row_id)
    if not slip:
        raise ApiError("Payslip not found", 404)
    slip = enrich_payslip(slip)
    if not is_admin() and str(slip.get("employee_id")) != str(acting_employee_id()):
        raise ApiError("You can only open your own payslips", 403)
    if slip.get("is_draft"):
        raise ApiError("This payslip is still being prepared - HR will publish it for {period}".format(
            period=slip.get("period_label") or "that month"), 404)
    employee = employees_map().get(str(slip.get("employee_id"))) or {}
    structure = current_structure(slip.get("employee_id"), on=f"{slip.get('period')}-28" if slip.get("period") else None)
    year, month = int(money(slip.get("year"))), int(money(slip.get("month")))
    if slip.get("period"):        # a slip stores the days it was built from; re-derive only when absent
        days = {"working_days": money(slip.get("working_days")), "payable_days": money(slip.get("payable_days")),
                "lop_days": money(slip.get("lop_days")), "lost_days": [], "note": ""}
        if not days["working_days"]:
            days = payroll_days(employee or {"id": slip.get("employee_id")}, year, month)
    else:
        days = payroll_days(employee or {"id": slip.get("employee_id")}, year, month)
    payout = compute_payout(structure, extra_earnings=slip.get("bonus"), extra_deductions=slip.get("deductions"),
                            paid_days=days["payable_days"] or 26, total_days=days["working_days"] or 26)
    if money(slip.get("gross_earnings")):      # the stored slip is authoritative for published/paid periods
        gross, deductions = money(slip.get("gross_earnings")), money(slip.get("total_deductions"))
        net = money(slip.get("net_pay")) or round(gross - deductions, 2)
    else:
        gross, deductions, net = payout["gross"], payout["deductions_total"], payout["net"]
    leaves = [l for l in db_list("leave_requests", {"employee_id": slip.get("employee_id"), "status": "Approved"})
              if str(l.get("start_date"))[:7] == f"{year:04d}-{month:02d}"]
    return jsonify({"payslip": slip, "structure": enrich_structure(structure, employee_display(slip.get("employee_id"))),
                    "earnings": payout["earnings"], "deductions": payout["deductions"],
                    "gross": gross, "deductions_total": deductions, "net": net,
                    "net_in_words": amount_in_words(net), "days": days,
                    "lop_days": days["lop_days"], "payable_days": days["payable_days"],
                    "working_days": days["working_days"], "period": slip.get("period"),
                    "leaves_in_period": [enrich_leave_row(l) for l in leaves],
                    "bank": {"bank_name": employee.get("bank_name") or "—",
                             "account": str(employee.get("bank_account_no") or "—")[-4:] and
                                        "•••• " + str(employee.get("bank_account_no"))[-4:] or "—",
                             "ifsc": employee.get("ifsc_code") or "—", "pan": employee.get("pan_no") or "—",
                             "uan": employee.get("uan_no") or "—", "pf": employee.get("pf_no") or "—"},
                    "company": {"name": "Modish Enterprises", "gstin": "29AABCE1234F1Z5",
                                "address": "Prestige Tech Park, Outer Ring Road, Bengaluru 560103"}})


@app.route("/api/payroll/structures")
def api_payroll_structures():
    """HR manages every structure; anyone signed in can read their own.

    A GET for HR returns one row per employee, including the ones with no structure at all - the
    screen has to be able to say 'no structure yet, add one' instead of the row disappearing, which
    is what made this tab look empty.
    """
    if is_admin():
        want = (request.args.get("employee_id") or "").strip()
        only = (request.args.get("only") or "").strip().lower()
        search = (request.args.get("q") or "").strip().lower()
        people = [e for e in db_list("employees") if e.get("status") != "Exited"
                  and (not want or str(e.get("id")) == want)
                  and (not search or search in " ".join(str(e.get(f) or "") for f in
                                                          ("full_name", "employee_code", "email")).lower())]
        rows = []
        for emp in sorted(people, key=lambda e: str(e.get("full_name") or "").lower()):
            structure = current_structure(emp.get("id"))
            if structure:
                row = enrich_structure(structure, employee_display(emp.get("id")))
                row["missing"] = False
            else:
                row = {"id": None, "missing": True, "employee": employee_display(emp.get("id")),
                       "employee_name": emp.get("full_name"), "name": "—", "department": emp.get("department"),
                       "earnings": [], "deductions": [], "allowances": {}, "monthly_gross": 0,
                       "monthly_deductions": 0, "monthly_net": 0, "monthly": 0, "ctc": money(emp.get("salary_ctc")),
                       "ctc_label": inr(emp.get("salary_ctc")), "derived_ctc": round(money(emp.get("salary_ctc")), 2),
                       "ctc_drift": 0, "effective_from": None, "effective_from_label": "—", "form": {},
                       "allowance_labels": "—", "monthly_gross_label": inr(0), "monthly_net_label": inr(0),
                       "net_pct_of_gross": 0, "employer_pf": 0, "notes": ""}
            if only == "missing" and not row["missing"]:
                continue
            if only == "present" and row["missing"]:
                continue
            rows.append(row)
        return jsonify(rows)
    mine = acting_employee_id()
    if not mine:
        raise ApiError("No employee profile is linked to this account", 403)
    structure = current_structure(mine)
    return jsonify([enrich_structure(structure)] if structure else [])


def parse_structure_payload(data, employee=None, existing=None):
    """Read, validate and normalise a structure form.

    Components are monthly because that is what a payroll person thinks in; `ctc` is annual and is
    derived from them. An explicit CTC is allowed only when it reconciles - accepting a figure no
    combination of components can pay is how a payroll module starts disagreeing with itself.
    """
    def value(col):
        """A field the form did not send keeps its stored value.

        A PUT that re-sent only the two numbers someone nudged used to zero every other component -
        allowances, employer PF, even the name - because the payload was built from the request alone.
        """
        return round(money(data.get(col)), 2) if col in data and data.get(col) is not None \
            else round(money((existing or {}).get(col)), 2)

    earn = {col: value(col) for col, _ in PAYROLL_EARNINGS}
    ded = {col: value(col) for col, _ in PAYROLL_DEDUCTIONS}
    for col, label in PAYROLL_EARNINGS + PAYROLL_DEDUCTIONS:
        if money(data.get(col)) < 0:
            raise ApiError(f"{label} cannot be negative")
    allowances = {}
    raw_allow = data["allowances"] if "allowances" in data else (existing or {}).get("allowances")
    if isinstance(raw_allow, list):
        raw_allow = {str(a.get("label") or "").strip(): a.get("amount") for a in raw_allow if isinstance(a, dict)}
    if isinstance(raw_allow, dict):
        for label, amount in raw_allow.items():
            label = str(label).strip()[:40]
            if not label:
                continue
            if money(amount) < 0:
                raise ApiError(f"{label} cannot be negative")
            allowances[label] = round(money(amount), 2)
    employer_pf = value("employer_pf")
    gross = round(sum(earn.values()) + sum(allowances.values()), 2)
    if gross <= 0:
        raise ApiError("Enter at least one earning component - basic, HRA, special allowance or an allowance")
    if earn["hra"] > earn["basic"] > 0:
        raise ApiError("HRA cannot be more than basic pay - it is a share of basic (40-50% is usual)")
    total_ded = round(sum(ded.values()), 2)
    if total_ded >= gross:
        raise ApiError(f"Deductions of {inr(total_ded)} are not less than gross of {inr(gross)} - the net pay would not be positive")
    if employer_pf < 0:
        raise ApiError("Employer PF cannot be negative")
    derived_ctc = round((gross + employer_pf) * 12, 2)
    # CTC is a summary of the components, never a stored truth: an explicit figure is checked against
    # them and the derived one is what gets written, so a PUT that only nudges basic does not inherit
    # a now-wrong CTC from last time.
    stated_ctc = round(money(data.get("ctc")), 2)
    if stated_ctc and abs(stated_ctc - derived_ctc) > max(100.0, derived_ctc * 0.01):
        raise ApiError(f"CTC {inr(stated_ctc)} does not match these components ({inr(derived_ctc)} a year from "
                       f"{inr(gross)} a month plus {inr(employer_pf)} employer PF). Leave CTC blank to take the derived figure.")
    name = str(data.get("name") or (existing or {}).get("name") or "Standard").strip()
    if len(name) > 60:
        raise ApiError("Structure name must be 60 characters or fewer")
    effective = str(parse_day(data.get("effective_from")) or parse_day((existing or {}).get("effective_from"))
                    or (employee or {}).get("date_of_joining") or today())
    if parse_day(effective) and parse_day(effective) > today():
        raise ApiError("A structure cannot start in the future - payroll would have nothing to pay from")
    payload = {"employee_id": (employee or {}).get("id") or (existing or {}).get("employee_id"),
               "name": name, "effective_from": effective, "ctc": derived_ctc, "employer_pf": employer_pf,
               "allowances": allowances, **earn, **ded}
    return payload, {"gross": gross, "deductions": total_ded, "net": round(gross - total_ded, 2),
                     "derived_ctc": derived_ctc}


@app.route("/api/payroll/structures", methods=["POST"])
@admin_required
def api_payroll_structure_create():
    data = request.get_json(silent=True) or {}
    emp_id = data.get("employee_id")
    employee = employees_map().get(str(emp_id))
    if not employee:
        raise ApiError("Pick the employee this structure belongs to")
    if employee.get("status") == "Exited":
        raise ApiError(f"{employee.get('full_name')} has left - exited records keep the structure they were paid on")
    name = str(data.get("name") or "Standard").strip()
    clash = next((s for s in db_list("payroll_structures", {"employee_id": emp_id})
                  if str(s.get("name") or "Standard").strip().lower() == name.lower()), None)
    if clash:
        raise ApiError(f"{employee.get('full_name')} already has a structure called {name} - edit that one, "
                       "or give this revision a name like 'Revised FY26-27'")
    payload, totals = parse_structure_payload(data, employee)
    created = db_insert("payroll_structures", payload)
    return jsonify({"success": True, "structure": enrich_structure(created),
                    "message": f"Salary structure for {employee.get('full_name')} saved - "
                               f"{inr(totals['gross'])} gross a month, {inr(totals['derived_ctc'])} CTC"})


@app.route("/api/payroll/structures/<row_id>", methods=["PUT"])
@admin_required
def api_payroll_structure_update(row_id):
    existing = db_get("payroll_structures", row_id)
    if not existing:
        raise ApiError("Structure not found", 404)
    employee = employees_map().get(str(existing.get("employee_id"))) or {}
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or existing.get("name") or "Standard").strip()
    clash = next((s for s in db_list("payroll_structures", {"employee_id": existing.get("employee_id")})
                  if str(s.get("id")) != str(row_id)
                  and str(s.get("name") or "Standard").strip().lower() == name.lower()), None)
    if clash:
        raise ApiError(f"That name is already used for {employee.get('full_name') or 'this employee'}")
    payload, totals = parse_structure_payload(data, employee, existing)
    updated = db_update("payroll_structures", row_id, payload)
    return jsonify({"success": True, "structure": enrich_structure(updated),
                    "message": f"Structure updated - {inr(totals['gross'])} gross a month, net {inr(totals['net'])}"})


@app.route("/api/payroll/structures/<row_id>", methods=["DELETE"])
@admin_required
def api_payroll_structure_delete(row_id):
    existing = db_get("payroll_structures", row_id)
    if not existing:
        raise ApiError("Structure not found", 404)
    emp_id = existing.get("employee_id")
    pending = [p for p in db_list("payslips", {"employee_id": emp_id}) if str(p.get("status") or "Draft") == "Draft"]
    if pending:
        raise ApiError(f"This structure backs {len(pending)} draft payslip(s) for that employee - publish, revoke "
                       "or delete them first so nobody is paid from a structure that no longer exists")
    db_delete("payroll_structures", row_id)
    emp = employees_map().get(str(emp_id)) or {}
    return jsonify({"success": True,
                    "message": f"Structure removed for {emp.get('full_name') or 'that employee'} - "
                               "their past payslips keep the numbers they were paid on"})


def build_payslip_row(employee, structure, year, month, days, bonus=0.0, recovery=0.0, status="Draft",
                      generated_by=None, notes=None):
    """One payslip row from a structure + the days worked, so the run and the slip can never differ."""
    payout = compute_payout(structure, extra_earnings=bonus, extra_deductions=recovery,
                            paid_days=days["payable_days"] or 1, total_days=days["working_days"] or 26)
    status = status if status in PAYROLL_STATUSES else "Draft"
    return {"employee_id": employee.get("id"), "year": int(year), "month": int(month),
            "period": f"{int(year):04d}-{int(month):02d}",
            "gross_earnings": payout["gross"], "total_deductions": payout["deductions_total"],
            "net_pay": payout["net"], "bonus": round(money(bonus), 2), "deductions": round(money(recovery), 2),
            "lop_days": days["lop_days"], "payable_days": days["payable_days"],
            "working_days": days["working_days"], "status": status,
            "generated_at": str(today()), "generated_by": generated_by, "notes": (notes or "").strip()[:500] or None,
            "published_at": str(today()) if status in ("Published", "Paid") else None,
            "paid_on": str(today()) if status == "Paid" else None, "payslip_url": None}


@app.route("/api/payroll/run", methods=["POST"])
@admin_required
def api_payroll_run():
    """Generate (or re-generate) a month's payslips from structures + attendance.

    Idempotent on (employee, period): a draft is rebuilt in place, and a slip already Published or
    Paid is left alone unless `overwrite` is asked for, because re-running payroll after salaries went
    out is how people end up paid twice.
    """
    data = request.get_json(silent=True) or {}
    year, month = payroll_period(data)
    if date(year, month, 1) > date(today().year, today().month, 1):
        raise ApiError(f"{year}-{month:02d} has not started yet - payroll can only be run for a month in progress")
    ids = {str(i) for i in (data.get("employee_ids") or []) if str(i).strip()}
    status = "Published" if data.get("publish") else "Draft"
    overwrite = bool(data.get("overwrite"))
    actor = (session.get("user") or {}).get("email")
    period = f"{year:04d}-{month:02d}"
    created = updated = 0
    kept, skipped = [], []
    for emp in db_list("employees"):
        if emp.get("status") == "Exited" or (ids and str(emp.get("id")) not in ids):
            continue
        structure = current_structure(emp.get("id"), on=str(month_end(year, month)))
        if not structure:
            skipped.append({"employee": emp.get("full_name"), "reason": "no salary structure"})
            continue
        joining = parse_day(emp.get("date_of_joining"))
        if joining and joining > month_end(year, month):
            skipped.append({"employee": emp.get("full_name"), "reason": f"joins on {fmt_day(joining)}"})
            continue
        days = payroll_days(emp, year, month, through=min(today(), month_end(year, month))
                            if date(year, month, 1) <= date(today().year, today().month, 1) else None)
        if not days["working_days"]:
            skipped.append({"employee": emp.get("full_name"), "reason": "no working days in this period"})
            continue
        existing = payslip_for(emp.get("id"), year, month)
        if existing and str(existing.get("status") or "Draft") != "Draft" and not overwrite:
            kept.append({"employee": emp.get("full_name"), "status": existing.get("status")})
            continue
        bonus = money((existing or {}).get("bonus"))
        recovery = money((existing or {}).get("deductions"))
        row = build_payslip_row(emp, structure, year, month, days, bonus=bonus, recovery=recovery,
                                status=status, generated_by=actor, notes=(existing or {}).get("notes"))
        if existing:
            db_update("payslips", existing["id"], row)
            updated += 1
        else:
            db_insert("payslips", row)
            created += 1
    slips = [enrich_payslip(p) for p in db_list("payslips", {"period": period})]
    total_net = round(sum(money(s.get("net_pay")) for s in slips), 2)
    message = (f"Payroll for {datetime(year, month, 1).strftime('%B %Y')}: {created} generated, {updated} updated"
               + (f", {len(kept)} already released and left alone" if kept else ""))
    return jsonify({"success": True, "period": period, "year": year, "month": month, "status": status,
                    "created": created, "updated": updated, "kept": kept, "skipped": skipped,
                    "employees": len(slips), "net_payroll": total_net,
                    "gross_payroll": round(sum(money(s.get("gross_earnings")) for s in slips), 2),
                    "deductions": round(sum(money(s.get("total_deductions")) for s in slips), 2),
                    "message": message,
                    "next": "Review the drafts, then Publish them so employees can see their slips."
                            if status == "Draft" else "Slips are published - mark the period paid once salaries go out."})


@app.route("/api/payroll/publish", methods=["POST"])
@admin_required
def api_payroll_publish():
    """Release a period's drafts to the employees it belongs to."""
    data = request.get_json(silent=True) or {}
    year, month = payroll_period(data)
    period = f"{year:04d}-{month:02d}"
    ids = {str(i) for i in (data.get("employee_ids") or []) if str(i).strip()}
    changed = 0
    for slip in db_list("payslips", {"period": period}):
        if str(slip.get("status") or "Draft") != "Draft" or (ids and str(slip.get("employee_id")) not in ids):
            continue
        db_update("payslips", slip["id"], {"status": "Published", "published_at": str(today())})
        changed += 1
    if not changed:
        raise ApiError(f"No draft payslips to publish for {datetime(year, month, 1).strftime('%B %Y')} - "
                       "run payroll for that month first")
    return jsonify({"success": True, "period": period, "published": changed,
                    "message": f"{changed} payslip(s) for {datetime(year, month, 1).strftime('%B %Y')} published"})


@app.route("/api/payroll/mark-paid", methods=["POST"])
@admin_required
def api_payroll_mark_paid():
    """Close the loop: the bank transfer happened, so the period is Paid."""
    data = request.get_json(silent=True) or {}
    year, month = payroll_period(data)
    period = f"{year:04d}-{month:02d}"
    paid_on = str(parse_day(data.get("paid_on")) or today())
    ids = {str(i) for i in (data.get("employee_ids") or []) if str(i).strip()}
    changed = 0
    for slip in db_list("payslips", {"period": period}):
        emp_id = str(slip.get("employee_id"))
        if ids and emp_id not in ids:
            continue
        if str(slip.get("status") or "") == "Paid":
            continue
        if str(slip.get("status") or "Draft") != "Published":
            raise ApiError(f"{(employee_display(emp_id) or {}).get('full_name') or 'One employee'} is still on "
                           f"{slip.get('status') or 'Draft'} - publish the period before marking it paid")
        db_update("payslips", slip["id"], {"status": "Paid", "paid_on": paid_on})
        changed += 1
    if not changed:
        raise ApiError(f"Nothing published to mark paid for {datetime(year, month, 1).strftime('%B %Y')}")
    return jsonify({"success": True, "period": period, "paid": changed, "paid_on": paid_on,
                    "message": f"{changed} payslip(s) marked paid on {fmt_day(paid_on)}"})


@app.route("/api/payslips/<row_id>", methods=["PUT"])
@admin_required
def api_payslip_update(row_id):
    """A single slip: bonus, recovery, a note, or its status - HR's correction before release."""
    slip = db_get("payslips", row_id)
    if not slip:
        raise ApiError("Payslip not found", 404)
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or slip.get("status") or "Draft")
    if status not in PAYROLL_STATUSES:
        raise ApiError("Payslip status must be Draft, Published or Paid")
    # The status and the paid-on date may move on a released slip (that is what marking it paid is);
    # its money may not. Otherwise "publish, then quietly edit" would leave the employee holding a
    # PDF that no longer matches the register.
    released_as = str(slip.get("status") or "Draft")
    if released_as != "Draft" and any(k in data for k in ("bonus", "deductions", "working_days", "payable_days")):
        raise ApiError(f"This slip was already {released_as.lower()} - revoke it back to Draft before changing its "
                       "amounts, so a payslip nobody re-reads does not move underneath the bank file")
    employee = employees_map().get(str(slip.get("employee_id"))) or {}
    structure = current_structure(slip.get("employee_id"))
    year, month = int(money(slip.get("year"))), int(money(slip.get("month")))
    bonus = money(data["bonus"]) if "bonus" in data else money(slip.get("bonus"))
    recovery = money(data["deductions"]) if "deductions" in data else money(slip.get("deductions"))
    if bonus < 0 or recovery < 0:
        raise ApiError("Bonus and recovery cannot be negative")
    days = {"working_days": money(slip.get("working_days")), "payable_days": money(slip.get("payable_days")),
            "lop_days": money(slip.get("lop_days")), "lost_days": [], "note": ""}
    if not days["working_days"]:
        days = payroll_days(employee or {"id": slip.get("employee_id")}, year, month)
    row = build_payslip_row(employee or {"id": slip.get("employee_id")}, structure, year, month, days,
                            bonus=bonus, recovery=recovery, status=status,
                            generated_by=slip.get("generated_by") or (session.get("user") or {}).get("email"),
                            notes=data.get("notes") if "notes" in data else slip.get("notes"))
    updated = db_update("payslips", row_id, row)
    return jsonify({"success": True, "payslip": enrich_payslip(updated),
                    "message": f"{(employee_display(slip.get('employee_id')) or {}).get('full_name') or 'Payslip'} "
                               f"for {enrich_payslip(updated).get('period_label')}: net {inr(updated.get('net_pay'))}"})


@app.route("/api/payslips/<row_id>/revoke", methods=["POST"])
@admin_required
def api_payslip_revoke(row_id):
    """Pull a released slip back to Draft - with a reason, because someone may have been paid on it."""
    slip = db_get("payslips", row_id)
    if not slip:
        raise ApiError("Payslip not found", 404)
    if str(slip.get("status") or "Draft") == "Draft":
        raise ApiError("That payslip is still a draft - edit it, or delete it from the register")
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason") or "").strip()
    if len(reason) < 8:
        raise ApiError("Say why in a few words - this slip is already in someone's hands")
    updated = db_update("payslips", row_id, {"status": "Draft", "published_at": None, "paid_on": None,
                                             "notes": (str(slip.get("notes") or "") + f"\n[revoked] {reason}").strip()[:500]})
    return jsonify({"success": True, "payslip": enrich_payslip(updated),
                    "message": "Back to draft - the employee can no longer open it"})


@app.route("/api/payslips/<row_id>", methods=["DELETE"])
@admin_required
def api_payslip_delete(row_id):
    slip = db_get("payslips", row_id)
    if not slip:
        raise ApiError("Payslip not found", 404)
    if str(slip.get("status") or "Draft") != "Draft":
        raise ApiError("Only drafts can be deleted - revoke it first, and say why")
    db_delete("payslips", row_id)
    return jsonify({"success": True, "message": "Draft payslip deleted"})


def payroll_register(year, month):
    """The month's line-by-line payroll, for the HR screen and the bank file."""
    period = f"{int(year):04d}-{int(month):02d}"
    rows = []
    for slip in db_list("payslips", {"period": period}):
        emp = employee_display(slip.get("employee_id")) or {}
        employee = employees_map().get(str(slip.get("employee_id"))) or {}
        row = enrich_payslip(slip)
        row.update({"department": emp.get("department"), "designation": emp.get("designation"),
                    "bank_name": employee.get("bank_name") or "—", "bank_account_no": employee.get("bank_account_no") or "—",
                    "ifsc_code": employee.get("ifsc_code") or "—", "pan_no": employee.get("pan_no") or "—",
                    "uan_no": employee.get("uan_no") or "—", "structure": bool(current_structure(slip.get("employee_id")))})
        rows.append(row)
    rows.sort(key=lambda r: str((r.get("employee") or {}).get("full_name") or "").lower())
    totals = {"gross": round(sum(money(r.get("gross_earnings")) for r in rows), 2),
              "deductions": round(sum(money(r.get("total_deductions")) for r in rows), 2),
              "net": round(sum(money(r.get("net_pay")) for r in rows), 2),
              "bonus": round(sum(money(r.get("bonus")) for r in rows), 2),
              "lop_days": round(sum(money(r.get("lop_days")) for r in rows), 2),
              "employees": len(rows), "draft": len([r for r in rows if r.get("is_draft")]),
              "published": len([r for r in rows if str(r.get("status")) == "Published"]),
              "paid": len([r for r in rows if str(r.get("status")) == "Paid"])}
    missing = [employee_display(e.get("id")) for e in db_list("employees")
               if e.get("status") != "Exited" and not current_structure(e.get("id"), on=str(month_end(year, month)))]
    return rows, totals, missing


@app.route("/api/payroll/register")
@admin_required
def api_payroll_register():
    year, month = payroll_period(args=request.args)
    rows, totals, missing = payroll_register(year, month)
    return jsonify({"period": f"{year:04d}-{month:02d}",
                    "label": datetime(year, month, 1).strftime("%B %Y"), "rows": rows, "totals": totals,
                    "structures_missing": [m for m in missing if m]})


@app.route("/api/payroll/register/export")
@admin_required
def api_payroll_register_export():
    """Bank-throw CSV: one row per person, the columns a salary file actually has."""
    year, month = payroll_period(args=request.args)
    rows, _totals, _missing = payroll_register(year, month)
    out = [{"employee_code": (r.get("employee") or {}).get("employee_code"),
            "employee": (r.get("employee") or {}).get("full_name"), "department": r.get("department"),
            "designation": r.get("designation"), "month": r.get("period"), "working_days": r.get("working_days"),
            "payable_days": r.get("payable_days"), "lop_days": r.get("lop_days"),
            "bonus": r.get("bonus"), "gross": r.get("gross_earnings"), "deductions": r.get("total_deductions"),
            "net_pay": r.get("net_pay"), "status": r.get("status"), "paid_on": r.get("paid_on"),
            "bank_name": r.get("bank_name"), "account_no": r.get("bank_account_no"), "ifsc": r.get("ifsc_code"),
            "pan": r.get("pan_no"), "uan": r.get("uan_no")} for r in rows]
    columns = ["employee_code", "employee", "department", "designation", "month", "working_days", "payable_days",
               "lop_days", "bonus", "gross", "deductions", "net_pay", "status", "paid_on", "bank_name",
               "account_no", "ifsc", "pan", "uan"]
    return csv_response(f"payroll_register_{year:04d}_{month:02d}", columns, out)


@app.route("/api/payroll/summary")
def api_payroll_summary():
    slips = db_list("payslips")
    scope = scoped_employee_id()
    admin = is_admin()
    if scope:
        slips = [s for s in slips if str(s.get("employee_id")) == str(scope)]
    if request.args.get("period"):     # the payroll screens carry ?period=; keep both shapes in step
        arg_year, arg_month = payroll_period(args=request.args)
    else:
        arg_year, arg_month = month_year_from_args()
    if not arg_month and not arg_year and slips:
        year, month = max((int(money(s.get("year")) or 0), int(money(s.get("month")) or 0)) for s in slips)
    else:
        year = arg_year or today().year
        month = arg_month or today().month
    period = f"{year:04d}-{month:02d}"
    rows = [s for s in slips if str(s.get("period") or "") == period or
             (int(money(s.get("year")) or 0) == year and int(money(s.get("month")) or 0) == month)]
    if not admin:
        rows = [s for s in rows if str(s.get("status") or "Draft") != "Draft"]
    structures = db_list("payroll_structures")
    by_employee = {str(s.get("employee_id")): s for s in structures}
    total_net = round(sum(money(s.get("net_pay")) for s in rows), 2)
    total_gross = round(sum(money(s.get("gross_earnings")) for s in rows), 2)
    total_ded = round(sum(money(s.get("total_deductions")) for s in rows), 2)
    per_dept = {}
    for s in rows:
        emp = employees_map().get(str(s.get("employee_id")), {})
        dept = emp.get("department") or dept_map().get(str(emp.get("department_id")), "Unassigned")
        per_dept[dept] = round(per_dept.get(dept, 0) + money(s.get("net_pay")), 2)
    trend = []
    for m in range(1, 13):
        subset = [s for s in slips if int(money(s.get("year")) or 0) == year and int(money(s.get("month")) or 0) == m
                  and (admin or str(s.get("status") or "Draft") != "Draft")]
        trend.append({"month": datetime(2000, m, 1).strftime("%b"),
                      "net": round(sum(money(s.get("net_pay")) for s in subset), 0), "count": len(subset)})
    monthly_cost = round(sum(money(s.get("ctc")) / 12 for s in structures), 2)
    monthly_gross_cost = round(sum(structure_lines(s)[2] for s in structures), 2)
    return jsonify({"period": datetime(year, month, 1).strftime("%B %Y"), "period_key": period,
                    "year": year, "month": month, "employees_paid": len(rows), "net_payroll": total_net,
                    "gross_payroll": total_gross, "deductions": total_ded,
                    "average_net": round(total_net / len(rows), 2) if rows else 0,
                    "monthly_ctc_cost": monthly_cost, "monthly_gross_cost": monthly_gross_cost,
                    "structures_count": len(structures),
                    "average_ctc": round(sum(money(s.get("ctc")) for s in structures) / len(structures), 2)
                    if structures else 0,
                    "pending_slips": len([s for s in rows if str(s.get("status") or "Draft") != "Paid"]),
                    "draft_slips": len([s for s in rows if str(s.get("status") or "Draft") == "Draft"]),
                    "published_slips": len([s for s in rows if str(s.get("status")) == "Published"]),
                    "paid_slips": len([s for s in rows if str(s.get("status")) == "Paid"]),
                    "lop_days": round(sum(money(s.get("lop_days")) for s in rows), 2),
                    "bonus_paid": round(sum(money(s.get("bonus")) for s in rows), 2),
                    "per_department": per_dept, "trend": trend, "scoped": bool(scope),
                    "my_structure": (enrich_structure(current_structure(scope)) if scope else None) or None,
                    "periods": [{"year": y, "month": m, "label": datetime(y, m, 1).strftime("%B %Y"),
                                 "net": round(sum(money(s.get("net_pay")) for s in slips
                                                  if int(money(s.get("year")) or 0) == y
                                                  and int(money(s.get("month")) or 0) == m), 0),
                                 "count": len([s for s in slips if int(money(s.get("year")) or 0) == y
                                               and int(money(s.get("month")) or 0) == m])}
                                for y, m in sorted({(int(money(s.get("year")) or 0), int(money(s.get("month")) or 0))
                                                    for s in slips}, reverse=True)[:12]],
                    "structures_missing": ([] if scope else
                                           [employee_display(e.get("id")) for e in db_list("employees")
                                            if e.get("status") != "Exited" and str(e.get("id")) not in by_employee][:10])})


# =================================================================== expenses
EXPENSE_CATEGORIES = ["Travel", "Food", "Accommodation", "Client Entertainment", "Medical", "Learning & Development",
                      "Equipment", "Home Office", "Other"]


@app.route("/api/reimbursements")
def api_reimbursements():
    emp_id = scoped_employee_id()
    filters = {} if not emp_id else {"employee_id": emp_id}
    if request.args.get("status") and request.args["status"] != "All":
        filters["status"] = request.args["status"]
    rows = []
    for r in db_list("reimbursements", filters, order="date", descending=True):
        rows.append({**r, "amount": money(r.get("amount")), "amount_label": inr(r.get("amount")),
                     "employee": employee_display(r.get("employee_id")), "date_label": fmt_day(r.get("date")),
                     "reviewer": employee_display(r.get("reviewer_id")),
                     "has_receipt": bool(r.get("receipt_url"))})
    return jsonify(rows)


@app.route("/api/reimbursements/summary")
def api_reimbursements_summary():
    rows = db_list("reimbursements")
    if not is_admin():
        rows = [r for r in rows if str(r.get("employee_id")) == str(acting_employee_id())]
    by_cat, months = {}, {}
    for r in rows:
        by_cat[r.get("category") or "Other"] = round(by_cat.get(r.get("category") or "Other", 0) + money(r.get("amount")), 2)
        key = str(r.get("date"))[:7]
        months[key] = round(months.get(key, 0) + money(r.get("amount")), 2)
    pending = [r for r in rows if r.get("status") == "Pending"]
    return jsonify({"total": round(sum(money(r.get("amount")) for r in rows), 2),
                    "pending": round(sum(money(r.get("amount")) for r in pending), 2),
                    "pending_count": len(pending), "approved": round(sum(money(r.get("amount")) for r in rows if r.get("status") == "Approved"), 2),
                    "paid": round(sum(money(r.get("amount")) for r in rows if r.get("status") == "Paid"), 2),
                    "rejected": round(sum(money(r.get("amount")) for r in rows if r.get("status") == "Rejected"), 2),
                    "by_category": by_cat, "by_month": months, "count": len(rows)})


@app.route("/api/reimbursements", methods=["POST"])
def api_reimbursement_create():
    data = request.get_json(silent=True) or {}
    employee_id = acting_employee_id()
    if not employee_id:
        raise ApiError("This login has no employee record to claim against")
    amount = money(data.get("amount"))
    if amount <= 0:
        raise ApiError("Enter the amount you are claiming")
    if amount > 100000:
        raise ApiError("Claims above ₹1,00,000 need a written approval from Finance before submission")
    if not (data.get("description") or "").strip():
        raise ApiError("Add a short description of the expense")
    if not data.get("date"):
        raise ApiError("Add the date of the expense")
    if not data.get("receipt_url") and not request.files.get("receipt") and not data.get("has_receipt"):
        raise ApiError("Attach the bill or receipt for this claim")
    row = {"employee_id": employee_id, "category": data.get("category") or "Other", "amount": amount,
           "date": str(data["date"])[:10], "description": data["description"].strip(),
           "status": "Pending", "receipt_url": data.get("receipt_url"), "created_at": str(today())}
    created = db_insert("reimbursements", row)
    return jsonify({"success": True, "reimbursement": created,
                    "message": f"Claim of {inr(amount)} submitted for approval"})


@app.route("/api/reimbursements/<row_id>/action", methods=["POST"])
@admin_required
def api_reimbursement_action(row_id):
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    claim = db_get("reimbursements", row_id)
    if not claim:
        raise ApiError("Claim not found", 404)
    if action not in ("approve", "reject", "pay"):
        raise ApiError("Use 'approve', 'reject' or 'pay'")
    if action == "reject" and not (data.get("remark") or "").strip():
        raise ApiError("Add a note explaining the rejection")
    status = {"approve": "Approved", "reject": "Rejected", "pay": "Paid"}[action]
    updated = db_update("reimbursements", row_id, {"status": status, "reviewer_id": acting_employee_id(),
                                                  "reviewer_remark": (data.get("remark") or "").strip() or claim.get("reviewer_remark")})
    return jsonify({"success": True, "reimbursement": updated,
                    "message": f"{inr(claim.get('amount'))} claim {status.lower()}"})


@app.route("/api/reimbursements/<row_id>", methods=["DELETE"])
def api_reimbursement_delete(row_id):
    claim = db_get("reimbursements", row_id)
    if not claim:
        raise ApiError("Claim not found", 404)
    if not is_admin() and str(claim.get("employee_id")) != str(acting_employee_id()):
        raise ApiError("You can only delete your own claims", 403)
    if claim.get("status") in ("Paid", "Approved") and not is_admin():
        raise ApiError("An approved claim can no longer be deleted - ask Finance to reverse it")
    db_delete("reimbursements", row_id)
    return jsonify({"success": True, "message": "Claim deleted"})


# =================================================================== hiring
CANDIDATE_STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"]


def enrich_job(job, candidates=None):
    row = dict(job)
    cands = candidates if candidates is not None else [c for c in db_list("candidates") if c.get("job_id")]
    mine = [c for c in cands if str(c.get("job_id")) == str(row.get("id"))]
    active = [c for c in mine if c.get("stage") != "Rejected"]
    person = employee_display(row.get("hiring_manager_id")) if row.get("hiring_manager_id") else None
    hr_map = {f"hiring_manager_{k}": v for k, v in person.items()} if person else {}
    row["hiring_manager"] = (person or {}).get("full_name") or "Unassigned"
    row["department"] = row.get("department") or dept_map().get(str(row.get("department_id")), "Unassigned")
    row["pipeline"] = {s: len([c for c in mine if c.get("stage") == s]) for s in CANDIDATE_STAGES}
    row["pipeline"]["Rejected"] = len([c for c in mine if c.get("stage") == "Rejected"])
    row["applicants"] = len(mine)
    row["in_progress"] = len(active)
    row["offers"] = row["pipeline"]["Offer"] + row["pipeline"]["Hired"]
    row["hired"] = row["pipeline"]["Hired"]
    openings = int(row.get("openings") or 0)
    row["fill_pct"] = min(100, round(row["hired"] / openings * 100)) if openings else 0
    row["days_open"] = max(0, (today() - (parse_day(row.get("posted_at")) or today())).days)
    row["status_label"] = {"Open": "Actively hiring", "On Hold": "On hold", "Closed": "Closed"}.get(row.get("status"), row.get("status"))
    row["posted_label"] = fmt_day(row.get("posted_at"))
    row["closed_label"] = fmt_day(row.get("closed_at")) if row.get("closed_at") else None
    row.update(hr_map)
    return row


@app.route("/api/jobs")
@hr_area
def api_jobs():
    rows = db_list("jobs", order="posted_at", descending=True)
    cands = db_list("candidates")
    status = request.args.get("status")
    out = [enrich_job(j, cands) for j in rows]
    if status and status != "All":
        out = [j for j in out if j.get("status") == status]
    return jsonify(out)


JOB_FIELDS = {"title", "department_id", "location", "employment_type", "experience", "salary_range", "openings",
              "description", "status", "hiring_manager_id", "closed_at", "closure_reason", "posted_at"}


@app.route("/api/jobs", methods=["POST"])
@admin_required
def api_job_create():
    data = request.get_json(silent=True) or {}
    if not (data.get("title") or "").strip():
        raise ApiError("The job needs a title")
    row = {k: v for k, v in data.items() if k in JOB_FIELDS}
    row.update({"title": data["title"].strip(), "status": "Open", "posted_at": data.get("posted_at") or str(today()),
                "openings": int(money(data.get("openings") or 1)),
                "hiring_manager_id": data.get("hiring_manager_id") or acting_employee_id()})
    created = db_insert("jobs", row)
    return jsonify({"success": True, "job": enrich_job(created), "message": f"{created['title']} is now live on the careers board"})


@app.route("/api/jobs/<row_id>", methods=["PUT", "DELETE"])
@admin_required
def api_job_update(row_id):
    job = db_get("jobs", row_id)
    if not job:
        raise ApiError("Job not found", 404)
    if request.method == "DELETE":
        linked = [c for c in db_list("candidates") if str(c.get("job_id")) == str(row_id)]
        if linked:
            raise ApiError(f"{len(linked)} candidate(s) are still attached to this requisition - close it instead of deleting")
        db_delete("jobs", row_id)
        return jsonify({"success": True, "message": "Job removed"})
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action == "close":
        reason = (data.get("closure_reason") or "").strip()
        if not reason:
            raise ApiError("A closing note is required - it is shown on the requisition history")
        in_flight = [c for c in db_list("candidates") if str(c.get("job_id")) == str(row_id) and c.get("stage") not in ("Hired", "Rejected")]
        updated = db_update("jobs", row_id, {"status": "Closed", "closed_at": str(today()), "closure_reason": reason})
        return jsonify({"success": True, "job": enrich_job(updated),
                        "message": f"Job closed. {len(in_flight)} open candidate(s) were left in the pipeline - move them or reject them."})
    if action == "reopen":
        updated = db_update("jobs", row_id, {"status": "Open", "closed_at": None, "closure_reason": None})
        return jsonify({"success": True, "job": enrich_job(updated), "message": "Requisition reopened"})
    payload = {k: v for k, v in data.items() if k in JOB_FIELDS}
    if not payload:
        raise ApiError("Nothing to update")
    if "openings" in payload:
        payload["openings"] = int(money(payload["openings"]) or 1)
    if payload.get("status") == "Closed" and not (payload.get("closure_reason") or job.get("closure_reason")):
        raise ApiError("Add a closure reason before marking a job Closed")
    updated = db_update("jobs", row_id, payload)
    return jsonify({"success": True, "job": enrich_job(updated), "message": f"{updated.get('title')} updated"})


def enrich_candidate(c):
    row = dict(c)
    job = db_get("jobs", row.get("job_id")) if row.get("job_id") else None
    row["job_title"] = (job or {}).get("title") or "Unassigned requisition"
    row["department"] = dept_map().get(str((job or {}).get("department_id")), "")
    row["owner"] = employee_display(row.get("owner_id"))
    row["stage_index"] = CANDIDATE_STAGES.index(row.get("stage")) if row.get("stage") in CANDIDATE_STAGES else -1
    row["is_rejected"] = row.get("stage") == "Rejected"
    row["is_hired"] = row.get("stage") == "Hired"
    row["converted"] = bool(row.get("converted_employee_id"))
    row["converted_employee"] = employee_display(row.get("converted_employee_id")) if row.get("converted_employee_id") else None
    row["experience_years"] = money(row.get("experience_years"))
    row["current_ctc_label"] = inr(row.get("current_ctc")) if row.get("current_ctc") else "-"
    row["expected_ctc_label"] = inr(row.get("expected_ctc")) if row.get("expected_ctc") else "-"
    row["rating"] = money(row.get("rating"))
    row["initials"] = initials(row.get("full_name"))
    row["applied_label"] = fmt_day(row.get("created_at") or row.get("applied_at"))
    row["age_in_stage_days"] = max(0, (today() - (parse_day(row.get("stage_changed_at") or row.get("created_at")) or today())).days)
    return row


@app.route("/api/candidates")
@hr_area
def api_candidates():
    filters = {}
    if request.args.get("job_id"):
        filters["job_id"] = request.args["job_id"]
    if request.args.get("stage") and request.args["stage"] != "All":
        filters["stage"] = request.args["stage"]
    rows = [enrich_candidate(c) for c in db_list("candidates", filters or None, order="created_at", descending=True)]
    q = (request.args.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows if q in " ".join(str(r.get(k) or "") for k in
               ("full_name", "email", "phone", "current_role", "job_title", "notes", "source")).lower()]
    return jsonify(rows)


CANDIDATE_FIELDS = {"job_id", "full_name", "email", "phone", "experience_years", "current_role", "current_ctc",
                    "expected_ctc", "stage", "rating", "source", "owner_id", "resume_url", "notes",
                    "converted_employee_id", "stage_changed_at"}


@app.route("/api/candidates", methods=["POST"])
@admin_required
def api_candidate_create():
    data = request.get_json(silent=True) or {}
    if not (data.get("full_name") or "").strip():
        raise ApiError("Candidate name is required")
    if not (data.get("email") or "").strip():
        raise ApiError("Candidate email is required")
    row = {k: v for k, v in data.items() if k in CANDIDATE_FIELDS}
    row.update({"full_name": data["full_name"].strip(), "email": data["email"].strip().lower(),
                "stage": data.get("stage") if data.get("stage") in CANDIDATE_STAGES + ["Rejected"] else "Applied",
                "owner_id": data.get("owner_id") or acting_employee_id(), "created_at": str(today()),
                "stage_changed_at": str(today())})
    created = db_insert("candidates", row)
    return jsonify({"success": True, "candidate": enrich_candidate(created), "message": f"{created['full_name']} added to the pipeline"})


@app.route("/api/candidates/<row_id>", methods=["PUT", "DELETE"])
@admin_required
def api_candidate_update(row_id):
    cand = db_get("candidates", row_id)
    if not cand:
        raise ApiError("Candidate not found", 404)
    if request.method == "DELETE":
        db_delete("candidates", row_id)
        return jsonify({"success": True, "message": f"{cand.get('full_name')} removed from the pipeline"})
    data = request.get_json(silent=True) or {}
    payload = {k: v for k, v in data.items() if k in CANDIDATE_FIELDS}
    if data.get("stage") and data["stage"] != cand.get("stage"):
        if data["stage"] not in CANDIDATE_STAGES + ["Rejected"]:
            raise ApiError(f"'{data['stage']}' is not a pipeline stage")
        payload["stage"] = data["stage"]
        payload["stage_changed_at"] = str(today())
    if not payload:
        raise ApiError("Nothing to update")
    updated = db_update("candidates", row_id, payload)
    return jsonify({"success": True, "candidate": enrich_candidate(updated),
                    "message": f"{updated.get('full_name')} moved to {updated.get('stage')}" if "stage" in payload else "Candidate profile updated"})


HIRE_FIELDS = {"full_name", "email", "phone", "personal_email", "date_of_birth", "department_id", "designation_id",
               "manager_id", "employment_type", "work_location", "salary_ctc", "employee_code", "status",
               "date_of_joining", "gender", "blood_group", "address", "pan_no", "bank_name", "bank_account_no",
               "ifsc_code", "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation"}


@app.route("/api/candidates/<row_id>/hire", methods=["POST"])
@admin_required
def api_candidate_hire(row_id):
    """Convert a candidate into a directory employee (and link them both ways)."""
    cand = db_get("candidates", row_id)
    if not cand:
        raise ApiError("Candidate not found", 404)
    if cand.get("converted_employee_id"):
        raise ApiError(f"{cand.get('full_name')} is already in the employee directory")
    data = request.get_json(silent=True) or {}
    if not cand.get("job_id"):
        raise ApiError("Attach this candidate to a requisition before hiring them")
    job = db_get("jobs", cand["job_id"]) or {}
    row = {k: v for k, v in data.items() if k in HIRE_FIELDS}
    name = (row.get("full_name") or cand.get("full_name") or "").strip()
    email = (row.get("email") or cand.get("email") or "").strip().lower()
    if not name or not email:
        raise ApiError("A hired candidate needs both a full name and a work email")
    if any((e.get("email") or "").strip().lower() == email for e in db_list("employees")):
        raise ApiError(f"{email} already belongs to an employee record")
    department_id = row.get("department_id") or job.get("department_id")
    joining = parse_day(row.get("date_of_joining")) or today()
    row.update({"full_name": name, "email": email, "department_id": department_id,
                "designation_id": row.get("designation_id") or job.get("designation_id"),
                "manager_id": row.get("manager_id") or job.get("hiring_manager_id"),
                "employment_type": row.get("employment_type") or job.get("employment_type") or "Full-time",
                "work_location": row.get("work_location") or job.get("location") or "Bengaluru",
                "salary_ctc": money(row.get("salary_ctc") or cand.get("expected_ctc")),
                "date_of_joining": str(joining), "status": "Active",
                "employee_code": (row.get("employee_code") or "").strip().upper() or next_employee_code(),
                "personal_email": row.get("personal_email") or cand.get("email"),
                "phone": row.get("phone") or cand.get("phone"), "avatar": initials(name)})
    created = db_insert("employees", row)
    hire_ctc = money(created.get("salary_ctc"))
    hire_basic = round(hire_ctc * 0.4 / 12, 0)
    db_insert("payroll_structures", {"employee_id": created["id"], "ctc": hire_ctc, "name": "Standard",
                                     "basic": hire_basic,
                                     "hra": round(hire_ctc * 0.16 / 12, 0),
                                     "special_allowance": round(hire_ctc * 0.24 / 12, 0),
                                     "pf": 1800, "esi": 78, "professional_tax": 200,
                                     "employer_pf": round(hire_basic * 0.12, 2),
                                     "tds": round(hire_ctc * 0.10 / 12, 0),
                                     "effective_from": str(joining)})
    seed_leave_balances(created)
    db_update("candidates", row_id, {"stage": "Hired", "converted_employee_id": created["id"],
                                     "stage_changed_at": str(today())})
    if job:
        still_open = max(0, int(money(job.get("openings") or 1)) - 1)
        db_update("jobs", job["id"], {"openings": still_open} if still_open else {"openings": 0})
    return jsonify({"success": True, "employee": enrich_employee_row(created),
                    "candidate": enrich_candidate(db_get("candidates", row_id)),
                    "message": f"{name} joined as {created.get('employee_code')} - payroll structure and leave quotas created"})


@app.route("/api/hiring/pipeline")
@hr_area
def api_hiring_pipeline():
    cands = db_list("candidates")
    jobs = db_list("jobs")
    stages = [{"name": s, "count": len([c for c in cands if c.get("stage") == s]),
               "value": round(sum(money(c.get("expected_ctc")) for c in cands if c.get("stage") == s), 0)} for s in CANDIDATE_STAGES]
    rejected = len([c for c in cands if c.get("stage") == "Rejected"])
    hired = [c for c in cands if c.get("stage") == "Hired"]
    time_in_stage = {s: {"count": len([c for c in cands if c.get("stage") == s]),
                         "over_7_days": len([c for c in cands if c.get("stage") == s and
                                             max(0, (today() - (parse_day(c.get("stage_changed_at") or c.get("created_at")) or today())).days) > 7])}
                     for s in CANDIDATE_STAGES}
    by_source = {}
    for c in cands:
        src = c.get("source") or "Other"
        by_source[src] = by_source.get(src, 0) + 1
    return jsonify({"stages": stages, "rejected": rejected, "total": len(cands),
                    "open_roles": len([j for j in jobs if j.get("status") == "Open"]),
                    "open_positions": sum(int(j.get("openings") or 0) for j in jobs if j.get("status") == "Open"),
                    "hired": len(hired),
                    "hire_rate": round(len(hired) / len(cands) * 100, 1) if cands else 0,
                    "by_source": by_source, "time_in_stage": time_in_stage,
                    "avg_experience": round(sum(money(c.get("experience_years")) for c in cands) / len(cands), 1) if cands else 0})


# =================================================================== performance
def enrich_goal(gg):
    row = dict(gg)
    row["employee"] = employee_display(row.get("employee_id"))
    row["progress"] = int(money(row.get("progress") or 0))
    row["due_label"] = fmt_day(row.get("due_date"))
    due = parse_day(row.get("due_date"))
    row["days_left"] = (due - today()).days if due else None
    if row.get("status") in ("Achieved", "Closed"):
        row["health"] = "achieved"
    elif row["progress"] >= 75:
        row["health"] = "on_track"
    elif row["progress"] >= 40 and (row["days_left"] is None or row["days_left"] > 14):
        row["health"] = "on_track" if row["progress"] >= 50 else "at_risk"
    elif row["days_left"] is not None and row["days_left"] < 0:
        row["health"] = "overdue"
    else:
        row["health"] = "at_risk" if row["progress"] < 40 else "on_track"
    row["health_label"] = {"on_track": "On track", "at_risk": "At risk", "overdue": "Overdue", "achieved": "Achieved"}[row["health"]]
    return row


def enrich_review(r):
    row = dict(r)
    row["employee"] = employee_display(row.get("employee_id"))
    row["reviewer"] = employee_display(row.get("reviewer_id"))
    row["due_label"] = fmt_day(row.get("due_date"))
    row["cycle_label"] = f"{fmt_day(row.get('cycle_start'), '%d %b %Y')} - {fmt_day(row.get('cycle_end'), '%d %b %Y')}"
    row["rating_label"] = f"{money(row.get('final_rating') or row.get('manager_rating') or 0):.1f}"
    try:
        comps = row.get("competencies")
        comps = json.loads(comps) if isinstance(comps, str) and comps.strip().startswith("{") else (comps or {})
    except (TypeError, ValueError):
        comps = {}
    row["competencies"] = {k: money(v) for k, v in comps.items()} if isinstance(comps, dict) else {}
    row["competency_avg"] = round(sum(row["competencies"].values()) / len(row["competencies"]), 2) if row["competencies"] else 0
    due = parse_day(row.get("due_date"))
    row["days_left"] = (due - today()).days if due else None
    row["overdue"] = bool(due and due < today() and row.get("status") != "Completed")
    return row


def enrich_feedback(f):
    row = dict(f)
    row["to"] = employee_display(row.get("to_employee_id"))
    row["from"] = None if row.get("is_anonymous") else employee_display(row.get("from_employee_id"))
    row["from_label"] = "Anonymous" if row.get("is_anonymous") else ((row["from"] or {}).get("full_name") or "Colleague")
    row["tags"] = row.get("tags") or ""
    row["tag_list"] = [t.strip() for t in str(row["tags"]).split(",") if t.strip()]
    row["date_label"] = fmt_day(row.get("date") or row.get("created_at"))
    return row


def enrich_checkin(c):
    row = dict(c)
    row["employee"] = employee_display(row.get("employee_id"))
    row["manager"] = employee_display(row.get("manager_id"))
    row["date_label"] = fmt_day(row.get("date"))
    d = parse_day(row.get("date"))
    row["days_ago"] = (today() - d).days if d else None
    row["due_soon"] = bool(d and d >= today() and row.get("status") != "Done")
    return row


@app.route("/api/goals")
def api_goals():
    emp_id = scoped_employee_id()
    filters = {} if not emp_id else {"employee_id": emp_id}
    if request.args.get("status") and request.args["status"] != "All":
        filters["status"] = request.args["status"]
    rows = [enrich_goal(gg) for gg in db_list("goals", filters or None, order="due_date")]
    return jsonify(rows)


GOAL_FIELDS = {"employee_id", "title", "description", "category", "metric", "target", "progress", "status", "due_date"}


@app.route("/api/goals", methods=["POST"])
def api_goal_create():
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id") if is_admin() else acting_employee_id()
    employee_id = employee_id or acting_employee_id()
    if not (data.get("title") or "").strip():
        raise ApiError("Give the goal a title")
    if not employee_id:
        raise ApiError("This login has no employee record to attach a goal to")
    row = {k: v for k, v in data.items() if k in GOAL_FIELDS}
    row.update({"employee_id": employee_id, "title": data["title"].strip(),
                 "progress": int(max(0, min(100, money(data.get("progress"))))),
                 "status": data.get("status") or "On Track", "due_date": data.get("due_date") or str(today() + timedelta(days=90)),
                 "created_at": str(today())})
    created = db_insert("goals", row)
    return jsonify({"success": True, "goal": enrich_goal(created), "message": f"Goal added: {created['title']}"})


@app.route("/api/goals/<row_id>", methods=["PUT", "DELETE"])
def api_goal_update(row_id):
    goal = db_get("goals", row_id)
    if not goal:
        raise ApiError("Goal not found", 404)
    owner_ok = is_admin() or str(goal.get("employee_id")) == str(acting_employee_id())
    manager_id = (employees_map().get(str(goal.get("employee_id")), {}) or {}).get("manager_id")
    owner_ok = owner_ok or (manager_id and str(manager_id) == str(acting_employee_id()))
    if request.method == "DELETE":
        if not owner_ok:
            raise ApiError("Only the owner, their manager or HR can delete this goal", 403)
        db_delete("goals", row_id)
        return jsonify({"success": True, "message": "Goal removed"})
    if not owner_ok:
        raise ApiError("Only the owner, their manager or HR can update this goal", 403)
    data = request.get_json(silent=True) or {}
    payload = {k: v for k, v in data.items() if k in GOAL_FIELDS}
    if "progress" in payload:
        progress = int(max(0, min(100, money(payload["progress"]))))
        payload["progress"] = progress
        payload["status"] = data.get("status") or ("Achieved" if progress >= 100 else "On Track" if progress >= 40 else "At Risk")
    if not payload:
        raise ApiError("Nothing to update")
    updated = db_update("goals", row_id, payload)
    return jsonify({"success": True, "goal": enrich_goal(updated), "message": "Goal updated"})


@app.route("/api/reviews")
def api_reviews():
    emp_id = scoped_employee_id()
    filters = {} if not emp_id else {"employee_id": emp_id}
    rows = [enrich_review(r) for r in db_list("performance_reviews", filters or None, order="cycle_start", descending=True)]
    if request.args.get("status") and request.args["status"] != "All":
        rows = [r for r in rows if r.get("status") == request.args["status"]]
    return jsonify(rows)


REVIEW_FIELDS = {"employee_id", "reviewer_id", "period", "cycle_start", "cycle_end", "due_date", "self_rating",
                 "manager_rating", "final_rating", "potential", "strengths", "improvements", "comments", "status",
                 "competencies"}


@app.route("/api/reviews", methods=["POST"])
@admin_required
def api_review_create():
    data = request.get_json(silent=True) or {}
    if not data.get("employee_id"):
        raise ApiError("Choose the employee being reviewed")
    row = {k: v for k, v in data.items() if k in REVIEW_FIELDS}
    start = parse_day(data.get("cycle_start")) or today().replace(month=1, day=1)
    row.update({"cycle_start": str(start), "cycle_end": str(data.get("cycle_end") or (start.replace(year=start.year + 1) - timedelta(days=1))),
                "due_date": str(data.get("due_date") or today()), "status": data.get("status") or "Self Review Pending",
                "reviewer_id": data.get("reviewer_id") or acting_employee_id(), "period": data.get("period") or f"FY{start.year % 100 + 1}",
                "competencies": comp_map(data.get("competencies")), "created_at": str(today())})
    created = db_insert("performance_reviews", row)
    return jsonify({"success": True, "review": enrich_review(created),
                    "message": f"{row['period']} review opened for {employee_display(created['employee_id'])['full_name']}"})


@app.route("/api/reviews/<row_id>", methods=["PUT"])
def api_review_update(row_id):
    review = db_get("performance_reviews", row_id)
    if not review:
        raise ApiError("Review not found", 404)
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    me = str(acting_employee_id() or "")
    is_self = str(review.get("employee_id")) == me
    is_manager = str(review.get("reviewer_id")) == me
    if action == "self_review":
        if not (is_self or is_admin()):
            raise ApiError("Only the employee being reviewed can fill the self assessment", 403)
        rating = money(data.get("self_rating"))
        if not 1 <= rating <= 5:
            raise ApiError("Self rating must be between 1 and 5")
        if not (data.get("comments") or "").strip():
            raise ApiError("Write your self-review comments before submitting")
        payload = {"self_rating": rating, "comments": data["comments"].strip(),
                   "strengths": (data.get("strengths") or review.get("strengths") or "").strip(),
                   "improvements": (data.get("improvements") or review.get("improvements") or "").strip(),
                   "status": "Manager Review Pending"}
    elif action == "manager_review":
        if not (is_manager or is_admin()):
            raise ApiError("Only the assigned reviewer can score this review", 403)
        rating = money(data.get("manager_rating"))
        if not 1 <= rating <= 5:
            raise ApiError("Manager rating must be between 1 and 5")
        if not (data.get("comments") or "").strip():
            raise ApiError("Add reviewer comments - the employee sees them")
        comps = data.get("competencies")
        payload = {"manager_rating": rating, "comments": data["comments"].strip(),
                   "strengths": (data.get("strengths") or "").strip() or review.get("strengths"),
                   "improvements": (data.get("improvements") or "").strip() or review.get("improvements"),
                   "potential": data.get("potential") or review.get("potential"),
                   "status": data.get("status") or ("Completed" if data.get("finalize") else "Manager Review Pending")}
        if comps:
            payload["competencies"] = comp_map(comps)
        if money(data.get("final_rating")):
            payload["final_rating"] = money(data["final_rating"])
    else:
        if not is_admin():
            raise ApiError("Only HR can edit a review record", 403)
        payload = {k: v for k, v in data.items() if k in REVIEW_FIELDS}
        if "competencies" in payload:
            payload["competencies"] = comp_map(payload["competencies"])
    if not payload:
        raise ApiError("Nothing to update")
    if payload.get("status") == "Completed" and not money(review.get("final_rating") or payload.get("final_rating")):
        payload["final_rating"] = money(review.get("manager_rating") or payload.get("manager_rating") or 0)
    updated = db_update("performance_reviews", row_id, payload)
    return jsonify({"success": True, "review": enrich_review(updated),
                    "message": {"Self Review Pending": "Self assessment saved", "Manager Review Pending": "Self review submitted to your reviewer",
                                "Completed": "Review completed and rating published"}.get(updated.get("status"), "Review updated")})


@app.route("/api/feedback", methods=["GET", "POST"])
def api_feedback():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if not data.get("to_employee_id"):
            raise ApiError("Choose who you are recognising")
        message = (data.get("message") or "").strip()
        if len(message) < 10:
            raise ApiError("Write at least a line - a real note means more than 'good job'")
        row = {"from_employee_id": acting_employee_id(), "to_employee_id": data["to_employee_id"], "message": message,
               "tags": (data.get("tags") or "").strip(), "category": data.get("category") or "Appreciation",
               "is_anonymous": bool(data.get("is_anonymous")), "date": str(today()), "created_at": str(today())}
        created = db_insert("feedbacks", row)
        return jsonify({"success": True, "feedback": enrich_feedback(created),
                        "message": f"Feedback sent to {employee_display(created['to_employee_id'])['full_name']}"})
    rows = db_list("feedbacks", order="date", descending=True)
    if not is_admin():
        me = str(acting_employee_id() or "")
        rows = [r for r in rows if str(r.get("to_employee_id")) == me or (not r.get("is_anonymous") and str(r.get("from_employee_id")) == me)]
    return jsonify([enrich_feedback(r) for r in rows[:120]])


@app.route("/api/checkins", methods=["GET", "POST"])
def api_checkins():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        employee_id = data.get("employee_id")
        if not employee_id:
            raise ApiError("Choose the team member this check-in is with")
        if not data.get("date"):
            raise ApiError("Pick a date for the check-in")
        row = {"employee_id": employee_id, "manager_id": data.get("manager_id") or acting_employee_id(),
               "date": str(data["date"])[:10], "agenda": (data.get("agenda") or "").strip(),
               "notes": (data.get("notes") or "").strip(), "next_steps": (data.get("next_steps") or "").strip(),
               "status": data.get("status") or "Scheduled", "created_at": str(today())}
        created = db_insert("checkins", row)
        return jsonify({"success": True, "checkin": enrich_checkin(created),
                        "message": f"Check-in scheduled with {employee_display(employee_id)['full_name']}"})
    emp_id = scoped_employee_id()
    rows = db_list("checkins", order="date", descending=True)
    if emp_id:
        rows = [r for r in rows if str(r.get("employee_id")) == str(emp_id) or str(r.get("manager_id")) == str(emp_id)]
    return jsonify([enrich_checkin(r) for r in rows[:80]])


@app.route("/api/checkins/<row_id>", methods=["PUT"])
@admin_required
def api_checkin_update(row_id):
    data = request.get_json(silent=True) or {}
    payload = {k: v for k, v in data.items() if k in ("agenda", "notes", "next_steps", "status", "date")}
    if not payload:
        raise ApiError("Nothing to update")
    return jsonify({"success": True, "checkin": enrich_checkin(db_update("checkins", row_id, payload)), "message": "Check-in updated"})


@app.route("/api/performance/overview")
def api_performance_overview():
    goals = [enrich_goal(g_) for g_ in db_list("goals")]
    reviews = [enrich_review(r) for r in db_list("performance_reviews")]
    feedbacks = [enrich_feedback(f) for f in db_list("feedbacks")]
    checkins = [enrich_checkin(c) for c in db_list("checkins")]
    employees = [e for e in db_list("employees") if e.get("status") != "Exited"]
    buckets = {"4.5-5.0 Outstanding": 0, "4.0-4.4 Exceeds": 0, "3.0-3.9 Meets": 0, "2.0-2.9 Below": 0, "Under 2.0": 0}
    rated = []
    for r in reviews:
        rating = money(r.get("final_rating") or r.get("manager_rating"))
        if not rating:
            continue
        rated.append(rating)
        key = ("4.5-5.0 Outstanding" if rating >= 4.5 else "4.0-4.4 Exceeds" if rating >= 4.0 else
               "3.0-3.9 Meets" if rating >= 3.0 else "2.0-2.9 Below" if rating >= 2.0 else "Under 2.0")
        buckets[key] += 1
    by_employee_review = {}
    for r in sorted(reviews, key=lambda x: str(x.get("cycle_start"))):
        by_employee_review[str(r.get("employee_id"))] = r
    # for the matrix use each person's most recent *rated* review - an open review has no rating yet
    rated_review = {}
    for r in sorted(reviews, key=lambda x: str(x.get("cycle_start"))):
        if money(r.get("final_rating") or r.get("manager_rating")):
            rated_review[str(r.get("employee_id"))] = r
    nine_box = {}
    for e in employees:
        review = rated_review.get(str(e.get("id"))) or by_employee_review.get(str(e.get("id")))
        perf = money((review or {}).get("final_rating") or (review or {}).get("manager_rating"))
        if not perf:
            continue
        emp_goals = [g_ for g_ in goals if str(g_.get("employee_id")) == str(e.get("id"))]
        avg = round(sum(g_["progress"] for g_ in emp_goals) / len(emp_goals)) if emp_goals else 0
        potential = (review or {}).get("potential") or ("High" if avg >= 75 and perf >= 4 else "Medium" if avg >= 45 else "Low")
        perf_axis = "High" if perf >= 4.2 else "Medium" if perf >= 3 else "Low"
        key = f"{potential} potential / {perf_axis} performance"
        nine_box.setdefault(key, []).append({"id": e.get("id"), "name": e.get("full_name"), "rating": perf,
                                             "goal_progress": avg, "avatar": e.get("avatar") or initials(e.get("full_name"))})
    pending_self = len([r for r in reviews if r.get("status") == "Self Review Pending"])
    pending_mgr = len([r for r in reviews if r.get("status") == "Manager Review Pending"])
    dept_rows = {}
    for e in employees:
        dept = e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")
        rec = dept_rows.setdefault(dept, {"department": dept, "people": 0, "avg_rating": 0.0, "avg_goal": 0.0, "reviews": 0})
        rec["people"] += 1
    for eid, review in by_employee_review.items():
        e = employees_map().get(eid, {})
        dept = e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")
        if dept in dept_rows:
            rec = dept_rows[dept]
            rec["reviews"] += 1
            rec["avg_rating"] += money(review.get("final_rating") or review.get("manager_rating"))
    for g_ in goals:
        e = employees_map().get(str(g_.get("employee_id")), {})
        dept = e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")
        if dept in dept_rows:
            dept_rows[dept]["avg_goal"] += g_["progress"]
    for rec in dept_rows.values():
        rec["avg_rating"] = round(rec["avg_rating"] / rec["reviews"], 2) if rec["reviews"] else 0
        rec["avg_goal"] = round(rec["avg_goal"] / len([g_ for g_ in goals]), 1)
    goal_status_counts = {}
    for g_ in goals:
        goal_status_counts[g_.get("status") or "Not Started"] = goal_status_counts.get(g_.get("status") or "Not Started", 0) + 1
    return jsonify({"goals_total": len(goals), "goals_open": len([g_ for g_ in goals if g_.get("status") not in ("Achieved", "Closed")]),
                    "avg_goal_progress": round(sum(g_["progress"] for g_ in goals) / len(goals), 1) if goals else 0,
                    "goals_by_status": goal_status_counts,
                    "at_risk": [g_ for g_ in goals if g_.get("health") in ("at_risk", "overdue")][:12],
                    "reviews_total": len(reviews), "reviews_open": pending_self + pending_mgr,
                    "pending_self_review": pending_self, "pending_manager_review": pending_mgr,
                    "completed_reviews": len([r for r in reviews if r.get("status") == "Completed"]),
                    "avg_rating": round(sum(rated) / len(rated), 2) if rated else 0,
                    "rating_distribution": buckets, "nine_box": nine_box,
                    "nine_box_counts": {k: len(v) for k, v in nine_box.items()},
                    "feedback_count": len(feedbacks), "feedback_recent": feedbacks[:8],
                    "checkins_total": len(checkins), "checkins_upcoming": [c for c in checkins if c.get("due_soon")][:6],
                    "checkins_overdue": len([c for c in checkins if (c.get("days_ago") or 0) > 45 and c.get("status") != "Done"]),
                    "departments": sorted(dept_rows.values(), key=lambda x: -x["people"])})


# =================================================================== reports
def _period(args):
    frm, to = parse_day(args.get("from")), parse_day(args.get("to"))
    if not to:
        to = today()
    if not frm:
        frm = to - timedelta(days=29)
    return frm, to


def _between(row, frm, to, field="date"):
    d = parse_day(row.get(field))
    return bool(d) and frm <= d <= to


def _dept_of(emp_id):
    e = employees_map().get(str(emp_id), {})
    return e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")


def _in_dept(emp_id, department):
    return not department or _dept_of(emp_id) == department


@app.route("/api/reports")
@hr_area
def api_reports_list():
    return jsonify([
        {"id": "headcount", "name": "Headcount & Attrition", "module": "Employee", "icon": "👥",
         "description": "Joiners, exits, net movement and department mix for the period.",
         "suits": "Monthly HR review, board pack"},
        {"id": "attendance", "name": "Attendance & Punctuality", "module": "Attendance", "icon": "🕘",
         "description": "Days marked, present rate, late arrivals and absenteeism per employee.",
         "suits": "Payroll inputs, manager review"},
        {"id": "leave", "name": "Leave Utilisation", "module": "Leave", "icon": "🌴",
         "description": "Days taken by leave type, balances and approval turnaround.",
         "suits": "Capacity planning, policy review"},
        {"id": "payroll", "name": "Payroll Cost", "module": "Payroll", "icon": "💰",
         "description": "Gross, deductions and net cost by month and department.",
         "suits": "Finance reconciliation"},
        {"id": "expenses", "name": "Expense Claims", "module": "Expenses", "icon": "🧾",
         "description": "Claim value by category and status, with ageing of pending claims.",
         "suits": "Audit, budget tracking"},
        {"id": "hiring", "name": "Hiring Funnel", "module": "Hiring", "icon": "🎯",
         "description": "Candidates by stage, source mix and requisition fill progress.",
         "suits": "Talent review with hiring managers"},
        {"id": "timesheet", "name": "Timesheet & Utilisation", "module": "Timesheet", "icon": "⏱",
         "description": "Billable vs internal hours per person and per project.",
         "suits": "Client billing, delivery review"},
        {"id": "performance", "name": "Performance Summary", "module": "Performance", "icon": "📈",
         "description": "Goal progress and rating distribution by department.", "suits": "Calibration sessions"},
        {"id": "documents", "name": "Document Compliance", "module": "Documents", "icon": "📁",
         "description": "Mandatory document status per employee and items expiring soon.",
         "suits": "Statutory audit, onboarding close-out"},
    ])


@app.route("/api/reports/<name>")
@hr_area
def api_report(name):
    frm, to = _period(request.args)
    department = request.args.get("department") or None
    builders = {"headcount": _report_headcount, "attendance": _report_attendance, "leave": _report_leave,
                "payroll": _report_payroll, "expenses": _report_expenses, "hiring": _report_hiring,
                "timesheet": _report_timesheet, "performance": _report_performance, "documents": _report_documents}
    builder = builders.get(name)
    if not builder:
        raise ApiError(f"No such report '{name}'. Available: {', '.join(sorted(builders))}")
    payload = builder(frm, to, department)
    payload["meta"] = {"report": name, "from": str(frm), "to": str(to), "department": department or "All departments",
                       "generated_at": now_local().strftime("%d %b %Y, %H:%M"), "generated_by": session["user"]["name"],
                       "rows": len(payload.get("table", {}).get("rows", []))}
    if request.args.get("format") == "csv":
        table = payload.get("table") or {}
        return csv_response(f"report_{name}", table.get("columns", ["info"]), table.get("rows", []))
    return jsonify(payload)


def _chart(kind, labels, values, series_name="Value", colors=None):
    return {"kind": kind, "labels": labels, "values": values, "series_name": series_name, "colors": colors}


def _report_headcount(frm, to, department):
    employees = db_list("employees")
    joiners = [e for e in employees if _between(e, frm, to, "date_of_joining")]
    exited = [e for e in employees if e.get("exit_date") and _between(e, frm, to, "exit_date")]
    active_now = [e for e in employees if e.get("status") != "Exited" and not e.get("exit_date")]
    start_of_period = [e for e in employees if (parse_day(e.get("date_of_joining")) or date.max) <= frm and
                       (parse_day(e.get("exit_date")) or date.max) >= frm]
    depts = {}
    for e in active_now:
        dept = e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")
        if department and dept != department:
            continue
        rec = depts.setdefault(dept, {"department": dept, "count": 0, "joiners": 0, "exits": 0, "avg_tenure_months": 0.0})
        rec["count"] += 1
        months = (today() - (parse_day(e.get("date_of_joining")) or today())).days / 30.44
        rec["avg_tenure_months"] += months
    for e in joiners:
        dept = e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")
        if dept in depts:
            depts[dept]["joiners"] += 1
    for e in exited:
        dept = e.get("department") or dept_map().get(str(e.get("department_id")), "Unassigned")
        if dept in depts:
            depts[dept]["exits"] += 1
    for rec in depts.values():
        rec["avg_tenure_months"] = round(rec["avg_tenure_months"] / rec["count"], 1) if rec["count"] else 0
    rows = list(depts.values())
    months = {}
    cursor = date(frm.year, frm.month, 1)
    while cursor <= to:
        months[cursor.strftime("%b %y")] = {"joiners": 0, "exits": 0}
        cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)
    for e in joiners:
        key = (parse_day(e.get("date_of_joining")) or frm).strftime("%b %y")
        if key in months:
            months[key]["joiners"] += 1
    for e in exited:
        key = (parse_day(e.get("exit_date")) or frm).strftime("%b %y")
        if key in months:
            months[key]["exits"] += 1
    exits = len(exited)
    opening = len(start_of_period)
    attrition = round(exits / opening * 100, 1) if opening else 0.0
    return {"kpis": [{"label": "Headcount now", "value": len(active_now), "hint": "active employees today"},
                     {"label": "Joiners", "value": len(joiners), "hint": f"{frm.strftime('%d %b')} - {to.strftime('%d %b')}"},
                     {"label": "Exits", "value": exits, "hint": f"{attrition:.1f}% attrition"},
                     {"label": "Net movement", "value": len(joiners) - exits,
                      "hint": "positive means the org grew"}],
            "chart": _chart("bar", list(months), [m["joiners"] for m in months.values()], "Joiners"),
            "secondary": {"exits": [m["exits"] for m in months.values()], "labels": list(months)},
            "table": {"columns": ["department", "count", "joiners", "exits", "avg_tenure_months"],
                      "labels": {"department": "Department", "count": "Headcount", "joiners": "Joiners",
                                 "exits": "Exits", "avg_tenure_months": "Avg tenure (months)"},
                      "rows": sorted(rows, key=lambda r: -r["count"])} if rows else {"columns": [], "rows": []},
            "note": "Attrition = exits in the period ÷ headcount at the start of the period."}


def _report_attendance(frm, to, department):
    rows = [a for a in db_list("attendance") if _between(a, frm, to) and _in_dept(a.get("employee_id"), department)]
    counts = {"Present": 0, "Absent": 0, "Half Day": 0, "Work From Home": 0, "On Leave": 0}
    late, hours, per_person, per_day = 0, 0.0, {}, {}
    for a in rows:
        status = a.get("status") or "Other"
        counts[status] = counts.get(status, 0) + 1
        late += 1 if a.get("is_late") else 0
        hours += money(a.get("work_hours"))
        rec = per_person.setdefault(str(a.get("employee_id")), {"employee": (employee_display(a.get("employee_id")) or {}).get("full_name", "-"),
                                                                "department": _dept_of(a.get("employee_id")), "present": 0, "absent": 0,
                                                                "wfh": 0, "late": 0, "hours": 0.0, "days": 0})
        rec["days"] += 1
        if status == "Present":
            rec["present"] += 1
        elif status == "Absent":
            rec["absent"] += 1
        elif status == "Work From Home":
            rec["wfh"] += 1
        if a.get("is_late"):
            rec["late"] += 1
        rec["hours"] = round(rec["hours"] + money(a.get("work_hours")), 1)
        day = str(a.get("date"))[:10]
        bucket = per_day.setdefault(day, {"present": 0, "absent": 0})
        if status in ("Present", "Work From Home", "Half Day"):
            bucket["present"] += 1
        elif status == "Absent":
            bucket["absent"] += 1
    working_days = max(1, sum(1 for n in range((to - frm).days + 1) if (frm + timedelta(days=n)).weekday() < 5))
    expected = counts["Present"] + counts["Absent"] + counts["Half Day"] + counts["Work From Home"]
    table = sorted(per_person.values(), key=lambda r: (-r["present"], r["employee"]))
    days = sorted(per_day)
    return {"kpis": [{"label": "Days recorded", "value": len(rows), "hint": f"{working_days} working days in period"},
                     {"label": "Present rate", "value": f"{round(counts['Present'] / expected * 100, 1) if expected else 0}%",
                      "hint": "of all marked days"},
                     {"label": "Absent days", "value": counts["Absent"], "hint": "marked absent"},
                     {"label": "Late arrivals", "value": late, "hint": "clock-in after 09:30"},
                     {"label": "Hours worked", "value": round(hours, 1), "hint": "sum of work_hours"}],
            "chart": _chart("line", [fmt_day(d, "%d %b") for d in days], [per_day[d]["present"] for d in days], "Present employees"),
            "table": {"columns": ["employee", "department", "days", "present", "wfh", "absent", "late", "hours"],
                      "labels": {"employee": "Employee", "department": "Department", "days": "Days", "present": "Present",
                                 "wfh": "WFH", "absent": "Absent", "late": "Late", "hours": "Hours"},
                      "rows": table[:60]}}


def _report_leave(frm, to, department):
    leaves = [l for l in db_list("leave_requests") if _between(l, frm, to, "start_date") and _in_dept(l.get("employee_id"), department)]
    lt_map = leave_type_map()
    by_type, by_person = {}, {}
    for l in leaves:
        name = (lt_map.get(str(l.get("leave_type_id"))) or {}).get("name") or "Other"
        rec = by_type.setdefault(name, {"type": name, "days": 0.0, "requests": 0, "approved": 0, "pending": 0, "rejected": 0})
        rec["days"] += money(l.get("days") or 1)
        rec["requests"] += 1
        status = (l.get("status") or "").lower()
        if status in rec:
            rec[status] += 1
        pr = by_person.setdefault(str(l.get("employee_id")), {"employee": (employee_display(l.get("employee_id")) or {}).get("full_name", "-"),
                                                              "department": _dept_of(l.get("employee_id")), "days": 0.0, "requests": 0})
        pr["days"] += money(l.get("days") or 1)
        pr["requests"] += 1
    turnaround = []
    for l in leaves:
        created, actioned = parse_day(l.get("created_at")), parse_day(l.get("actioned_at"))
        if created and actioned:
            turnaround.append((actioned - created).days)
    return {"kpis": [{"label": "Leave requests", "value": len(leaves), "hint": f"{frm.strftime('%d %b')} - {to.strftime('%d %b')}"},
                     {"label": "Days approved", "value": round(sum(money(l.get('days') or 1) for l in leaves if l.get("status") == "Approved"), 1),
                      "hint": "calendar days taken"},
                     {"label": "Awaiting approval", "value": len([l for l in leaves if l.get("status") == "Pending"]), "hint": "needs a decision"},
                     {"label": "Rejection rate", "value": f"{round(len([l for l in leaves if l.get('status') == 'Rejected']) / len(leaves) * 100, 1) if leaves else 0}%",
                      "hint": "of requests in period"},
                     {"label": "Avg approval time", "value": f"{round(sum(turnaround) / len(turnaround), 1) if turnaround else 0} d",
                      "hint": "from application to decision"}],
            "chart": _chart("doughnut", list(by_type), [round(v["days"], 1) for v in by_type.values()], "Days by type"),
            "table": {"columns": ["employee", "department", "requests", "days"],
                      "labels": {"employee": "Employee", "department": "Department", "requests": "Requests", "days": "Days"},
                      "rows": sorted(by_person.values(), key=lambda r: -r["days"])[:60]},
            "note": "Types: " + (", ".join(f"{k} {round(v['days'],1)}d" for k, v in by_type.items()) or "no leave taken in this period")}


def _report_payroll(frm, to, department):
    slips = db_list("payslips")
    def in_period(s):
        try:
            d = date(int(s.get("year")), int(s.get("month")), 1)
        except (TypeError, ValueError):
            return False
        return frm.replace(day=1) <= d <= to
    rows = [s for s in slips if in_period(s) and _in_dept(s.get("employee_id"), department)]
    by_dept, by_month = {}, {}
    for s in rows:
        dept = _dept_of(s.get("employee_id"))
        rec = by_dept.setdefault(dept, {"department": dept, "people": 0, "gross": 0.0, "deductions": 0.0, "net": 0.0})
        rec["people"] += 1
        rec["gross"] += money(s.get("gross_earnings"))
        rec["deductions"] += money(s.get("total_deductions"))
        rec["net"] += money(s.get("net_pay"))
        key = f"{s.get('year')}-{str(s.get('month')).zfill(2)}"
        by_month[key] = round(by_month.get(key, 0) + money(s.get("net_pay")), 0)
    table = sorted(by_dept.values(), key=lambda r: -r["net"])
    for r in table:
        for k in ("gross", "deductions", "net"):
            r[k] = inr(r[k])
    return {"kpis": [{"label": "Payslips", "value": len(rows), "hint": "in the selected period"},
                     {"label": "Gross", "value": inr(sum(money(s.get("gross_earnings")) for s in rows)), "hint": "earnings before deductions"},
                     {"label": "Deductions", "value": inr(sum(money(s.get("total_deductions")) for s in rows)), "hint": "PF, ESI, TDS, PT"},
                     {"label": "Net paid", "value": inr(sum(money(s.get("net_pay")) for s in rows)), "hint": "credited to banks"}],
            "chart": _chart("bar", list(by_month), list(by_month.values()), "Net payroll (₹)"),
            "table": {"columns": ["department", "people", "gross", "deductions", "net"],
                      "labels": {"department": "Department", "people": "Payslips", "gross": "Gross",
                                 "deductions": "Deductions", "net": "Net"}, "rows": table}}


def _report_expenses(frm, to, department):
    rows = [r for r in db_list("reimbursements") if _between(r, frm, to) and _in_dept(r.get("employee_id"), department)]
    by_cat, by_status, by_person = {}, {}, {}
    for r in rows:
        amt = money(r.get("amount"))
        by_cat[r.get("category") or "Other"] = round(by_cat.get(r.get("category") or "Other", 0) + amt, 2)
        by_status[r.get("status") or "Pending"] = round(by_status.get(r.get("status") or "Pending", 0) + amt, 2)
        pr = by_person.setdefault(str(r.get("employee_id")), {"employee": (employee_display(r.get("employee_id")) or {}).get("full_name", "-"),
                                                              "department": _dept_of(r.get("employee_id")), "claims": 0, "amount": 0.0, "pending": 0})
        pr["claims"] += 1
        pr["amount"] = round(pr["amount"] + amt, 2)
        if r.get("status") == "Pending":
            pr["pending"] += 1
    oldest_pending = sorted([r for r in rows if r.get("status") == "Pending"], key=lambda r: str(r.get("date")))[:1]
    ageing = (today() - (parse_day(oldest_pending[0].get("date")) or today())).days if oldest_pending else 0
    table = sorted(by_person.values(), key=lambda r: -r["amount"])
    for r in table:
        r["amount"] = inr(r["amount"])
    return {"kpis": [{"label": "Claims", "value": len(rows), "hint": f"{frm.strftime('%d %b')} - {to.strftime('%d %b')}"},
                     {"label": "Total value", "value": inr(sum(money(r.get("amount")) for r in rows)), "hint": "all statuses"},
                     {"label": "Pending", "value": len([r for r in rows if r.get("status") == "Pending"]),
                      "hint": f"{inr(sum(money(r.get('amount')) for r in rows if r.get('status') == 'Pending'))} waiting"},
                     {"label": "Oldest pending", "value": f"{ageing} d" if ageing else "0 d", "hint": "days since the bill date"}],
            "chart": _chart("doughnut", list(by_cat), list(by_cat.values()), "Amount by category"),
            "table": {"columns": ["employee", "department", "claims", "amount", "pending"],
                      "labels": {"employee": "Employee", "department": "Department", "claims": "Claims",
                                 "amount": "Amount", "pending": "Pending"}, "rows": table[:60]},
            "note": "By status: " + (", ".join(f"{k} {inr(v)}" for k, v in by_status.items()) or "no claims")}


def _report_hiring(frm, to, department):
    jobs = [j for j in db_list("jobs") if _between(j, frm, to, "posted_at")]
    all_jobs = db_list("jobs")
    cands = db_list("candidates")
    if department:
        dept_job_ids = {str(j.get("id")) for j in all_jobs if dept_map().get(str(j.get("department_id"))) == department}
        cands = [c for c in cands if str(c.get("job_id")) in dept_job_ids]
    stages = {s: len([c for c in cands if c.get("stage") == s]) for s in CANDIDATE_STAGES}
    hired = stages.get("Hired", 0)
    rejected = len([c for c in cands if c.get("stage") == "Rejected"])
    by_job = {}
    for j in jobs:
        mine = [c for c in cands if str(c.get("job_id")) == str(j.get("id"))]
        by_job[str(j.get("id"))] = {"role": j.get("title"), "department": dept_map().get(str(j.get("department_id")), "-"),
                                    "openings": int(money(j.get("openings") or 0)), "applicants": len(mine),
                                    "interviews": len([c for c in mine if c.get("stage") in ("Interview", "Offer", "Hired")]),
                                    "hired": len([c for c in mine if c.get("stage") == "Hired"]),
                                    "status": j.get("status")}
    by_source = {}
    for c in cands:
        by_source[c.get("source") or "Other"] = by_source.get(c.get("source") or "Other", 0) + 1
    return {"kpis": [{"label": "Requisitions", "value": len(jobs), "hint": "posted in period"},
                     {"label": "Applicants", "value": len(cands), "hint": f"{rejected} rejected"},
                     {"label": "Interviews", "value": stages.get("Interview", 0) + stages.get("Offer", 0), "hint": "in stage or offer"},
                     {"label": "Hires", "value": hired, "hint": f"{round(hired / len(cands) * 100, 1) if cands else 0}% of applicants"},
                     {"label": "Open positions", "value": sum(int(j.get("openings") or 0) for j in jobs if j.get("status") == "Open"),
                      "hint": "still to fill"}],
            "chart": _chart("bar", list(stages), list(stages.values()), "Candidates by stage"),
            "secondary": {"sources": by_source},
            "table": {"columns": ["role", "department", "openings", "applicants", "interviews", "hired", "status"],
                      "labels": {"role": "Role", "department": "Department", "openings": "Openings",
                                 "applicants": "Applicants", "interviews": "Interviews", "hired": "Hired", "status": "Status"},
                      "rows": sorted(by_job.values(), key=lambda r: -r["applicants"])}}


def _report_timesheet(frm, to, department):
    sheets = {str(t["id"]): t for t in db_list("timesheets") if _between(t, frm, to, "week_starting")}
    entries = [e for e in db_list("timesheet_entries") if str(e.get("timesheet_id")) in sheets and
               _in_dept(sheets[str(e.get("timesheet_id"))].get("employee_id"), department)]
    pmap = project_map()
    by_person, by_project = {}, {}
    for e in entries:
        sheet = sheets[str(e.get("timesheet_id"))]
        hours, billable = money(e.get("hours")), bool(e.get("billable"))
        rate = money((pmap.get(str(e.get("project_id"))) or {}).get("billing_rate"))
        pr = by_person.setdefault(str(sheet.get("employee_id")), {"employee": (employee_display(sheet.get("employee_id")) or {}).get("full_name", "-"),
                                                                  "department": _dept_of(sheet.get("employee_id")), "hours": 0.0, "billable": 0.0, "weeks": set()})
        pr["hours"] += hours
        pr["billable"] += hours if billable else 0
        pr["weeks"].add(str(sheet.get("week_starting")))
        pj = by_project.setdefault(str(e.get("project_id")), {"project": (pmap.get(str(e.get("project_id"))) or {}).get("name") or "Internal",
                                                              "hours": 0.0, "billable": 0.0, "value": 0.0, "people": set()})
        pj["hours"] += hours
        pj["billable"] += hours if billable else 0
        pj["value"] += hours * rate if billable else 0
        pj["people"].add(str(sheet.get("employee_id")))
    rows = []
    for r in by_person.values():
        r["hours"] = round(r["hours"], 1)
        r["billable"] = round(r["billable"], 1)
        r["utilisation"] = round(r["billable"] / r["hours"] * 100) if r["hours"] else 0
        r["weeks"] = len(r["weeks"])
        rows.append(r)
    prows = []
    for r in by_project.values():
        prows.append({"project": r["project"], "hours": round(r["hours"], 1), "billable": round(r["billable"], 1),
                      "people": len(r["people"]), "value": inr(r["value"])})
    total_hours = round(sum(r["hours"] for r in rows), 1)
    total_billable = round(sum(r["billable"] for r in rows), 1)
    return {"kpis": [{"label": "Hours logged", "value": total_hours, "hint": f"{len(sheets)} timesheets in period"},
                     {"label": "Billable", "value": total_billable, "hint": f"{round(total_billable / total_hours * 100) if total_hours else 0}% utilisation"},
                     {"label": "Billable value", "value": inr(sum(money(e.get('hours')) * money((pmap.get(str(e.get('project_id'))) or {}).get('billing_rate')) for e in entries if e.get('billable'))),
                      "hint": "hours × project rate"},
                     {"label": "People billing", "value": len(rows), "hint": "with logged time"}],
            "chart": _chart("bar", [p["project"] for p in prows], [p["hours"] for p in prows], "Hours by project"),
            "table": {"columns": ["employee", "department", "weeks", "hours", "billable", "utilisation"],
                      "labels": {"employee": "Employee", "department": "Department", "weeks": "Weeks", "hours": "Hours",
                                 "billable": "Billable", "utilisation": "Utilisation %"}, "rows": sorted(rows, key=lambda r: -r["hours"])[:60]},
            "secondary": {"projects": prows},
            "note": "Only weeks whose start date falls inside the period are counted."}


def _report_performance(frm, to, department):
    goals = [enrich_goal(g_) for g_ in db_list("goals") if _in_dept(g_.get("employee_id"), department)]
    reviews = [enrich_review(r) for r in db_list("performance_reviews") if _in_dept(r.get("employee_id"), department)]
    by_dept = {}
    for g_ in goals:
        rec = by_dept.setdefault(_dept_of(g_.get("employee_id")),
                                 {"department": _dept_of(g_.get("employee_id")), "goals": 0, "progress": 0.0, "ratings": 0.0, "reviews": 0})
        rec["goals"] += 1
        rec["progress"] += g_["progress"]
    for r in reviews:
        rec = by_dept.setdefault(_dept_of(r.get("employee_id")), {"department": _dept_of(r.get("employee_id")), "goals": 0, "progress": 0.0, "ratings": 0.0, "reviews": 0})
        rec["reviews"] += 1
        rec["ratings"] += money(r.get("final_rating") or r.get("manager_rating"))
    rows = []
    for rec in by_dept.values():
        rows.append({"department": rec["department"], "goals": rec["goals"],
                     "avg_goal_progress": f"{round(rec['progress'] / rec['goals']) if rec['goals'] else 0}%",
                     "reviews": rec["reviews"], "avg_rating": round(rec["ratings"] / rec["reviews"], 2) if rec["reviews"] else "-"})
    return {"kpis": [{"label": "Goals tracked", "value": len(goals), "hint": f"{len([g_ for g_ in goals if g_.get('status') not in ('Achieved','Closed')])} open"},
                     {"label": "Avg progress", "value": f"{round(sum(g_['progress'] for g_ in goals) / len(goals)) if goals else 0}%", "hint": "across all goals"},
                     {"label": "Reviews completed", "value": len([r for r in reviews if r.get("status") == "Completed"]),
                      "hint": f"of {len(reviews)} in the cycle"},
                     {"label": "At-risk goals", "value": len([g_ for g_ in goals if g_.get("health") in ("at_risk", "overdue")]),
                      "hint": "need a manager conversation"}],
            "chart": _chart("bar", [r["department"] for r in rows], [int(str(r["avg_goal_progress"]).rstrip("%")) for r in rows], "Avg goal progress %"),
            "table": {"columns": ["department", "goals", "avg_goal_progress", "reviews", "avg_rating"],
                      "labels": {"department": "Department", "goals": "Goals", "avg_goal_progress": "Avg progress",
                                 "reviews": "Reviews", "avg_rating": "Avg rating"}, "rows": sorted(rows, key=lambda r: -r["goals"])}}


def _report_documents(frm, to, department):
    rows = [d for d in db_list("documents") if _between(d, frm, to, "uploaded_at") and _in_dept(d.get("employee_id"), department)]
    by_type, by_status = {}, {}
    for d in rows:
        by_type[d.get("doc_type") or "Other"] = by_type.get(d.get("doc_type") or "Other", 0) + 1
        by_status[d.get("status") or "Pending"] = by_status.get(d.get("status") or "Pending", 0) + 1
    people = {}
    for d in rows:
        people.setdefault(str(d.get("employee_id")), []).append(d)
    checklist = []
    scope = [e for e in db_list("employees") if e.get("status") != "Exited" and _in_dept(e.get("id"), department)]
    for e in scope:
        have = people.get(str(e.get("id")), [])
        types = {d.get("doc_type") for d in have}
        missing = [t for t in REQUIRED_DOC_TYPES if t not in types]
        checklist.append({"employee": e.get("full_name"), "department": e.get("department") or dept_map().get(str(e.get("department_id")), "-"),
                          "uploaded": len(have), "verified": len([d for d in have if d.get("status") == "Verified"]),
                          "pending": len([d for d in have if d.get("status") == "Pending"]),
                          "missing": len(missing), "completion": f"{round((len(REQUIRED_DOC_TYPES) - len(missing)) / max(len(REQUIRED_DOC_TYPES), 1) * 100)}%"})
    expiring = [enrich_document(d) for d in db_list("documents") if d.get("expiry_state") in ("Expired", "Expiring soon")]
    return {"kpis": [{"label": "Documents filed", "value": len(rows), "hint": f"{frm.strftime('%d %b')} - {to.strftime('%d %b')}"},
                     {"label": "Awaiting verification", "value": by_status.get("Pending", 0), "hint": "uploaded by employees"},
                     {"label": "Compliant employees", "value": len([c for c in checklist if c["missing"] == 0]),
                      "hint": f"of {len(checklist)} in scope"},
                     {"label": "Expiring within 60d", "value": len(expiring), "hint": "including already expired"}],
            "chart": _chart("doughnut", list(by_type), list(by_type.values()), "Documents by type"),
            "table": {"columns": ["employee", "department", "uploaded", "verified", "pending", "missing", "completion"],
                      "labels": {"employee": "Employee", "department": "Department", "uploaded": "Uploaded",
                                 "verified": "Verified", "pending": "Pending", "missing": "Missing mandatory", "completion": "Compliance"},
                      "rows": sorted(checklist, key=lambda c: (int(c["completion"].rstrip("%")), c["employee"]))},
            "note": f"{len(expiring)} document(s) need renewal soon: " + (", ".join(f"{d['employee']['full_name']} - {d['doc_type']}" for d in expiring[:6]) or "none")}


@app.route("/api/reports/custom", methods=["POST"])
@admin_required
def api_report_custom():
    data = request.get_json(silent=True) or {}
    dataset = data.get("dataset")
    if dataset not in SUPA_COLUMNS:
        raise ApiError(f"Unknown dataset '{dataset}'. Pick one of: {', '.join(sorted(SUPA_COLUMNS))}")
    allowed = SUPA_COLUMNS[dataset] | {"id", "created_at"}
    requested = data.get("columns") or sorted(allowed)
    columns = [c for c in requested if c in allowed]
    if not columns:
        raise ApiError("Select at least one column")
    filters = {k: v for k, v in (data.get("filters") or {}).items() if k in allowed and str(v).strip() != ""}
    rows = db_list(dataset, filters or None)
    frm, to = parse_day(data.get("from")), parse_day(data.get("to"))
    date_col = next((c for c in ("date", "start_date", "uploaded_at", "created_at", "week_starting", "month") if c in allowed), None)
    if (frm or to) and date_col:
        def keep(r):
            d = parse_day(r.get(date_col))
            if not d:
                return True
            if frm and d < frm:
                return False
            if to and d > to:
                return False
            return True
        rows = [r for r in rows if keep(r)]
    limit = min(int(money(data.get("limit") or 500)), 2000)
    out = [{c: r.get(c) for c in columns} for r in rows[:limit]]
    payload = {"dataset": dataset, "columns": columns, "labels": {c: c.replace("_", " ").title() for c in columns},
               "rows": out, "total": len(rows), "truncated": len(rows) > limit,
               "filters": filters, "available_columns": sorted(allowed - {"id"})}
    if data.get("format") == "csv":
        return csv_response(f"custom_{dataset}", columns, out)
    return jsonify(payload)


# =================================================================== inbox
def build_pending_actions(lean=False):
    """Every approval that is waiting on the signed-in user (or on their own approver)."""
    me = str(acting_employee_id() or "")
    actions = []
    inbox_view = "Approve"
    for l in db_list("leave_requests", {"status": "Pending"}):
        if not is_admin() and str(l.get("approver_id") or l.get("manager_id") or "") not in ("", me):
            continue
        emp = employee_display(l.get("employee_id")) or {}
        lt = (leave_type_map().get(str(l.get("leave_type_id"))) or {}).get("name", "Leave")
        days = money(l.get("days") or 1)
        actions.append({"kind": "leave", "id": l.get("id"), "employee_id": l.get("employee_id"),
                        "icon": "🌴", "tone": "amber", "title": f"{emp.get('full_name', 'Employee')} · {days:g}d {lt}",
                        "subtitle": f"{fmt_day(l.get('start_label') or l.get('start_date'))} → {fmt_day(l.get('end_date'))} · {l.get('reason') or 'No reason given'}",
                        "meta": ["Applied", fmt_day(l.get("created_at"))], "module": "leave",
                        "approve_endpoint": f"/api/leave-requests/{l.get('id')}/action"})
    for r in db_list("attendance_regularizations", {"status": "Pending"}):
        emp = employee_display(r.get("employee_id")) or {}
        actions.append({"kind": "regularization", "id": r.get("id"), "employee_id": r.get("employee_id"),
                        "icon": "🕐", "tone": "blue", "title": f"{emp.get('full_name', 'Employee')} · {r.get('request_type') or 'Correction'}",
                        "subtitle": f"{fmt_day(r.get('date'))} · {r.get('reason') or 'No reason given'}",
                        "meta": ["Requested", fmt_day(r.get("created_at"))], "module": "attendance",
                        "approve_endpoint": f"/api/regularizations/{r.get('id')}/action"})
    for c in db_list("reimbursements", {"status": "Pending"}):
        emp = employee_display(c.get("employee_id")) or {}
        actions.append({"kind": "expense", "id": c.get("id"), "employee_id": c.get("employee_id"),
                        "icon": "🧾", "tone": "violet", "title": f"{emp.get('full_name', 'Employee')} · {inr(c.get('amount'))}",
                        "subtitle": f"{c.get('category') or 'Expense'} · {fmt_day(c.get('date'))} · {c.get('description') or ''}",
                        "meta": ["Receipt", "Attached" if c.get("receipt_url") else "Missing"], "module": "expenses",
                        "approve_endpoint": f"/api/reimbursements/{c.get('id')}/action"})
    for d in db_list("documents", {"status": "Pending"}):
        if d.get("visibility") == "Employee only":
            continue
        emp = employee_display(d.get("employee_id")) or {}
        actions.append({"kind": "document", "id": d.get("id"), "employee_id": d.get("employee_id"),
                        "icon": "📁", "tone": "slate", "title": f"{emp.get('full_name', 'Employee')} · {d.get('doc_type') or 'Document'}",
                        "subtitle": f"Uploaded {fmt_day(d.get('uploaded_at') or d.get('created_at'))} · {d.get('purpose') or 'For HR records'}",
                        "meta": ["File", _human_size(d.get("file_size") or 0) if d.get("file_url") else "Metadata only"],
                        "module": "documents", "approve_endpoint": f"/api/documents/{d.get('id')}"})
    for t in db_list("timesheets", {"status": "Submitted"}):
        emp = employee_display(t.get("employee_id")) or {}
        actions.append({"kind": "timesheet", "id": t.get("id"), "employee_id": t.get("employee_id"),
                        "icon": "⏱", "tone": "teal", "title": f"{emp.get('full_name', 'Employee')} · week of {fmt_day(t.get('week_starting'), '%d %b')}",
                        "subtitle": f"{money(t.get('total_hours')):g} h logged · {money(t.get('billable_hours')):g} h billable",
                        "meta": ["Submitted", fmt_day(t.get("submitted_at"))], "module": "timesheet",
                        "approve_endpoint": f"/api/timesheets/{t.get('id')}/action"})
    if not is_admin():
        # what the employee is waiting on from their own approver
        mine = []
        for l in db_list("leave_requests", {"employee_id": me or None}):
            if l.get("status") == "Pending":
                emp = employee_display(l.get("employee_id")) or {}
                lt = (leave_type_map().get(str(l.get("leave_type_id"))) or {}).get("name", "Leave")
                mine.append({"kind": "leave_status", "id": l.get("id"), "employee_id": me, "icon": "⏳", "tone": "amber",
                             "title": f"{lt} · {money(l.get('days') or 1):g}d", "subtitle": f"Awaiting {inbox_view} from your manager",
                             "meta": ["Applied", fmt_day(l.get("created_at"))], "module": "leave", "actions": []})
        for t in db_list("timesheets", {"status": "Submitted"}):
            if str(t.get("employee_id")) == me:
                mine.append({"kind": "timesheet_status", "id": t.get("id"), "employee_id": me, "icon": "⏳", "tone": "teal",
                             "title": f"Week of {fmt_day(t.get('week_starting'), '%d %b')} submitted",
                             "subtitle": "Awaiting approval from your manager", "meta": ["Submitted", fmt_day(t.get("submitted_at"))],
                             "module": "timesheet", "actions": []})
        if mine:
            return mine
    for r in db_list("document_requests", {"status": OPEN_DOC_REQUESTS}):
        if not is_admin() and str(r.get("employee_id")) != me:
            continue
        emp = employee_display(r.get("employee_id")) or {}
        actions.append({"kind": "document_request", "id": r.get("id"), "employee_id": r.get("employee_id"),
                        "icon": "📤", "tone": "rose",
                        "title": (f"HR needs {r.get('doc_type')} from {emp.get('full_name', 'you')}" if is_admin()
                                  else f"{r.get('doc_type')} requested by HR"),
                        "subtitle": r.get("reason") or "Needed for your employee file",
                        "meta": ["Due", fmt_day(r.get("due_date"))], "module": "documents",
                        "approve_endpoint": f"/api/document-requests/{r.get('id')}"})
    for r in db_list("performance_reviews", {"status": "Self Review Pending"}):
        if is_admin() or str(r.get("employee_id")) == me:
            emp = employee_display(r.get("employee_id")) or {}
            actions.append({"kind": "review_self", "id": r.get("id"), "employee_id": r.get("employee_id"),
                            "icon": "📝", "tone": "amber", "title": f"{r.get('period') or 'Review'} · self review due",
                            "subtitle": f"{emp.get('full_name', 'Employee')} · due {fmt_day(r.get('due_date'))}",
                            "meta": ["Status", r.get("status")], "module": "performance",
                            "approve_endpoint": f"/api/reviews/{r.get('id')}"})
    for r in db_list("performance_reviews", {"status": "Manager Review Pending"}):
        if is_admin() or str(r.get("reviewer_id")) == me:
            emp = employee_display(r.get("employee_id")) or {}
            actions.append({"kind": "review_manager", "id": r.get("id"), "employee_id": r.get("employee_id"),
                            "icon": "⭐", "tone": "violet", "title": f"{r.get('period') or 'Review'} · manager rating due",
                            "subtitle": f"for {emp.get('full_name', 'Employee')} · due {fmt_day(r.get('due_date'))}",
                            "meta": ["Self review", "Submitted"], "module": "performance",
                            "approve_endpoint": f"/api/reviews/{r.get('id')}"})
    return actions[:8] if lean else actions


@app.route("/api/pending-actions/<kind>/<row_id>", methods=["POST"])
@admin_required
def api_pending_action(kind, row_id):
    """One-click approve from the Home / Inbox lists."""
    data = request.get_json(silent=True) or {}
    handlers = {
        "leave": lambda: api_leave_action(row_id),
        "regularization": lambda: api_regularization_action(row_id),
        "expense": lambda: api_reimbursement_action(row_id),
        "timesheet": lambda: api_timesheet_action(row_id),
    }
    if kind == "document":
        db_update("documents", row_id, {"status": "Verified", "reviewer_id": acting_employee_id(), "reviewed_at": str(today()),
                                        "reviewer_remark": (data.get("remark") or "Verified from Inbox").strip()})
        return jsonify({"success": True, "message": "Document verified"})
    if kind == "document_request":
        req = db_update("document_requests", row_id, {"status": data.get("status") or "Fulfilled"})
        return jsonify({"success": True, "request": req, "message": "Request updated"})
    handler = handlers.get(kind)
    if not handler:
        raise ApiError(f"Cannot auto-approve a {kind} from here")
    data.setdefault("action", "approve")      # get_json() hands back the cached dict, so the handler sees this
    return handler()


# =================================================================== misc exports & demo
# Modules in /api/export that an employee may use, and then only for their own rows.
SELF_EXPORT_MODULES = {"attendance", "leave", "payroll"}


@app.route("/api/export/<module>")
def api_export(module):
    admin = is_admin()
    if not admin and module not in SELF_EXPORT_MODULES:
        raise ApiError(f"The {module} export is available to HR Admins", 403)
    scope_to = None if admin else acting_employee_id()

    def own(rows, key="employee_id"):
        return rows if not scope_to else [r for r in rows if str(r.get(key)) == str(scope_to)]

    emps = [enrich_employee_row(e) for e in db_list("employees")]

    if module == "employees":
        return api_employees_export()
    if module == "attendance":
        rows = own([enrich_attendance_row(a) for a in db_list("attendance")])
        return csv_response("attendance", ["employee_name", "employee_code", "date", "clock_in_label", "clock_out_label",
                                           "work_hours", "status", "location", "clock_in_location_label",
                                           "clock_out_location_label", "regularization_status"], rows)
    if module == "leave":
        rows = own([enrich_leave_row(l) for l in db_list("leave_requests")])
        return csv_response("leave_requests", ["employee_name", "leave_type_label", "start_date", "end_date", "days",
                                                "status", "reason", "admin_remark"], [{**r, "employee_name": (r.get("employee") or {}).get("full_name")} for r in rows])
    if module == "payroll":
        rows = own([enrich_payslip(p) for p in db_list("payslips")])
        return csv_response("payslips", ["period_label", "employee_name", "gross_earnings", "total_deductions", "net_pay", "status"],
                            [{**r, "employee_name": (r.get("employee") or {}).get("full_name")} for r in rows])
    if module == "hiring":
        rows = [enrich_candidate(c) for c in db_list("candidates")]
        return csv_response("candidates", ["full_name", "email", "phone", "job_title", "stage", "experience_years",
                                           "expected_ctc", "source", "rating", "notes"], rows)
    if module == "org":
        rows = [{**e, "manager_name": e.get("manager")} for e in emps]
        return csv_response("org_chart", ["employee_code", "full_name", "designation", "department", "manager_name",
                                           "email", "work_location", "status"], rows)
    raise ApiError(f"Nothing to export for '{module}'")


@app.route("/api/demo/reset", methods=["POST"])
@admin_required
def api_demo_reset():
    if supabase:
        raise ApiError("Demo data is not in use - this app is reading your Supabase project", 400)
    reset_mock()
    return jsonify({"success": True, "message": "Demo data reset to its seeded state"})


@app.route("/api/inbox")
def api_inbox():
    """Grouped approval queue for the Inbox tab."""
    actions = build_pending_actions()
    groups, order = {}, []
    for a in actions:
        key = a.get("module") or "other"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(a)
    labels = {"leave": "Leave requests", "attendance": "Attendance corrections", "expenses": "Expense claims",
              "documents": "Documents", "timesheet": "Timesheets", "performance": "Performance reviews",
              "other": "Other"}
    return jsonify({"total": len(actions), "groups": [{"module": m, "label": labels.get(m, m.title()), "count": len(items),
                                                        "items": items} for m, items in zip(order, groups.values())],
                    "items": actions})


@app.route("/api/attendance", methods=["POST"])
def api_attendance_post():
    """Back-compatible alias: HR posts are manual entries, employee posts are clock events."""
    if is_admin() and (request.get_json(silent=True) or {}).get("employee_id"):
        return api_attendance_entry()
    return api_attendance_clock()


# Chat has its own identity/scoped storage and is deliberately absent from HR reports.
from chat_backend import init_chat
init_chat(app, sys.modules[__name__])


# =================================================================== run it
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    mode = "Supabase" if supabase else "demo data (mock)"
    try:
        print("-" * 74)
        print("  Modish Enterprises")
        print(f"  Data source : {mode}")
        print(f"  Storage     : {('Supabase Storage/' + SUPABASE_BUCKET) if (supabase and SUPABASE_BUCKET) else 'local uploads/'}")
        print("  Login       : Use your configured HR Admin or employee account")
        print(f"  Open        : http://localhost:{port}")
        print("-" * 74)
    except UnicodeEncodeError:
        print("Modish Enterprises starting on port", port)
    app.run(host="0.0.0.0", port=port, debug=debug)
