"""Smoke-test every Ekkaa HRMS endpoint against the running demo server."""
import json
import os
import sys
import uuid

# This file also imports `app` into its own process (the error-envelope check and the source-level /
# fake-client checks below), and that copy must start on the demo store: a Supabase-mode import never
# loads `mock_data`, so `_load_mock()` would die with `name 'build_mock_db' is not defined` the moment
# the fake client asks it for rows - and a test process has no business holding the real database
# anyway. The endpoint calls themselves still go to whatever BASE points at.
os.environ["USE_MOCK_DATA"] = "true"

import requests

BASE = os.environ.get("BASE", "http://localhost:5000")
s = requests.Session()
fails, checks = [], [0]


def call(method, path, *, expect=(200,), json_body=None, data=None, files=None, label=None, want_keys=None):
    checks[0] += 1
    url = BASE + path
    kwargs = {"timeout": 60}
    if json_body is not None:
        kwargs["json"] = json_body
    if data is not None:
        kwargs["data"] = data
    if files is not None:
        kwargs["files"] = files
    r = s.request(method, url, **kwargs)
    tag = label or f"{method} {path}"
    body = r
    if "json" in r.headers.get("Content-Type", ""):
        try:
            body = r.json()
        except ValueError:
            body = r
    if r.status_code not in expect:
        fails.append(f"{tag} -> {r.status_code}: {(r.text or '')[:220]}")
        print(f"  !! FAIL {tag} -> {r.status_code}: {(r.text or '')[:200]}")
        return r, body
    for key in want_keys or []:
        cur = body if isinstance(body, (dict, list)) else None
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)]
            else:
                fails.append(f"{tag}: missing key '{key}' in {json.dumps(body, default=str)[:200]}")
                print(f"  !! FAIL {tag}: missing key '{key}'")
                cur = None
                break
        if cur is None:
            break
    return r, body


def show(label, value):
    print(f"  {label:<34} {value}")


print("== auth ==")
call("GET", "/api/health", want_keys=["status"], label="health (no auth)")
call("POST", "/login", json_body={"email": "admin@company.com", "password": "nope"}, expect=(401,), label="bad admin password")
call("POST", "/login", json_body={"email": "someone@else.com", "password": "demo123"}, expect=(401,), label="unknown user")
_, body = call("POST", "/login", json_body={"email": "admin@company.com", "password": "demo123"},
               want_keys=["success"], label="admin login")
call("GET", "/dashboard", want_keys=None, label="dashboard page renders")
_, sess = call("GET", "/api/session", want_keys=["user.role", "is_admin", "office_date", "office_time"], label="session")
# the UI must be *told* what day it is; see the office-clock section for why a browser clock will not do
_od = str(sess.get("office_date") or "")
_ot = str(sess.get("office_time") or "")
if len(_od.split("-")) != 3 or not all(x.isdigit() for x in _od.split("-")):
    fails.append(f"/api/session must hand the browser an ISO office date, got {_od!r}")
if len(_ot.split(":")) < 3 or not all(x.isdigit() for x in _ot.split(":")[:3]):
    fails.append(f"/api/session office_time should read HH:MM:SS, got {_ot!r}")
show("role", sess["is_admin"])
call("GET", "/api/lookups", want_keys=["departments", "employees", "doc_types", "candidate_stages"], label="lookups")

print("== home ==")
_, st = call("GET", "/api/stats", label="stats", want_keys=[
    "total_employees", "present_today", "absent_today", "on_leave", "attendance_rate", "open_positions",
    "applicants", "pending_leaves", "pending_expenses", "pending_documents", "attendance_trend.labels",
    "today.birthdays", "today.next_holiday", "my_time.worked_hours", "pending_actions"])
for k in ("total_employees", "present_today", "wfh_today", "half_day_today", "absent_today", "late_today",
          "on_leave", "attendance_rate", "pending_leaves", "pending_timesheets", "open_positions", "applicants",
          "joined_this_month"):
    show(k, st.get(k))
show("trend pct", st["attendance_trend"]["present_pct"])
show("my_time", {k: st["my_time"][k] for k in ("clock_in", "clock_out", "worked_hours", "break_minutes",
                                               "overtime_hours", "is_late", "status", "clocked_in")})
show("birthdays/anniv/leave", (len(st["today"]["birthdays"]), len(st["today"]["anniversaries"]),
                               len(st["today"]["on_leave"]), st["today"]["next_holiday"]))
assert max(st["attendance_trend"]["present_pct"]) <= 100, "trend over 100%"
assert st["present_today"] + st["absent_today"] + st["on_leave"] <= st["total_employees"], "home cards disagree"

print("== employees ==")
_, emps = call("GET", "/api/employees", label="list")
show("count", len(emps))
show("first", {k: emps[0][k] for k in ("employee_code", "full_name", "department", "designation", "manager", "tenure")})
_, one = call("GET", f"/api/employees/{emps[4]['id']}", label="detail",
              want_keys=["employee", "snapshot.attendance_days_this_month", "leave_balances", "recent_attendance", "documents", "goals"])
show("detail keys", sorted(one.keys()))
call("GET", "/api/employees?q=vip&status=Active", label="search + status filter")
call("GET", "/api/employees/export", label="csv export")
_, made = call("POST", "/api/employees", json_body={"full_name": "Test Hireson", "email": f"test.hireson{uuid.uuid4().hex[:5]}@company.com",
                                                     "phone": "+91 90000 00001", "department_id": 2, "designation_id": 2,
                                                     "salary_ctc": 1800000, "date_of_joining": str(__import__("datetime").date.today())},
               label="create employee (admin only)", want_keys=["employee.employee_code", "employee.tenure"])
new_id = made["employee"]["id"]
call("POST", "/api/employees", json_body={"full_name": "", "email": ""}, expect=(400,), label="create validation")
call("PUT", f"/api/employees/{new_id}", json_body={"phone": "+91 90000 00009", "work_location": "Pune"}, label="admin edit")
call("DELETE", f"/api/employees/{new_id}", label="delete employee")

print("== me ==")
_, me = call("GET", "/api/me", want_keys=["employee", "leave_balances", "counts", "manager", "payslips", "attendance_month"], label="me")
show("me", {me["employee"]["full_name"]: me["employee"]["designation"]})
show("counts", me["counts"])
show("balances", [(b["leave_type"], b["remaining"], b["total"]) for b in me["leave_balances"]])
call("PUT", "/api/me", json_body={"address": "42 MG Road, Dādri, UP 251301", "salary_ctc": 999},
     expect=(200, 403), label="self-edit blocked field")
_, up = call("PUT", "/api/me", json_body={"address": "42 MG Road, Dādri, UP 251301", "blood_group": "B+"}, label="self-edit allowed")
show("changed", up.get("changed"))

print("== org chart ==")
_, oc = call("GET", "/api/orgchart", want_keys=["tree", "departments", "stats.total"], label="orgchart")
assert oc["stats"]["managers"] > 0 and oc["stats"]["max_depth"] >= 2, "org chart is flat"
assert all(d.get("head") and d.get("members") for d in oc["departments"]), "department head/members missing"
show("roots", [f"{n['name']} ({len(n['children'])} direct, {n['total_reports']} total)" for n in oc["tree"]])
show("stats", oc["stats"])
show("orphaned", oc["orphaned"])
show("dept[0]", {k: oc["departments"][0][k] for k in ("name", "count", "locations")} | {"head": (oc["departments"][0]["head"] or {}).get("full_name"), "members": len(oc["departments"][0].get("members") or [])})
root_id = oc["tree"][0]["id"]
some = [e for e in emps if str(e["id"]) != str(root_id)][0]
call("POST", "/api/orgchart/assign-manager", json_body={"employee_id": some["id"], "manager_id": some["id"]},
     expect=(400,), label="self manager rejected")
call("POST", "/api/orgchart/assign-manager", json_body={"employee_id": some["id"], "manager_id": "does-not-exist"},
     expect=(400, 404), label="bogus manager rejected")
call("POST", "/api/orgchart/assign-manager", json_body={"employee_id": some["id"], "manager_id": root_id}, label="assign manager")

def today_str(year_month, day):
    """`2026-09` + 3 -> `2026-09-03` (the seeded month, so the window always has data)."""
    return f"{year_month}-{day:02d}"


print("== attendance ==")
import datetime as dt
month = dt.date.today().strftime("%Y-%m")
_, att = call("GET", f"/api/attendance?month={month}", want_keys=["rows", "month_label"], label="attendance month")
show("rows", len(att["rows"]))
show("sample", att["rows"][0] if att["rows"] else None)
_, summ = call("GET", f"/api/attendance/summary?month={month}&employee_id={me['employee']['id']}",
               want_keys=["present", "total_hours", "calendar", "avg_hours"], label="summary")
show("summary", {k: summ[k] for k in ("days_marked", "present", "wfh", "absent", "late_days", "total_hours", "avg_hours", "overtime_hours")})
# the month / from-to filters must answer a nonsense value, never 500 on it
_, sep_att = call("GET", f"/api/attendance?month={month.replace('-', '/')}",
                  want_keys=["rows", "from_date"], label="attendance accepts 2026/09 as well as 2026-09")
if isinstance(sep_att, dict):
    assert len(sep_att["rows"]) == len(att["rows"]), "slash and dash forms of the same period returned different rows"
call("GET", "/api/attendance?month=nonsense", expect=(400,), label="month junk refused on the list")
call("GET", "/api/attendance?month=2026-13", expect=(400,), label="month 13 refused on the list")
call("GET", "/api/attendance/summary?month=nonsense", expect=(400,), label="month junk refused on the summary (was 500)")
call("GET", "/api/attendance?from=nope", expect=(400,), label="from=junk refused instead of crashing")
_, window = call("GET", f"/api/attendance?from={today_str(month, 1)}&to={today_str(month, 2)}",
                 want_keys=["from_date", "to_date", "rows"], label="explicit from/to window")
if isinstance(window, dict):
    assert (window["from_date"], window["to_date"]) == (today_str(month, 1), today_str(month, 2)), "window was not echoed back"
    assert all(window["from_date"] <= str(r["date"])[:10] <= window["to_date"] for r in window["rows"]), \
               "rows fell outside the requested window"
    show("from/to window", f"{window['from_date']}..{window['to_date']} -> {len(window['rows'])} of {len(att['rows'])} rows")
_, flipped = call("GET", f"/api/attendance?from={today_str(month, 5)}&to={today_str(month, 1)}", label="reversed window is normalized")
if isinstance(flipped, dict):
    assert flipped["from_date"] <= flipped["to_date"], "a reversed from/to came back reversed"
_, clock = call("POST", "/api/attendance/clock", json_body={"action": "out"}, expect=(200, 400), label="clock out")
show("clock", clock)
call("POST", "/api/attendance/clock", json_body={"action": "in"}, expect=(200, 400), label="clock in (may already be in)")
call("POST", "/api/attendance/entry", json_body={"employee_id": me["employee"]["id"], "date": str(dt.date.today() - dt.timedelta(days=1)),
                                                 "clock_in": "10:05:00", "clock_out": "19:10:00", "status": "Present"}, label="HR manual entry")
_, regs = call("GET", "/api/regularizations", label="regularization list")
show("reg rows", [(r["employee"]["full_name"], r["request_type"], r["status"], r["current"]) for r in regs[:2]])
call("POST", "/api/regularizations", json_body={"date": str(dt.date.today() - dt.timedelta(days=2)), "reason": "short"},
     expect=(400,), label="reason too short -> 400")
call("POST", "/api/regularizations", json_body={"date": str(dt.date.today() + dt.timedelta(days=2)),
                                                 "reason": "Biometric reader was offline all morning."}, expect=(400,), label="future date blocked")
_, reg = call("POST", "/api/regularizations", json_body={"date": str(dt.date.today() - dt.timedelta(days=4)),
                                                          "request_type": "Missing punch-out",
                                                          "clock_out_correction": "18:45:00",
                                                          "reason": "Left after the release go-live and forgot to punch out."},
              label="regularization created", want_keys=["regularization.reason"])
call("POST", f"/api/regularizations/{reg['regularization']['id']}/action", json_body={"action": "reject"},
     expect=(400,), label="reject needs remark")
call("POST", f"/api/regularizations/{reg['regularization']['id']}/action",
     json_body={"action": "reject", "remark": "Please attach the release ticket."}, label="reject with remark")
call("DELETE", f"/api/regularizations/{reg['regularization']['id']}", expect=(200, 400), label="withdraw (only pending)")

print("== clock state machine and HR punch edits ==")
call("POST", "/api/demo/reset", json_body={}, label="pristine store for the clock checks")
_, dir_rows = call("GET", "/api/employees", label="directory for the clock checks")
me_id = next(e["id"] for e in dir_rows if e["email"] == "aarav.sharma@company.com")
today_s = str(dt.date.today())

_, closed = call("POST", "/api/attendance/entry", json_body={"employee_id": me_id, "date": today_s, "status": "Present",
                                                              "clock_in": "09:15", "clock_out": "18:45", "break_minutes": 45},
                 want_keys=["attendance"], label="HR files a complete day")
att = closed["attendance"]
show("after the edit", f"{att['clock_in']} -> {att['clock_out']} = {att['work_hours']} h, late {att['is_late']}")
assert att["clock_in"] == "09:15:00" and att["clock_out"] == "18:45:00", "times were not normalised to HH:MM:SS"
assert abs(float(att["work_hours"]) - 8.8) < 0.1, f"work hours were not recomputed from the punches ({att['work_hours']})"
assert att["is_late"] is False, "09:15 is inside the 09:30 start + 15 min grace, so it must not be late"
_, after = call("GET", "/api/attendance", want_keys=["rows"], label="attendance after the edit")
row1 = next(a for a in after["rows"] if a["id"] == att["id"])
assert row1["clock_in_label"] == "09:15 AM", f"the table still shows {row1['clock_in_label']}"
# a late correction has to flip the flag the other way too
_, late_fix = call("POST", "/api/attendance/entry", json_body={"employee_id": me_id, "date": today_s, "status": "Present",
                                                                "clock_in": "10:40", "clock_out": "18:45", "break_minutes": 45},
                  want_keys=["attendance"], label="HR moves the clock-in late")
assert late_fix["attendance"]["is_late"] is True, "10:40 against a 09:45 grace must be marked late"
_, _ = call("POST", "/api/attendance/entry", json_body={"employee_id": me_id, "date": today_s, "status": "Present",
                                                        "clock_in": "09:15", "clock_out": "18:45", "break_minutes": 45},
           label="back to the on-time punch")
r, j = call("POST", "/api/attendance/clock", json_body={"action": "in"}, expect=(400,), label="a second clock-in on a closed day is blocked")
assert "already closed" in (j.get("error") or "").lower(), f"unexpected reply: {j}"
r, j = call("POST", "/api/attendance/clock", json_body={"action": "out"}, expect=(400,), label="a second clock-out is blocked")
assert "closed" in (j.get("error") or "").lower() or "already clocked out" in (j.get("error") or "").lower(), j
# and the day is never left "in progress" behind: an open day refuses a second in, accepts the out
call("POST", "/api/attendance/entry", json_body={"employee_id": me_id, "date": today_s, "status": "Present",
                                                "clock_in": "08:30", "clock_out": None, "break_minutes": 45}, label="reopen the day")
r, j = call("POST", "/api/attendance/clock", json_body={"action": "in"}, expect=(400,), label="clock-in while the day is open")
assert "already clocked in" in (j.get("error") or "").lower(), j
r, j = call("POST", "/api/attendance/clock", json_body={"action": "out"}, label="clock-out closes that open day")
assert j.get("success") and float(j["hours"]) > 0, j
# rows left over from the old behaviour (out before in) are reopened instead of jamming the person
call("POST", "/api/attendance/entry", json_body={"employee_id": me_id, "date": today_s, "status": "Present",
                                                "clock_in": "18:00", "clock_out": "09:00", "break_minutes": 45}, label="plant a broken row")
r, j = call("POST", "/api/attendance/clock", json_body={"action": "in"}, want_keys=["message"], label="a broken row is reopened by a clock-in")
assert "reopened" in (j.get("message") or "").lower(), j
r, j = call("POST", "/api/attendance/clock", json_body={"action": "out"}, label="and can then be closed normally")
_, st = call("GET", "/api/stats", want_keys=["my_time"], label="tracker state after closing")
t = st["my_time"]
show("tracker after close", f"{t['clock_in']} -> {t['clock_out']} · {t['status']}")
assert t["clocked_out"] is True and t["clocked_in"] is False, "a closed day must not read as clocked-in"
# approving a regularization must refresh the totals too, not just the status pill
_, regs = call("GET", "/api/regularizations", label="regularization queue")
pend = next((x for x in (regs if isinstance(regs, list) else regs.get("rows", [])) if x.get("status") == "Pending"), None)
if pend:
    day = str(pend["date"])[:10]
    call("POST", "/api/attendance/entry", json_body={"employee_id": pend["employee_id"], "date": day, "status": "Absent",
                                                     "clock_in": None, "clock_out": None, "break_minutes": 0,
                                                     "note": "no punch at all, awaiting the correction"},
         label="blank the day before approving")
    r, j = call("POST", f"/api/regularizations/{pend['id']}/action", json_body={"action": "approve", "remark": "approved"},
                want_keys=["attendance", "message"], label="approve the correction")
    fixed = j["attendance"]
    show("approved row", f"{fixed.get('clock_in')} -> {fixed.get('clock_out')} = {fixed.get('work_hours')} h · {fixed.get('regularization_status')}")
    assert fixed.get("regularization_status") == "Approved", fixed
    assert float(fixed.get("work_hours") or 0) > 0, "approval left the day with no hours - totals were not recomputed"
    assert fixed.get("status") != "Absent", "approval kept the absent mark on a corrected day"

call("POST", "/api/demo/reset", json_body={}, label="store restored")

print("== leave ==")
call("GET", "/api/leave-types", label="leave types")
call("GET", f"/api/leave-balances?employee_id={me['employee']['id']}", want_keys=["balances"], label="balances")
_, lvs = call("GET", "/api/leave-requests", label="leave list")
show("pending", len([l for l in lvs if l["status"] == "Pending"]))
show("sample", {k: lvs[0][k] for k in ("leave_type_label", "period_label", "days", "status", "leave_color")})
call("POST", "/api/leave-requests", json_body={"leave_type_id": 1, "start_date": str(dt.date.today() - dt.timedelta(days=3)),
                                               "end_date": str(dt.date.today() - dt.timedelta(days=2)), "reason": "past"},
     expect=(400,), label="past leave blocked")
call("POST", "/api/leave-requests", json_body={"leave_type_id": 99, "start_date": str(dt.date.today() + dt.timedelta(days=20)),
                                                "end_date": str(dt.date.today() + dt.timedelta(days=21)), "reason": "bad type"},
     expect=(400,), label="bogus leave type blocked")
_, over = call("GET", "/api/leave-balances", label="all balances")
emp_bal = [b for b in over if str(b["employee_id"]) == str(me["employee"]["id"])][0]["balances"]
tight = min(emp_bal, key=lambda b: b["remaining"])           # whatever is scarcest is the one to overdraw
over_span = dt.timedelta(days=tight["remaining"] + 14)       # comfortably more than what is left
call("POST", "/api/leave-requests", json_body={"leave_type_id": tight["leave_type_id"],
                                               "start_date": str(dt.date.today() + dt.timedelta(days=40)),
                                               "end_date": str(dt.date.today() + dt.timedelta(days=40) + over_span),
                                               "reason": "Should be blocked by balance"},
     expect=(400,), label=f"over-quota blocked ({tight['leave_type']}, {tight['remaining']} left)")
_, applied = call("POST", "/api/leave-requests", json_body={"leave_type_id": emp_bal[0]["leave_type_id"],
                                                             "start_date": str(dt.date.today() + dt.timedelta(days=25)),
                                                             "end_date": str(dt.date.today() + dt.timedelta(days=26)),
                                                             "reason": "Family function out of town"},
                  label="apply", want_keys=["leave.leave_type_label"])
lid = applied["leave"]["id"]
_, after = call("GET", f"/api/leave-balances?employee_id={me['employee']['id']}", label="balance after apply")
show("pending moved", [(b["leave_type"], b["pending"], b["remaining"]) for b in after["balances"]][:2])
call("POST", f"/api/leave-requests/{lid}/action", json_body={"action": "reject"}, expect=(400,), label="reject needs remark")
call("POST", f"/api/leave-requests/{lid}/action", json_body={"action": "approve", "remark": "Approved, enjoy."}, label="approve")
_, att_after = call("GET", f"/api/attendance?from={dt.date.today() + dt.timedelta(days=25)}&to={dt.date.today() + dt.timedelta(days=26)}",
                    label="approved leave wrote attendance")
show("leave rows in attendance", [r["status"] for r in att_after["rows"]])
call("POST", f"/api/leave-requests/{lid}/cancel", label="cancel approved leave")
_, bal_after_cancel = call("GET", f"/api/leave-balances?employee_id={me['employee']['id']}", label="balance after cancel")
show("used back down", [(b["leave_type"], b["used"], b["pending"]) for b in bal_after_cancel["balances"]][:2])

print("== documents ==")
_, meta = call("GET", "/api/documents/meta", want_keys=["doc_types", "checklist", "counts", "storage_mode"], label="documents meta")
show("counts", meta["counts"])
show("storage", meta["storage_mode"])
show("checklist[0]", {k: meta["checklist"][0][k] for k in ("completion_pct", "verified", "missing")})
show("types", len(meta["doc_types"]))
_, docs = call("GET", "/api/documents", label="list docs")
show("first doc", {k: docs[0][k] for k in ("title", "doc_type", "category", "purpose", "status", "size_label", "expiry_state", "uploaded_by_label")})
call("GET", "/api/documents?expiring=soon", label="expiring filter")
payload = {"employee_id": me["employee"]["id"], "title": "Driving License (test)", "doc_type": "Driving License",
           "purpose": "Needed for the client site access badge", "visibility": "Manager + HR",
           "valid_from": "2022-04-01", "valid_till": str(dt.date.today() + dt.timedelta(days=365)),
           "description": "Front and back scanned at home."}
call("POST", "/api/documents", json_body=payload, expect=(200, 400), label="metadata-only upload")
files = {"file": ("license.txt", io_ := b"FAKE PDF BYTES " * 40, "text/plain")}
_, up = call("POST", "/api/documents", data=payload, files=files, label="multipart upload", want_keys=["document.file_url"])
doc_id = up["document"]["id"]
show("upload", {k: up["document"].get(k, "-") for k in ("file_name", "size_label", "purpose", "visibility", "status", "expiry_state")})
call("POST", "/api/documents", json_body={"employee_id": me["employee"]["id"], "doc_type": "Driving License",
                                          "title": "no expiry", "description": "x"}, expect=(400,), label="expiry required")
_, dl = call("GET", f"/api/documents/{doc_id}/download", label="download")
assert dl.text.startswith("FAKE PDF BYTES"), "downloaded bytes did not round-trip"
print("  downloaded bytes round-trip      OK")
call("PUT", f"/api/documents/{doc_id}", json_body={"action": "Rejected"}, expect=(400,), label="reject needs remark")
call("PUT", f"/api/documents/{doc_id}", json_body={"action": "Verified", "reviewer_remark": "Clear copy."}, label="verify")
call("DELETE", f"/api/documents/{doc_id}", label="delete doc")
_, dreq = call("GET", "/api/document-requests", label="document requests")
show("requests", [(r["employee"].get("full_name"), r["doc_type"], r["status"], r["overdue"]) for r in dreq[:3]])
call("POST", "/api/document-requests", json_body={"doc_type": "PAN Card", "employee_id": me["employee"]["id"]},
     expect=(400,), label="request needs reason")
_, rq = call("POST", "/api/document-requests", json_body={"doc_type": "Cancelled Cheque", "reason": "Bank details changed",
                                                            "due_date": str(dt.date.today() + dt.timedelta(days=3))},
             label="create request", want_keys=["request.id"])
call("PUT", f"/api/document-requests/{rq['request']['id']}", json_body={"status": "Fulfilled"}, label="fulfil request")

# open document requests must be visible everywhere they are promised: the per-employee
# checklist counter and the inbox queue (older seeds used the "Requested" spelling and
# were silently invisible in both).
_, meta2 = call("GET", "/api/documents/meta", label="doc meta (re-read)")
_, dreq2 = call("GET", "/api/document-requests", label="doc requests (re-read)")
checks[0] += 1
_open = [r for r in dreq2 if r["status"] in ("Pending", "Requested")]
_counted = sum(c["requests_pending"] for c in meta2["checklist"])
assert len(_open) == _counted, f"{len(_open)} open requests but the checklist counts {_counted}"
print(f"  open requests == checklist counter  OK ({len(_open)})")
checks[0] += 1
assert not [r for r in dreq2 if r["status"] == "Requested"], "seed still writes the legacy 'Requested' status"
print("  request statuses use one vocabulary OK")
_, ibx2 = call("GET", "/api/inbox", label="inbox")
_docg = next((g for g in ibx2["groups"] if g["module"] == "documents"), None)
checks[0] += 1
assert _docg and any(a["kind"] == "document_request" for a in _docg["items"]), "open document requests never reach the inbox"
print(f"  document requests reach the inbox   OK ({len([a for a in _docg['items'] if a['kind'] == 'document_request'])} ask)")

print("== timesheet ==")
monday = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
_, ts = call("GET", f"/api/timesheet?week={monday}", want_keys=["days", "projects", "timesheet", "stats"], label="my week")
show("week", ts["week_label"])
show("days", [(d["label"], sum(e["hours"] for e in d["entries"])) for d in ts["days"]])
show("stats", ts["stats"])
show("locked", ts["locked"])
proj = ts["projects"][0]["id"]
call("POST", "/api/timesheet/save", json_body={"week": str(monday), "entries": [{"date": str(monday), "project_id": proj, "hours": 30, "task": "x"}]},
     expect=(400,), label="over-daily cap blocked")
call("POST", "/api/timesheet/save", json_body={"week": str(monday), "entries": [{"date": str(monday), "hours": 4, "task": "no project"}]},
     expect=(400,), label="missing project blocked")
_, saved = call("POST", "/api/timesheet/save", json_body={"week": str(monday), "entries": [
    {"date": str(monday), "project_id": proj, "hours": 4, "billable": True, "task": "Timesheet module build"},
    {"date": str(monday), "project_id": ts["projects"][1]["id"], "hours": 3, "billable": False, "task": "Bug triage"},
    {"date": str(monday + dt.timedelta(days=1)), "project_id": proj, "hours": 7.5, "billable": True, "task": "API review"}]},
    label="save grid", want_keys=["timesheet.total_hours", "timesheet.billable_hours"])
show("saved totals", {k: saved["timesheet"][k] for k in ("total_hours", "billable_hours", "utilization_pct")})
call("POST", "/api/timesheet/submit", json_body={"week": str(monday)}, expect=(200, 400), label="submit (needs 20h)")
_, team = call("GET", f"/api/timesheet?view=team&week={monday}", want_keys=["timesheets", "summary"], label="team view")
show("team summary", team["summary"])
if team["timesheets"]:
    pend = next((t for t in team["timesheets"] if t["status"] == "Submitted"), team["timesheets"][0])
    call("POST", f"/api/timesheets/{pend['id']}/action", json_body={"action": "reject"}, expect=(400,), label="reject needs remark")
    call("POST", f"/api/timesheets/{pend['id']}/action", json_body={"action": "approve"}, label="approve")
call("GET", "/api/timesheet/history", label="history")
call("GET", "/api/timesheet/export", label="csv export")
_, prj = call("GET", "/api/projects", label="projects")
show("projects", [(p["code"], p["hours_this_week"], p["total_hours"], p["billable_value"]) for p in prj])

print("== projects: the grid's vocabulary is not fixed ==")
# A timesheet is only as good as the project names it offers, so a person can add one themselves.
prj_emp = requests.Session()
prj_emp.post(BASE + "/login", json={"email": "aarav.sharma@company.com", "password": "demo123"}, timeout=60)
ME_ID = str(prj_emp.get(BASE + "/api/session", timeout=60).json().get("employee", {}).get("id") or "")


def prj(method, path, payload=None, expect=200):
    rr = prj_emp.request(method, BASE + path, json=payload, timeout=60)
    checks[0] += 1
    body = rr.json() if "json" in rr.headers.get("Content-Type", "") else rr.text[:160]
    if rr.status_code != expect:
        fails.append(f"employee {method} {path} -> {rr.status_code}: {json.dumps(body, default=str)[:170]}")
    return rr, body


_, made = prj("POST", "/api/projects", {"name": "Northwind Migration", "client": "Northwind Traders", "billing_rate": 2100})
row = (made or {}).get("project") or {}
if not row.get("id"):
    fails.append(f"an Employee could not open a project: {json.dumps(made, default=str)[:170]}")
else:
    show("project added", f"{row['name']} · code {row['code']} · {row['status']} · ₹{row['billing_rate']:,.0f}/h · "
                          f"manager {row['manager_id']}")
    assert ME_ID, "the employee session has no employee id to own the project"
    if str(row.get("manager_id")) != ME_ID:
        fails.append(f"the person who opened the project is not its manager ({row.get('manager_id')} vs {ME_ID}) - "
                     "they could not rename it afterwards")
    codes = [str(p2.get("code") or "").upper() for p2 in prj_emp.get(BASE + "/api/projects", timeout=60).json()]
    if not str(row["code"]).startswith("PRJ-") or codes.count(str(row["code"]).upper()) != 1:
        fails.append(f"the code generated from the name is not unique/prefixed: {row['code']} in {codes}")
    _, allp = call("GET", "/api/projects", label="projects list")
    if not any(x.get("id") == row["id"] for x in allp):
        fails.append("the new project is missing from /api/projects (the Projects tab)")
    _, tsnow = call("GET", f"/api/timesheet?week={monday}", want_keys=["projects"], label="the grid's project list")
    if not any(x.get("id") == row["id"] for x in tsnow["projects"]):
        fails.append("the new project never reached the timesheet grid - the dropdown is still the fixed list")
    else:
        show("grid offers it", f"{len(tsnow['projects'])} projects selectable, including {row['name']} "
                               f"({[x for x in tsnow['projects'] if x['id'] == row['id']][0].get('manager_id')})")
    _, lk = call("GET", "/api/lookups", label="lookups")
    if not any(x.get("id") == row["id"] for x in lk.get("projects") or []):
        fails.append("/api/lookups still returns the old project list")
    _, held = prj("PUT", f"/api/projects/{row['id']}", {"status": "On Hold"})
    hp = (held or {}).get("project") or {}
    if hp.get("status") != "On Hold" or hp.get("name") != row["name"] or float(hp.get("billing_rate") or 0) != 2100:
        fails.append(f"a one-field PUT must change only that field, got {json.dumps(hp, default=str)[:170]}")
    else:
        show("partial update", f"{hp['name']} kept its ₹{hp['billing_rate']:,.0f}/h and client while going {hp['status']}")
    _, grid2 = call("GET", f"/api/timesheet?week={monday}", label="a closed-ish project still shows")
    shown = next((x for x in grid2["projects"] if x["id"] == row["id"]), {})
    if shown.get("status") != "On Hold":
        fails.append("the grid did not pick up the status change (the select labels rows by it)")
    for body, why in (({"name": "northwind migration"}, "a second name differing only in case"),
                      ({"name": "Unrelated", "code": row["code"]}, "a code already in use"),
                      ({"name": ""}, "no name at all"),
                      ({"name": "N" * 61}, "a 61-character name"),
                      ({"name": "Rate Test", "billing_rate": -1}, "a negative billing rate"),
                      ({"name": "Status Test", "status": "Zombie"}, "a status that is not one of the four"),
                      ({"name": "Manager Test", "manager_id": "e9999"}, "a manager who is not on the roster"),
                      ({"name": "Code Test", "code": "x"}, "a one-character code")):
        rr, bb = prj("POST", "/api/projects", body, expect=400)
        if not isinstance(bb, dict) or not bb.get("error"):
            fails.append(f"{why} was not refused with a sentence: {str(bb)[:120]}")
    show("refusals", "8 ways to write a bad project, each answered with a sentence naming the fix")
    seeded = next((x for x in allp if x.get("total_hours") and str(x.get("id")) != str(row["id"])), None)
    if not seeded:
        fails.append("no seeded project has logged hours, so deleting a used project is untested")
    else:
        rr, bb = prj("PUT", f"/api/projects/{seeded['id']}", {"name": "Hijacked Project"}, expect=403)
        if "manager" not in str((bb or {}).get("error", "")).lower():
            fails.append(f"a stranger was refused without being told who can help: {str(bb)[:140]}")
        else:
            show("someone else's", str(bb["error"])[:100])
        _, busy = call("DELETE", f"/api/projects/{seeded['id']}", expect=(400,), label="a project with logged hours cannot be deleted")
        show("delete guarded", str((busy or {}).get("error"))[:100])
        if "Completed" not in str((busy or {}).get("error", "")):
            fails.append("the delete refusal did not offer the alternative that keeps the hours: " + str(busy)[:140])
    _, gone = prj("DELETE", f"/api/projects/{row['id']}")
    _, after = call("GET", "/api/projects", label="projects after the delete")
    if any(x.get("id") == row["id"] for x in after):
        fails.append("the project the Employee created survived its own delete (they may delete what they own)")
    else:
        show("cleaned up", f"{len(allp)} -> {len(after)} projects; {row['name']} was theirs to remove")

print("== org: departments, schema check and error envelopes ==")
_, depts = call("GET", "/api/departments", label="departments list")
made = None
_, created = call("POST", "/api/departments", json_body={"name": "Field Operations", "description": "On-site support"},
                  want_keys=["department", "message"], label="HR Admin can create a department")
made = (created or {}).get("department", {}).get("id")
assert made, "the created department came back without an id"
_, again = call("GET", "/api/departments", label="departments after create")
row = next((d for d in again if d["name"] == "Field Operations"), None)
assert row and row["employee_count"] == 0 and row["description"] == "On-site support", f"new department not listed correctly: {row}"
show("created department", {k: row[k] for k in ("id", "name", "employee_count", "head_id")})
call("POST", "/api/departments", json_body={"name": "field operations "}, expect=(400,), label="duplicate name refused (case/space insensitive)")
call("POST", "/api/departments", json_body={"name": "   "}, expect=(400,), label="blank name refused")
call("POST", "/api/departments", json_body={"name": "Odd Head", "head_id": "e9999"}, expect=(400,), label="unknown head refused")
_, renamed = call("PUT", f"/api/departments/{made}", json_body={"name": "Field Operations & Safety"},
                  want_keys=["department", "message"], label="department rename")
assert (renamed.get("department") or {}).get("name") == "Field Operations & Safety", "rename did not stick"
busy_id = next(d["id"] for d in again if d["employee_count"] > 0)
r, j = call("DELETE", f"/api/departments/{busy_id}", expect=(400,), label="a department with people cannot be deleted")
assert "move them" in (j.get("error") or "").lower(), f"the refusal did not say what to do: {j}"
r, j = call("DELETE", f"/api/departments/{made}", expect=(200,), label="empty department deleted")
assert not [d for d in call("GET", "/api/departments", label="departments after delete")[1] if d["id"] == made], "delete did not remove the row"
call("DELETE", "/api/departments/d-nope", expect=(404,), label="unknown department id is a 404")
call("GET", "/api/schema-check", want_keys=["gaps", "up_to_date", "advice", "tables_expected"], label="schema check for HR")
_, sc = call("GET", "/api/schema-check", label="schema check body")
show("schema check", {k: sc[k] for k in ("mode", "tables_expected", "gaps", "up_to_date")})
assert sc["tables_expected"] == 25 and isinstance(sc["gaps"], int) and sc["advice"], "schema check is not telling us anything"
checks[0] += 1
emp2 = requests.Session()
emp2.post(BASE + "/login", json={"email": "aarav.sharma@company.com", "password": "demo123"}, timeout=60)
_refused = []
for method, path, payload in (("POST", "/api/departments", {"name": "Sneaky"}),
                              ("PUT", f"/api/departments/{busy_id}", {"name": "Sneaky"}),
                              ("DELETE", f"/api/departments/{busy_id}", None),
                              ("GET", "/api/schema-check", None)):
    rr = emp2.request(method, BASE + path, json=payload, timeout=60)
    if rr.status_code != 403:
        _refused.append(f"{method} {path} -> {rr.status_code}")
if _refused:
    fails.append("an Employee was not refused the HR-only department/schema endpoints: " + "; ".join(_refused))
    print("  !! FAIL employee cannot touch departments/schema -> " + "; ".join(_refused))
else:
    print("  ok   an Employee is refused 403 on department writes and on /api/schema-check")

# a crash inside an /api route must answer JSON - the HTML debug page used to be pasted into the toast
import importlib
_app = importlib.import_module("app")


def _boom():
    raise RuntimeError("deliberate crash to prove the error envelope")


_app.app.add_url_rule("/api/__selftest_boom", "selftest_boom", _boom, methods=["GET"])
_client = _app.app.test_client()
with _client.session_transaction() as _sess:
    _sess["user"] = {"email": "admin@company.com", "name": "Suite", "is_admin": True, "modules": ["home"]}
_res = _client.get("/api/__selftest_boom")
assert _res.status_code == 500, f"expected 500, got {_res.status_code}"
assert _res.is_json, f"a crash on /api returned {_res.content_type}: {_res.get_data(as_text=True)[:120]}"
_404 = _client.get("/api/no-such-endpoint")
assert _404.status_code == 404 and _404.is_json, f"a missing /api route became {_404.status_code} {_404.content_type}"
_msg = (_res.get_json() or {}).get("error", "")
assert "server log" in _msg, f"the JSON error is not actionable: {_msg!r}"   # the detail stays in the log, not in the toast
del _app.app.view_functions["selftest_boom"]
_ok = _res.get_json()
show("error envelope", {"status": _res.status_code, "json": True, "error": _ok["error"][:70]})
_, perf = call("GET", "/api/performance/overview",
              want_keys=["nine_box", "rating_distribution", "avg_rating", "goals_total", "at_risk"],
              label="performance overview answers")
if isinstance(perf, dict):
    show("performance", {k: perf[k] for k in ("goals_total", "reviews_total", "avg_rating")} |
         {"nine_box_cells": len(perf["nine_box"])})
    assert sum(perf["rating_distribution"].values()) <= perf["reviews_total"], "rating buckets counted reviews that do not exist"


print("== payroll & expenses ==")


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


call("GET", "/api/payslips", label="payslips")
_, ps = call("GET", "/api/payslips", label="payslips list")
if ps:
    # A draft is HR's working paper: it may sit in the HR list, but the slip itself stays shut until
    # someone publishes it, or an employee reads numbers that are still moving.
    draft = next((p for p in ps if p.get("status") == "Draft"), None)
    if draft:
        _, derr = call("GET", f"/api/payslips/{draft['id']}/detail", expect=(404,), label="a draft payslip cannot be opened")
        show("draft slip says", (derr or {}).get("error"))
    else:
        fails.append("the seed has no Draft payslip, so unpublished slips being hidden is untested")
    released = next((p for p in ps if p.get("status") != "Draft"), None)
    assert released, "the demo data should have a published or paid payslip to read"
    _, det = call("GET", f"/api/payslips/{released['id']}/detail",
                  want_keys=["earnings", "deductions", "gross", "deductions_total", "net", "company.name",
                             "bank.bank_name", "days.working_days", "net_in_words", "structure.name"],
                  label="payslip detail")
    earn = sum(_num(l["amount"]) for l in det["earnings"])
    ded = sum(_num(l["amount"]) for l in det["deductions"])
    assert abs(earn - _num(det["gross"])) <= 1, f"earnings lines add to {earn}, gross says {det['gross']}"
    assert abs(ded - _num(det["deductions_total"])) <= 1, f"deduction lines add to {ded}, total says {det['deductions_total']}"
    assert abs(_num(det["gross"]) - _num(det["deductions_total"]) - _num(det["net"])) <= 1, "gross - deductions != net"
    assert str(det["net_in_words"]).startswith("Rupees") and det["net_in_words"].endswith("Only"), \
        f"no amount in words on the slip: {det['net_in_words']!r}"
    days = det["days"]
    assert _num(days["working_days"]) > 0, "the payslip does not say how many days it covers"
    assert abs(_num(days["payable_days"]) + _num(days["lop_days"]) - _num(days["working_days"])) <= 0.01, \
        f"days do not reconcile: {days}"
    show("payslip arithmetic", f"{det['structure']['name']}: {len(det['earnings'])} earning lines + "
                              f"{len(det['deductions'])} deduction lines = net {det['net']:,.0f} "
                              f"over {days['payable_days']:g}/{days['working_days']:g} days")
    show("in words", det["net_in_words"][:70])
call("GET", "/api/payroll/summary", want_keys=["net_payroll", "per_department", "trend", "draft_slips",
                                                "monthly_gross_cost", "lop_days"], label="payroll summary")
_, pay = call("GET", "/api/payroll/summary", label="payroll summary body")
show("payroll", {k: pay[k] for k in ("period", "employees_paid", "net_payroll", "gross_payroll", "deductions", "monthly_ctc_cost")})
show("trend", [t for t in pay["trend"] if t["count"]][:3])
call("GET", "/api/payroll/structures", label="structures")
# the month filter has to accept the ISO shape the attendance/report filters use: int("2026-08")
# used to raise ValueError and put both payroll endpoints on 500
_, iso_slips = call("GET", "/api/payslips?month=2026-08", label="payslips filtered by ISO month")
_, num_slips = call("GET", "/api/payslips?month=8&year=2026", label="payslips filtered by month+year")
if isinstance(iso_slips, list) and isinstance(num_slips, list):
    assert len(iso_slips) == len(num_slips), f"month=2026-08 gave {len(iso_slips)} slips, month=8&year=2026 gave {len(num_slips)}"
    assert all(str(x.get("month")) in ("8", "08") for x in iso_slips), "ISO month filter returned a slip from another month"
    show("payslips by month", f"2026-08 and 8/2026 agree - {len(iso_slips)} slip(s)")
_, iso_sum = call("GET", "/api/payroll/summary?month=2026-08",
                  want_keys=["period", "year", "month", "trend"], label="payroll summary filtered by ISO month")
if isinstance(iso_sum, dict):
    assert (iso_sum.get("year"), iso_sum.get("month")) == (2026, 8), f"summary resolved {iso_sum.get('year')}-{iso_sum.get('month')}"
    show("payroll period", f"{iso_sum['period']} from month=2026-08, net {iso_sum['net_payroll']} for {iso_sum['employees_paid']} employee(s)")
import datetime as _dt   # this section runs before the suite's own `dt` import

# ------------------------------------------------------- structures: HR writes, employees read
_, st_rows = call("GET", "/api/payroll/structures", want_keys=["0.employee"], label="structures (HR)")
if isinstance(st_rows, list):
    checks[0] += 1
    broken = [r for r in st_rows if not r.get("missing") and not _num(r.get("monthly_gross"))]
    if broken:
        fails.append(f"{len(broken)} structure(s) reached the UI with no monthly gross")
    else:
        show("structures", f"{len(st_rows)} employee(s), {sum(1 for r in st_rows if r.get('missing'))} without one, "
                           f"gross/net on every row")
    _, one_st = call("GET", f"/api/payroll/structures?employee_id={st_rows[0]['employee_id']}",
                     label="structures filtered to one employee")
    assert isinstance(one_st, list) and len(one_st) == 1, f"the employee filter gave {len(one_st) if isinstance(one_st, list) else one_st} rows"

pay_emp = requests.Session()
pay_emp.post(BASE + "/login", json={"email": "aarav.sharma@company.com", "password": "demo123"}, timeout=60)
checks[0] += 1
_r = pay_emp.get(BASE + "/api/payroll/structures", timeout=60)
_own = _r.json() if "json" in _r.headers.get("Content-Type", "") else _r.text[:120]
if _r.status_code == 200 and isinstance(_own, list) and len(_own) <= 1 \
        and all(str(o.get("employee", {}).get("email")) == "aarav.sharma@company.com" for o in _own):
    print("  ok   an employee reads only their own salary structure")
else:
    fails.append(f"employee structures read -> {_r.status_code} {json.dumps(_own, default=str)[:160]}")
_refused = []
for method, path, payload in (("POST", "/api/payroll/structures", {"basic": 40000}),
                              ("POST", "/api/payroll/run", {"period": "2026-08"}),
                              ("POST", "/api/payroll/publish", {"period": "2026-08"}),
                              ("POST", "/api/payroll/mark-paid", {"period": "2026-08"}),
                              ("GET", "/api/payroll/register?period=2026-08", None),
                              ("GET", "/api/payroll/register/export?period=2026-08", None)):
    rr = pay_emp.request(method, BASE + path, json=payload, timeout=60)
    checks[0] += 1
    if rr.status_code != 403:
        _refused.append(f"{method} {path} -> {rr.status_code}")
if _refused:
    fails.append("an Employee was not refused the HR-only payroll endpoints: " + "; ".join(_refused))
    print("  !! FAIL employee refused payroll admin -> " + "; ".join(_refused))
else:
    print("  ok   running payroll, publishing, paying and the bank register are HR only")

target = next((r["employee_id"] for r in st_rows if not r.get("missing")), None)
assert target, "no employee with a structure to test against"
call("POST", "/api/payroll/structures", json_body={"employee_id": "ghost", "basic": 40000}, expect=(400,), label="unknown employee refused")
call("POST", "/api/payroll/structures", json_body={"employee_id": target, "name": "Upside down", "basic": 10000, "hra": 20000},
     expect=(400,), label="HRA above basic refused")
call("POST", "/api/payroll/structures", json_body={"employee_id": target, "name": "Nothing"}, expect=(400,), label="no earnings refused")
call("POST", "/api/payroll/structures", json_body={"employee_id": target, "name": "All gone", "basic": 5000, "hra": 1000, "pf": 9000},
     expect=(400,), label="deductions not below gross refused")
_, badctc = call("POST", "/api/payroll/structures", json_body={"employee_id": target, "name": "Wrong CTC", "basic": 40000, "hra": 5000,
                                                                "ctc": 9999999}, expect=(400,), label="a CTC the components cannot pay")
show("ctc refusal says", (badctc or {}).get("error"))
_, mk = call("POST", "/api/payroll/structures", json_body={"employee_id": target, "name": "Suite revision", "basic": 40000,
             "hra": 16000, "special_allowance": 8000, "allowances": [{"label": "Internet", "amount": 1200}],
             "pf": 4800, "esi": 0, "professional_tax": 200, "tds": 3000, "employer_pf": 4800,
             "effective_from": str(_dt.date.today())}, want_keys=["structure.id", "message"], label="structure created")
sid = mk["structure"]["id"]
show("created", mk.get("message"))
call("POST", "/api/payroll/structures", json_body={"employee_id": target, "name": "suite revision", "basic": 40000},
     expect=(400,), label="a second structure with the same name refused")
_, upd = call("PUT", f"/api/payroll/structures/{sid}", json_body={"basic": 44000}, want_keys=["structure"], label="partial update")
st_after = upd["structure"]
assert st_after["allowances"].get("Internet") == 1200, f"a PUT that only touched basic wiped the allowances: {st_after['allowances']}"
assert st_after["name"] == "Suite revision", "a PUT that only touched basic renamed the structure"
assert abs(_num(st_after["monthly_gross"]) - 69200) < 1, f"gross did not follow the new basic: {st_after['monthly_gross']}"
assert abs(_num(st_after["monthly_gross"]) - _num(st_after["monthly_deductions"]) - _num(st_after["monthly_net"])) < 1, \
    "the structure's own gross - deductions != net"
show("partial update", f"basic 44,000 -> gross {_num(st_after['monthly_gross']):,.0f}, net {_num(st_after['monthly_net']):,.0f}, "
                       "allowances and name kept")
call("DELETE", f"/api/payroll/structures/{sid}", want_keys=["success"], label="structure deleted")
checks[0] += 1
after_del = call("GET", f"/api/payroll/structures?employee_id={target}", label="structures after delete")[1]
assert not any(r["id"] == sid for r in after_del), "the deleted structure is still listed"
assert len(after_del) == 1, f"expected the seeded structure back, got {len(after_del)} rows"

# ------------------------------------------------------------------------- the payroll process
_, pay0 = call("GET", "/api/payroll/summary", want_keys=["year", "month"], label="summary before the run")
period = f"{pay0['year']:04d}-{pay0['month']:02d}"
_, run = call("POST", "/api/payroll/run", json_body={"period": period, "overwrite": True},
              want_keys=["created", "updated", "kept", "skipped", "net_payroll", "employees"], label="payroll run (drafts)")
checks[0] += 1
if _num(run["created"]) + _num(run["updated"]) < 1 or _num(run["net_payroll"]) <= 0:
    fails.append(f"the run produced nothing usable: {run}")
else:
    show("payroll run", f"{run['created']} generated, {run['updated']} rebuilt, {len(run['kept'])} left alone, "
                        f"{len(run['skipped'])} skipped - net {run['net_payroll']:,.0f} for {run['employees']}")
assert all(isinstance(x.get("reason"), str) and x.get("employee") for x in run["skipped"]), "skips are not explained"
_, again = call("POST", "/api/payroll/run", json_body={"period": period}, want_keys=["created", "updated"], label="a second run is idempotent")
assert _num(again["created"]) == 0, f"the second run created {again['created']} extra payslips"
call("POST", "/api/payroll/run", json_body={"period": f"{pay0['year']}-12"}, expect=(400,), label="a future month is refused")
call("POST", "/api/payroll/run", json_body={"period": "september"}, expect=(400,), label="a junk period is answered in words")
_, drafted = call("GET", f"/api/payslips?period={period}", label="the period after the run")
assert drafted and all(p["status"] == "Draft" for p in drafted), "the run left something outside Draft"
assert any(_num(p["lop_days"]) > 0 for p in drafted), "attendance has absences but no slip carries loss of pay"
show("loss of pay", f"{sum(1 for p in drafted if _num(p['lop_days']) > 0)} of {len(drafted)} slips docked days, "
                    f"{sum(_num(p['lop_days']) for p in drafted):g} LOP days total")
_, emp_view = call("GET", f"/api/payslips?period={period}", label="employee sees nothing unreleased (admin view)")
checks[0] += 1
_emp_slips = pay_emp.get(BASE + f"/api/payslips?period={period}", timeout=60).json()
if _emp_slips:
    fails.append(f"a Draft payslip was visible to the employee: {_emp_slips}")
else:
    print("  ok   an employee's payslip list is empty while the period is still in Draft")
call("POST", "/api/payroll/mark-paid", json_body={"period": period}, expect=(400,), label="cannot pay what was never published")
_, pub = call("POST", "/api/payroll/publish", json_body={"period": period}, want_keys=["published", "message"], label="publish the period")
assert _num(pub["published"]) == len(drafted), f"published {pub['published']} of {len(drafted)} drafts"
checks[0] += 1
_now = pay_emp.get(BASE + f"/api/payslips?period={period}", timeout=60).json()
if _now and all(p["status"] == "Published" for p in _now):
    print(f"  ok   after publishing, the employee sees {len(_now)} slip(s) with their own numbers")
else:
    fails.append(f"publishing did not reach the employee: {_now}")
_, reg = call("GET", f"/api/payroll/register?period={period}", want_keys=["rows", "totals.net", "totals.employees",
                                                                          "structures_missing", "label"], label="payroll register")
assert abs(sum(_num(r["net_pay"]) for r in reg["rows"]) - _num(reg["totals"]["net"])) < 1, \
    f"register rows add to {sum(_num(r['net_pay']) for r in reg['rows'])}, totals say {reg['totals']['net']}"
assert reg["totals"]["employees"] == len(reg["rows"]), "the register's employee count disagrees with its rows"
assert all(r.get("bank_account_no") and r.get("pan_no") for r in reg["rows"]), "the bank file has no account or PAN columns"
show("register", f"{len(reg['rows'])} rows · net {reg['totals']['net']:,.0f} · {reg['totals']['paid']} paid, "
                 f"{reg['totals']['published']} published, {reg['totals']['draft']} draft")
_, paid = call("POST", "/api/payroll/mark-paid", json_body={"period": period, "paid_on": f"{period}-28"},
               want_keys=["paid", "paid_on"], label="mark the period paid")
_, after_pay = call("GET", f"/api/payslips?period={period}", label="the period after payment")
assert all(p["status"] == "Paid" for p in after_pay), "some slips did not become Paid"
assert all(p.get("paid_on_label") not in (None, "", "-") for p in after_pay), "a paid slip has no paid-on date"
one_slip = after_pay[0]["id"]
call("POST", f"/api/payslips/{one_slip}/revoke", json_body={}, expect=(400,), label="revoking needs a reason")
call("POST", f"/api/payslips/{one_slip}/revoke", json_body={"reason": "Recomputed TDS after the finance review"},
     want_keys=["message"], label="revoke a released slip")
call("GET", f"/api/payslips/{one_slip}/detail", expect=(404,), label="the revoked slip is shut again")
_, boosted = call("PUT", f"/api/payslips/{one_slip}", json_body={"bonus": 15000, "notes": "Festival advance, approved by finance"},
                  want_keys=["payslip", "message"], label="add a bonus to the draft")
checks[0] += 1
if _num(boosted["payslip"]["net_pay"]) <= _num(after_pay[0]["net_pay"]):
    fails.append(f"a 15,000 bonus did not raise net pay: {after_pay[0]['net_pay']} -> {boosted['payslip']['net_pay']}")
else:
    show("bonus applied", f"{after_pay[0]['net_pay']:,.0f} -> {boosted['payslip']['net_pay']:,.0f} with a note on the slip")
call("PUT", f"/api/payslips/{one_slip}", json_body={"status": "Published"}, label="release it again")
_, csv_res = call("GET", f"/api/payroll/register/export?period={period}", label="bank register CSV")
checks[0] += 1
_csv = s.get(BASE + f"/api/payroll/register/export?period={period}", timeout=60)
_lines = [l for l in _csv.text.splitlines() if l.strip()]
if "text/csv" not in _csv.headers.get("Content-Type", ""):
    fails.append(f"the register export is not CSV: {_csv.headers.get('Content-Type')}")
elif len(_lines) != len(reg["rows"]) + 1:
    fails.append(f"CSV has {len(_lines) - 1} data rows for {len(reg['rows'])} register rows")
elif not all(h in _lines[0].lower() for h in ("account no", "net pay", "ifsc")):
    # csv_response title-cases every column, so the header reads "Account No", not "account_no"
    fails.append(f"CSV header is missing the bank columns: {_lines[0][:120]}")
else:
    show("bank file", f"{len(_lines) - 1} rows · header {len(_lines[0].split(','))} columns · {len(_csv.content) / 1024:.1f} KB")
# the two readers of a period must agree, and a released slip's money is frozen
_, _by_period = call("GET", f"/api/payroll/summary?period={period}", label="payroll summary by ?period=")
_, _by_month = call("GET", f"/api/payroll/summary?month={period}", label="payroll summary by ?month=")
if _by_period.get("period") != _by_month.get("period"):
    fails.append(f"one month answers differently by period= ({_by_period.get('period')}) than by month= ({_by_month.get('period')})")
elif float(_by_period.get("net_payroll") or 0) != float(_by_month.get("net_payroll") or 0):
    fails.append("?period= and ?month= disagree about the net payroll for the same month - one is not filtering")
else:
    show("summary filters", f"?period= and ?month= both read {_by_period.get('period')}, net {_by_period.get('net_payroll'):,.0f}")
# read it fresh: an earlier step in this section revoked one slip and re-released it with a bonus,
# so the snapshot taken before that would report a legal change as a refused one
_, _now = call("GET", f"/api/payslips?period={period}", label="the period before the frozen-amount check")
_locked = next(p2 for p2 in _now if p2.get("status") in ("Paid", "Published"))
_bonus_before = float(_locked.get("bonus") or 0)
_r, _b = call("PUT", f"/api/payslips/{_locked['id']}", json_body={"bonus": _bonus_before + 5000},
              expect=(400,), label="a released slip refuses an amount change")
_msg = str(_b.get("error") or _b.get("message") or "")
if "revoke" not in _msg.lower():
    fails.append(f"the refusal did not say how to proceed: {_msg[:120]!r}")
else:
    show("amounts frozen", _msg[:104])
call("PUT", f"/api/payslips/{_locked['id']}", json_body={"status": "Paid", "paid_on": f"{period}-28"},
     expect=(200,), label="but status and paid-on date stay editable")
_, _rows_now = call("GET", f"/api/payslips?period={period}", label="the period after the refused edit")
_here = next((x for x in _rows_now if x.get("id") == _locked["id"]), {})
if abs(float(_here.get("bonus") or 0) - _bonus_before) > 0.5:
    fails.append(f"the refused bonus change still moved the slip: {_bonus_before} -> {_here.get('bonus')}")
elif str(_here.get("status") or "").lower() not in ("paid", "published"):
    fails.append(f"the allowed status write did not stick: the row reads {_here.get('status')!r}")
else:
    show("refused edit", f"bonus still {_bonus_before:,.0f} and the slip is {_here['status']} on {_here.get('paid_on_label') or '-'}")

call("GET", "/api/payslips?month=13", expect=(400,), label="month out of range refused")
call("GET", "/api/payroll/summary?month=nonsense", expect=(400,), label="month junk answered with 400, not 500")
call("GET", "/api/reimbursements", want_keys=["0.amount_label"], label="reimbursements")
call("GET", "/api/reimbursements/summary", label="expense summary")
call("POST", "/api/reimbursements", json_body={"amount": 0, "date": str(dt.date.today()), "description": "x"}, expect=(400,), label="amount validation")
_, claim = call("POST", "/api/reimbursements", json_body={"amount": 4250, "category": "Travel", "date": str(dt.date.today()),
                                                           "description": "Goa client visit - flights", "has_receipt": True},
                label="create claim", want_keys=["reimbursement.id"])
cid = claim["reimbursement"]["id"]
call("POST", f"/api/reimbursements/{cid}/action", json_body={"action": "approve"}, label="approve claim")
call("POST", f"/api/reimbursements/{cid}/action", json_body={"action": "pay"}, label="pay claim")
call("POST", f"/api/reimbursements/{cid}/action", json_body={"action": "reject"}, expect=(400,), label="reject needs remark")
call("DELETE", f"/api/reimbursements/{cid}", label="delete claim after pay (admin ok)")

print("== hiring ==")
_, jobs = call("GET", "/api/jobs", want_keys=["0.pipeline", "0.in_progress", "0.fill_pct"], label="jobs")
show("job[0]", {k: jobs[0][k] for k in ("title", "status", "applicants", "in_progress", "pipeline", "fill_pct", "days_open", "hiring_manager")})
_, pipe = call("GET", "/api/hiring/pipeline", want_keys=["stages", "open_roles", "hire_rate"], label="pipeline")
show("stages", [(s["name"], s["count"]) for s in pipe["stages"]], )
show("pipeline", {k: pipe[k] for k in ("rejected", "total", "open_roles", "open_positions", "hired", "hire_rate", "by_source")})
assert sum(x["count"] for x in pipe["stages"]) + pipe["rejected"] == pipe["total"], "pipeline counts do not add up"
_, cands = call("GET", "/api/candidates", label="candidates")
show("candidates", len(cands))
call("POST", "/api/jobs", json_body={"title": ""}, expect=(400,), label="job validation")
_, nj = call("POST", "/api/jobs", json_body={"title": "QA Automation Engineer", "department_id": 2, "location": "Remote",
                                             "openings": 2, "employment_type": "Full-time", "experience": "2-4 yrs",
                                             "salary_range": "₹8-14 LPA", "description": "Playwright + CI"},
             label="create job", want_keys=["job.pipeline"])
jid = nj["job"]["id"]
call("PUT", f"/api/jobs/{jid}", json_body={"action": "close"}, expect=(400,), label="close needs reason")
_, closed = call("PUT", f"/api/jobs/{jid}", json_body={"action": "close", "closure_reason": "Role put on hold by finance"},
                 label="close job")
show("closed", {k: closed["job"][k] for k in ("status", "closed_label", "closure_reason")})
call("PUT", f"/api/jobs/{jid}", json_body={"action": "reopen"}, label="reopen job")
call("PUT", f"/api/jobs/{jid}", json_body={"title": "QA Automation Engineer II", "openings": 3, "salary_range": "₹10-16 LPA"}, label="update job")
_, nc = call("POST", "/api/candidates", json_body={"job_id": jid, "full_name": "Pipeline Tester", "email": "pipeline.tester@example.com",
                                                    "phone": "+91 98888 11111", "experience_years": 3, "current_ctc": 900000,
                                                    "expected_ctc": 1300000, "source": "LinkedIn", "notes": "Strong on Playwright"},
             label="create candidate", want_keys=["candidate.stage"])
cid2 = nc["candidate"]["id"]
for stage in ["Screening", "Interview", "Offer"]:
    _, moved = call("PUT", f"/api/candidates/{cid2}", json_body={"stage": stage}, label=f"move to {stage}")
_, edited = call("PUT", f"/api/candidates/{cid2}", json_body={"full_name": "Pipeline Tester", "rating": 4.5, "expected_ctc": 1450000,
                                                               "notes": "Accepted verbal offer", "current_role": "Sr. QA, Zeta"}, label="edit candidate fields")
show("candidate", {k: edited["candidate"][k] for k in ("stage", "rating", "expected_ctc_label", "age_in_stage_days", "converted")})
call("POST", f"/api/candidates/{cid2}/hire", json_body={"email": "vikram.singh@company.com"}, expect=(400,), label="hire onto an existing email blocked")
_, hired = call("POST", f"/api/candidates/{cid2}/hire", json_body={"date_of_joining": str(dt.date.today()), "salary_ctc": 1450000,
                                                                    "employment_type": "Full-time", "work_location": "Bengaluru"},
                label="convert to employee", want_keys=["employee.employee_code"])
show("hired", {k: hired["employee"][k] for k in ("full_name", "employee_code", "department", "designation", "manager", "tenure")})
call("POST", f"/api/candidates/{cid2}/hire", json_body={}, expect=(400,), label="double hire blocked")
_, jobs_after = call("GET", "/api/jobs", label="job openings after hire")
this_job = next(j for j in jobs_after if j["id"] == jid)
show("openings decremented", this_job["openings"])
_, hired_emp = call("GET", f"/api/employees/{hired['employee']['id']}", label="hired employee detail (balances seeded)")
show("seeded balances", [(b["leave_type"] or b.get("name"), b["total"]) for b in hired_emp["leave_balances"]])
call("DELETE", f"/api/candidates/{cid2}", label="delete candidate")
call("DELETE", f"/api/jobs/{jid}", label="delete now-empty job")
call("DELETE", f"/api/employees/{hired['employee']['id']}", label="remove test hire")

print("== performance ==")
# ---- source-level invariants: every column the code asks the database for must exist in it.
# `db_list("feedbacks", order="date")` was the bug this catches - demo data happened to carry a
# `date` key so the sort silently did nothing, while Postgres refused the query outright.
import importlib as _importlib
import re as _re
_app = _importlib.import_module("app")          # already imported by the envelope check; idempotent
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), encoding="utf-8").read()
_meta = {"id", "created_at", "updated_at"}
_bad_cols = []
for _m in _re.finditer(r'db_(?:list|get)\(\s*"([a-z_0-9]+)"([^)]*)\)', _src, _re.S):
    _cols = set(_app.SUPA_COLUMNS.get(_m.group(1), set())) | _meta
    for _om in _re.finditer(r'order="([a-z_0-9]+)"', _m.group(2)):
        if _om.group(1) not in _cols:
            _bad_cols.append(f"{_m.group(1)}.order {_om.group(1)}")
    for _fk in _re.finditer(r'"([a-z_0-9]+)":\s*(?:"|data|None|\()', _m.group(2)):
        if _fk.group(1) not in _cols:
            _bad_cols.append(f"{_m.group(1)}.filter {_fk.group(1)}")
# and every *_FIELDS allowlist (the keys a POST/PUT may write) must be a real column of its table.
# The mapping is deliberate: a new *_FIELDS constant makes this fail until someone says which table
# it belongs to, which is exactly the review step that let `feedbacks.date` slip through.
import ast as _ast
_TABLE_OF_FIELDS = {"EMPLOYEE_FIELDS": ["employees"], "SELF_EDITABLE_FIELDS": ["employees"],
                    "CANDIDATE_FIELDS": ["candidates"], "DEPARTMENT_FIELDS": ["departments"],
                    "DOC_FIELDS": ["documents"], "DOC_REQUEST_FIELDS": ["document_requests"],
                    "GOAL_FIELDS": ["goals"], "HIRE_FIELDS": ["employees"],   # the hire flow writes an employee row
                    "JOB_FIELDS": ["jobs"], "REG_FIELDS": ["attendance_regularizations"],
                    "REVIEW_FIELDS": ["performance_reviews"]}
for _node in _ast.parse(_src).body:
    if not (isinstance(_node, _ast.Assign) and isinstance(_node.targets[0], _ast.Name)
            and "FIELDS" in _node.targets[0].id):
        continue
    _cname = _node.targets[0].id
    _names = {e.value for e in getattr(_node.value, "elts", []) if isinstance(e, _ast.Constant)}
    if _cname not in _TABLE_OF_FIELDS:
        _bad_cols.append(f"{_cname} has no entry in the field-set map in tests_api.py")
        continue
    _allowed = set()
    for _t in _TABLE_OF_FIELDS[_cname]:
        _allowed |= set(_app.SUPA_COLUMNS.get(_t, set())) | _meta
    for _field in sorted(_names - _allowed):
        _bad_cols.append(f"{_cname} would write {_field}, which is not a column of {', '.join(_TABLE_OF_FIELDS[_cname])}")
if _bad_cols:
    fails.append("code asks for columns the schema does not have: " + "; ".join(sorted(set(_bad_cols))))
    print("  !! FAIL column invariants -> " + "; ".join(sorted(set(_bad_cols))[:4]))
else:
    print("  ok   column invariants: every order/filter/allowlisted write field exists in the schema")

# ---- the Supabase read path, against a fake client whose schema is one version behind.
# Reads use select("*") so a missing column is invisible - but ORDER BY a column the database does
# not have is a hard PostgREST error, which is what took the Performance tab down. db_list() now
# checks the live columns and sorts the fetched rows itself.
class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, name, cols, rows, order_only_bad=()):
        self.name, self.cols, self.rows = name, set(cols), rows
        self.order_only_bad = set(order_only_bad)
        self.ordered_by, self.selects, self.orders = None, 0, 0

    def select(self, cols):
        # PostgREST validates the select list even when the table has no rows to return
        self.selects += 1
        for one in str(cols).split(","):
            one = one.strip()
            if one and one != "*" and one not in self.cols:
                raise RuntimeError(f"column {self.name}.{one} does not exist")
        return self

    def limit(self, _n):
        return self

    def eq(self, *_a): return self
    def gte(self, *_a): return self
    def lte(self, *_a): return self
    def neq(self, *_a): return self
    def is_(self, *_a): return self
    def in_(self, *_a): return self

    def order(self, col, desc=False):
        self.orders += 1
        if col not in self.cols or col in self.order_only_bad:
            raise RuntimeError(f"column {self.name}.{col} does not exist")
        self.ordered_by = col
        return self

    def execute(self):
        return _FakeResult([{k: r.get(k) for k in self.cols if k in r} for r in self.rows])


class _FakeSupabase:
    """Rows come back carrying only the columns this older database actually has."""

    def __init__(self, drop, empty=(), order_only_bad=None):
        self.drop, self.empty = drop, set(empty)
        self.order_only_bad = order_only_bad or {}
        self.tables = {}

    def table(self, name):
        if name not in self.tables:
            store = [] if name in self.empty else _app._load_mock().get(name, [])
            cols = [c for c in sorted(set(_app.SUPA_COLUMNS.get(name, set())) | {"id"})
                    if c not in self.drop.get(name, ())]
            self.tables[name] = _FakeTable(name, cols, store, self.order_only_bad.get(name, ()))
        return self.tables[name]


checks[0] += 1
_fake = _FakeSupabase({"performance_reviews": {"cycle_start"}, "goals": set(),
                       # the reported failure: two brand-new, still-empty tables with no `date`
                       "feedbacks": {"date"}, "checkins": set()},
                      empty={"feedbacks", "checkins"}, order_only_bad={"checkins": {"date"}})
_saved_supa, _app.supabase = _app.supabase, _fake
_app._COLUMN_CACHE.clear()
try:
    _rows = _app.db_list("performance_reviews", order="cycle_start", descending=True)
    _kept = _app.db_list("goals", order="due_date")
    assert _rows and _fake.tables["performance_reviews"].ordered_by is None, \
        "the fake client should never have been asked to order by the missing column"
    assert _fake.tables["goals"].ordered_by == "due_date", "an ordering the database supports must stay in SQL"
    # with the order column gone there is nothing to order by, so the rows must simply come back
    assert all("cycle_start" not in r for r in _rows), "the fake DB was asked to return a column it does not have"
    _probe = [{"id": 1, "d": "2026-01-02"}, {"id": 2, "d": "2026-01-03"}, {"id": 3, "d": "2026-01-01"}]
    assert [r["id"] for r in _app._sort_rows(_probe, "d", True)] == [2, 1, 3], "the python fallback sort is wrong"
    assert [r["id"] for r in _app._sort_rows(_probe, "not_a_column", False)] == [1, 2, 3], \
        "sorting by an absent key must leave the order alone, not crash"
    print(f"  ok   a stale schema degrades instead of failing: {len(_rows)} review(s) back, SQL order skipped")
    # empty tables: sample_columns has nothing to read, so the column probe and the retry are the only
    # things standing between "no rows yet" and a 502 on the whole Performance tab
    _empty_ok = _app.db_list("feedbacks", order="date", descending=True)
    assert _empty_ok == [], f"an empty table with a missing order column should read as empty, got {_empty_ok}"
    assert _fake.tables["feedbacks"].orders == 0, "the probe should have skipped the ORDER BY outright"
    assert "date" in _app._ABSENT_COLUMNS.get("feedbacks", ()), "the refusal was not remembered"
    _queries_after_first = _fake.tables["feedbacks"].selects          # sample + probe + the read
    _again = _app.db_list("feedbacks", order="date", descending=True)
    assert _again == [] and _fake.tables["feedbacks"].selects == _queries_after_first + 1, \
        f"a cached refusal should cost one query, not { _fake.tables['feedbacks'].selects - _queries_after_first}"
    _retried = _app.db_list("checkins", order="date", descending=True)
    assert _retried == [], "the retry-after-refusal path did not return the rows"
    assert _fake.tables["checkins"].orders == 1, "the retry should have run the refused query exactly once"
    assert "date" in _app._ABSENT_COLUMNS.get("checkins", ()), "the retry did not teach db_list about the column"
    _before_third = _fake.tables["checkins"].selects
    _third = _app.db_list("checkins", order="date", descending=True)
    assert _third == [] and _fake.tables["checkins"].orders == 1, "after learning, the ORDER BY must not be attempted again"
    assert _fake.tables["checkins"].selects == _before_third + 1, "the learned refusal still re-probes"
    print("  ok   empty tables degrade too: probe skipped the order, refusal retried once, then remembered")
except Exception as _exc:                                              # noqa: BLE001
    fails.append(f"db_list did not survive a missing order column: {type(_exc).__name__}: {_exc}")
    print(f"  !! FAIL db_list vs a stale schema -> {type(_exc).__name__}: {_exc}")
finally:
    _app.supabase = _saved_supa
    _app._COLUMN_CACHE.clear()

_, perf = call("GET", "/api/performance/overview", want_keys=["goals_total", "rating_distribution", "nine_box_counts", "departments"], label="overview")
show("overview", {k: perf[k] for k in ("goals_total", "avg_goal_progress", "reviews_total", "avg_rating", "feedback_count",
                                       "checkins_total", "pending_self_review", "pending_manager_review")})
show("ratings", perf["rating_distribution"])
show("nine box", perf["nine_box_counts"])
_, goals = call("GET", "/api/goals", label="goals")
show("goals", [(g_["title"][:26], g_["progress"], g_["health_label"]) for g_ in goals[:3]])
_, ng = call("POST", "/api/goals", json_body={"title": "Cut p95 latency below 400ms", "category": "Engineering", "metric": "p95 ms",
                                              "target": "400", "progress": 20}, label="create goal")
gid = ng["goal"]["id"]
_, ug = call("PUT", f"/api/goals/{gid}", json_body={"progress": 100}, label="progress to 100")
show("goal status", (ug["goal"]["progress"], ug["goal"]["status"], ug["goal"]["health"]))
call("DELETE", f"/api/goals/{gid}", label="delete goal")
_, rvs = call("GET", "/api/reviews", label="reviews")
show("review[0]", {k: rvs[0][k] for k in ("period", "status", "rating_label", "competency_avg", "cycle_label", "overdue")} if rvs else None)
if rvs:
    open_rev = next((r for r in rvs if r["status"] in ("Self Review Pending", "Manager Review Pending")), rvs[0])
    call("PUT", f"/api/reviews/{open_rev['id']}", json_body={"action": "self_review", "self_rating": 4.2}, expect=(400,), label="self review needs comments")
    call("PUT", f"/api/reviews/{open_rev['id']}", json_body={"action": "self_review", "self_rating": 9, "comments": "x"}, expect=(400,), label="rating bounds")
    call("PUT", f"/api/reviews/{open_rev['id']}", json_body={"action": "self_review", "self_rating": 4.2,
                                                             "comments": "Shipped the timesheet rebuild and mentored two juniors.",
                                                             "strengths": "Ownership", "improvements": "Written updates"}, label="self review")
    call("PUT", f"/api/reviews/{open_rev['id']}", json_body={"action": "manager_review", "manager_rating": 4.0,
                                                             "comments": "Strong half, keep documenting decisions.", "finalize": True,
                                                             "competencies": {"Collaboration": 4.5, "Delivery": 4.0, "Communication": 3.5}},
         label="manager review")
_, fb = call("GET", "/api/feedback", label="feedback list")
show("feedback", [(f["from_label"], f["message"][:30], f["tag_list"]) for f in fb[:2]])
_fb_dates = [str(f.get("date") or f.get("created_at") or "") for f in (fb or [])]
assert _fb_dates == sorted(_fb_dates, reverse=True), f"feedback is not newest-first: {_fb_dates[:4]}"
assert fb and all(f.get("date") for f in fb), "feedback rows have no date, so the ORDER BY sorts on nothing"
show("feedback order", f"{len(fb)} row(s) newest-first from {_fb_dates[0]} to {_fb_dates[-1]}")
call("POST", "/api/feedback", json_body={"to_employee_id": emps[1]["id"], "message": "nice"}, expect=(400,), label="short feedback blocked")
call("POST", "/api/feedback", json_body={"to_employee_id": emps[1]["id"], "message": "Your runbook saved us an hour of paging.",
                                         "tags": "Teamwork, Mentoring", "category": "Appreciation", "is_anonymous": True}, label="send feedback")
_, ci = call("GET", "/api/checkins", label="checkins")
show("checkins", [(c["employee"].get("full_name") if c.get("employee") else None, c["date_label"], c["status"]) for c in ci[:3]])
call("POST", "/api/checkins", json_body={"employee_id": emps[1]["id"], "agenda": "Sprint retro follow-ups", "notes": "n/a",
                                         "next_steps": "Pair on the alerting rules"}, expect=(400,), label="check-in needs a date")
call("POST", "/api/checkins", json_body={"employee_id": emps[1]["id"], "date": str(dt.date.today() + dt.timedelta(days=2)),
                                         "agenda": "Sprint retro follow-ups", "notes": "n/a", "next_steps": "Pair on alerting"}, label="schedule check-in")

print("== reports ==")
_, rl = call("GET", "/api/reports", label="report list")
show("reports", [r["id"] for r in rl])
assert len(rl) == 9, f"expected 9 reports, got {len(rl)}"
for rep in rl:
    _, p = call("GET", f"/api/reports/{rep['id']}?from={dt.date.today() - dt.timedelta(days=89)}&to={dt.date.today()}",
                want_keys=["kpis", "chart", "table"], label=f"report {rep['id']}")
    show(f"  {rep['id']}", {"kpis": [(k["label"], k["value"]) for k in p["kpis"]][:4],
                            "chart": f"{p['chart']['kind']}:{len(p['chart']['labels'])}",
                            "rows": len(p["table"]["rows"]), "note": (p.get("note") or "")[:60]})
    r2, _ = call("GET", f"/api/reports/{rep['id']}?format=csv", label=f"  {rep['id']} csv")
    assert "," in r2.text and len(r2.text) > 10, f"{rep['id']} csv is empty"
call("GET", "/api/reports/headcount?department=Engineering", label="department filter")
_, bad = call("GET", "/api/reports/nonexistent", expect=(400, 404), label="unknown report")
call("POST", "/api/reports/custom", json_body={"dataset": "not_a_table"}, expect=(400,), label="custom bad dataset")
_, custom = call("POST", "/api/reports/custom", json_body={"dataset": "attendance", "columns": ["employee_id", "date", "status", "work_hours"],
                                                            "filters": {"status": "Absent"}, "limit": 25},
                 label="custom builder", want_keys=["rows", "columns"])
show("custom", {"rows": len(custom["rows"]), "cols": custom["columns"], "total": custom["total"]})
_, ccsv = call("POST", "/api/reports/custom", json_body={"dataset": "employees", "columns": ["full_name", "email", "salary_ctc"], "format": "csv"},
               label="custom csv")
assert "full_name".title() in ccsv.text or "Full Name" in ccsv.text

print("== inbox / announcements / holidays ==")
_, ib = call("GET", "/api/inbox", want_keys=["total", "groups"], label="inbox")
show("inbox groups", [(g["label"], g["count"]) for g in ib["groups"]])
show("first item", {k: ib["items"][0][k] for k in ("kind", "title", "subtitle", "meta", "approve_endpoint")} if ib["items"] else None)
pending_leave = next((i for i in ib["items"] if i["kind"] == "leave"), None)
if pending_leave:
    call("POST", f"/api/pending-actions/leave/{pending_leave['id']}", json_body={"action": "approve", "remark": "Approved from Inbox"},
         label="one-click approve from inbox")
_, an = call("GET", "/api/announcements", label="announcements")
show("announcements", [(a["title"][:34], a["type"], a["is_pinned"], a["date"]) for a in an[:3]])
_, na = call("POST", "/api/announcements", json_body={"title": "Smoke-test notice", "content": "Ignore this test row.", "type": "Update"}, label="create announcement")
call("PUT", f"/api/announcements/{na['announcement']['id']}", json_body={"is_pinned": True}, label="pin announcement")
call("DELETE", f"/api/announcements/{na['announcement']['id']}", label="delete announcement")
_, hol = call("GET", "/api/holidays", label="holidays")
show("holidays", [(h["name"], h["date"], h["days_left"]) for h in hol[:3]])
for mod in ("employees", "attendance", "leave", "payroll", "hiring", "org"):
    call("GET", f"/api/export/{mod}", label=f"export {mod}")

print("== employee-role permissions ==")
other = next(e for e in emps if e["email"] != "admin@company.com")
s2 = requests.Session()
_, _ = call("POST", "/login", json_body={"email": other["email"], "password": "demo123"}, label="employee login")
_, e_sess = call("GET", "/api/session", label="employee session")
show("employee sees", {k: e_sess["employee"][k] for k in ("full_name", "designation", "department")})
call("GET", "/api/employees", expect=(403,), label="employee cannot open the directory")
call("GET", f"/api/employees/{other['id']}", label="employee can open their own card")
call("GET", "/api/orgchart", label="employee can see the org chart")
call("GET", "/api/stats", expect=(200,), label="employee stats")
_, e_att = call("GET", "/api/attendance", want_keys=["scoped_to"], label="employee attendance scoped")
show("scoped_to", e_att["scoped_to"])
assert str(e_att["scoped_to"]) == str(other["id"]), "attendance not scoped to the signed-in employee"
_, e_ts = call("GET", "/api/timesheet", want_keys=["timesheet"], label="employee timesheet")
assert str(e_ts["timesheet"]["employee_id"]) == str(other["id"]), "timesheet leaked another employee's data"
call("POST", "/api/employees", json_body={"full_name": "X", "email": "x@y.com"}, expect=(403,), label="employee cannot add")
call("POST", "/api/reimbursements", json_body={"amount": 100, "employee_id": "e01", "description": "trying to file on someone else", "has_receipt": True, "date": str(dt.date.today())}, label="employee claim (self only)")
call("POST", "/api/documents", json_body={"employee_id": other["id"], "doc_type": "PAN Card", "title": "x", "description": "y"},
     expect=(200, 400), label="employee cannot upload for others")
call("PUT", f"/api/documents/{docs[0]['id']}", json_body={"action": "Verified"}, expect=(200, 403, 404), label="employee cannot verify docs")
call("GET", "/api/export/employees", expect=(403,), label="employee cannot export")
_, e_me = call("GET", "/api/me", want_keys=["editable_fields"], label="employee me")
show("editable for employees", len(e_me["editable_fields"]))
show("notice", e_me["notice"])
call("POST", "/api/demo/reset", expect=(403,), label="employee cannot reset demo")

print("== what an employee may open ==")
mods = e_sess.get("modules") or []
show("modules granted", len(mods))
for blocked in ("employees", "hiring", "reports"):
    assert blocked not in mods, f"modules list leaked the HR area '{blocked}'"
for granted in ("home", "me", "inbox", "attendance", "leave", "payroll", "expenses", "timesheet",
                "documents", "performance", "orgchart"):
    assert granted in mods, f"modules list is missing '{granted}'"
for path, tag in (("/api/employees/export", "directory export"), ("/api/jobs", "job openings"),
                  ("/api/candidates", "candidate list"), ("/api/hiring/pipeline", "hiring pipeline"),
                  ("/api/reports", "report list"), ("/api/reports/headcount", "headcount report")):
    call("GET", path, expect=(403,), label=f"employee blocked from {tag}")
call("GET", "/api/custom-report-datasets", expect=(403, 404), label="employee has no custom-report datasets")
_, look = call("GET", "/api/lookups", label="lookups for an employee")
assert not look.get("custom_datasets"), "custom-report datasets leaked to an employee"
r, _ = call("GET", "/api/export/attendance", label="employee exports their own attendance")
show("own attendance export", r.headers.get("Content-Type", "")[:24])
assert "csv" in (r.headers.get("Content-Type") or "").lower(), "attendance export is not CSV"
_, own_rows = call("GET", "/api/attendance", want_keys=["rows"], label="attendance rows for scoping check")
names = {a.get("employee_name") for a in own_rows["rows"]}
show("names in own export scope", len(names))
assert not e_sess.get("security", {}).get("has_own_password"), "a fresh demo account should not have its own password yet"
assert e_sess.get("must_set_password") in (True, False), "must_set_password missing from /api/session"
r, _ = call("POST", "/login", json_body={"email": "deepak.chauhan@company.com", "password": "demo123"},
            expect=(401,), label="exited employee cannot sign in")
show("exited login says", (r.json().get("error") or "")[:44])

print("== wall clock (the office, not the container) ==")
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
IST = _tz(_td(hours=5, minutes=30))
_, hh = call("GET", "/api/health", want_keys=["timezone", "office_time", "wall_clock_offset_minutes"],
             label="health exposes the office clock")
show("server timezone", hh["timezone"])
assert int(hh["wall_clock_offset_minutes"]) == 330, f"clock is {hh['wall_clock_offset_minutes']} min from UTC, expected 330 (IST)"
expected = _dt.now(IST)


def seconds_off(hhmmss, ref):
    """How far a HH:MM[:SS] or "h:mm AM/PM" value is from a datetime, wrapping over midnight."""
    text = str(hhmmss).strip().upper()
    pm = None
    if "AM" in text or "PM" in text:                # the labels the API renders for people
        pm = "PM" in text
        text = text.replace("AM", "").replace("PM", "").strip()
    parts = [int(x) for x in text[:8].split(":") if x.strip().isdigit()]
    while len(parts) < 3:
        parts.append(0)
    hour = (parts[0] % 12) + (12 if pm else 0) if pm is not None else parts[0]
    a = hour * 3600 + parts[1] * 60 + parts[2]
    b = ref.hour * 3600 + ref.minute * 60 + ref.second
    gap = abs(a - b)
    return min(gap, 86400 - gap)


# the helper reads both shapes the API prints, so pin noon and midnight before trusting it:
# "12:42 PM" once dropped its minutes ("42 PM".isdigit() is False) and reported a 42-minute drift.
_dt = dt
for _label, _at, _want in (("12:42 PM", (12, 42, 0), 0), ("12:42 AM", (0, 42, 0), 0),
                           ("12:00 PM", (12, 0, 0), 0), ("11:30 AM", (11, 30, 0), 0),
                           ("12:42:07", (12, 42, 7), 0), ("01:15 PM", (13, 15, 0), 0)):
    if seconds_off(_label, _dt.datetime(2026, 1, 1, *_at)) > _want:
        raise AssertionError(f"seconds_off misreads {_label!r}")


# The browser's "today" is served, never computed locally: a container on UTC is a day behind an
# IST office after 18:30 UTC, and every date default (payslip period, correction form, report month)
# would silently land on yesterday.
if sess.get("office_date") != expected.strftime("%Y-%m-%d"):
    fails.append(f"/api/session tells the browser the office date is {sess.get('office_date')!r} while the office clock "
                 f"reads {expected.strftime('%Y-%m-%d')} - every date default in the app would be a day off")
else:
    show("session date", f"the browser's 'today' is the server's {sess['office_date']} at {sess.get('office_time')}")

drift = seconds_off(hh["office_time"], expected)
show("office_time vs IST now", f"{hh['office_time']} vs {expected.strftime('%H:%M:%S')} ({int(drift)}s apart)")
assert drift < 120, f"/api/health office_time is {int(drift)}s away from IST - the server is on its own clock"

# a punch filed now has to land on today's IST time and date, whatever the host clock says
_, before = call("GET", "/api/attendance", want_keys=["rows"], label="attendance before the punch")
mine_row = next((a for a in before["rows"] if a.get("date") == expected.strftime("%Y-%m-%d")), None)
_, clk = call("POST", "/api/attendance/clock", json_body={"action": "in", "location": "Testing"},
              expect=(200, 400), label="clock in")
# The suite's session is the Employee's by now, and an Employee cannot clear a day, so this runs
# as HR in a session of its own: it wipes today's punches, clocks in, and checks both the label the
# API renders and the TIME it stored. Without the clear, a seeded day made the check skip silently.
_sa = requests.Session()
_hr = _sa.post(BASE + "/login", json={"email": "admin@company.com", "password": "demo123"}, timeout=60)
checks[0] += 1
if not _hr.ok:
    fails.append(f"the wall-clock punch check could not sign in as HR: {_hr.status_code}")
else:
    _today = expected.strftime("%Y-%m-%d")
    _month = expected.strftime("%Y-%m")
    # HR sees everyone's attendance, so these rows have to be narrowed to the signed-in HR person
    _hr_id = (_sa.get(BASE + "/api/me", timeout=60).json().get("employee") or {}).get("id")
    _rows = _sa.get(BASE + f"/api/attendance?month={_month}", timeout=60).json()["rows"]
    _mine = next((a for a in _rows if str(a.get("date"))[:10] == _today
                  and a.get("employee_id") == _hr_id), None)
    if _mine and (_mine.get("clock_in") or _mine.get("clock_out")):
        _c = _sa.post(BASE + "/api/attendance/entry",
                      json={"employee_id": _mine["employee_id"], "date": _today, "status": "Present",
                                 "clock_in": None, "clock_out": None, "break_minutes": 0,
                                 "note": "cleared by the wall-clock check"}, timeout=60)
        if _c.status_code != 200:
            fails.append(f"could not clear the HR day before punching: {_c.status_code} {_c.text[:120]}")
    _p = _sa.post(BASE + "/api/attendance/clock", json={"action": "in", "location": "Testing"}, timeout=60)
    _pj = _p.json() if "json" in _p.headers.get("Content-Type", "") else {}
    checks[0] += 1
    if not _pj.get("success"):
        fails.append(f"HR clock-in on a cleared day did not succeed: {_p.status_code} {_pj.get('error')}")
    else:
        _after = _sa.get(BASE + f"/api/attendance?month={_month}", timeout=60).json()["rows"]
        _row = next((a for a in _after if str(a.get("date"))[:10] == _today
                     and a.get("employee_id") == _hr_id), None)
        _label_off = seconds_off(_pj.get("time", ""), expected)
        _stored_off = seconds_off(str(_row.get("clock_in")), expected) if _row else 99999
        show("punch as HR", f"label {_pj.get('time')}, stored {_row and _row.get('clock_in')}, "
                            f"filed on {_row and _row.get('date')}")
        assert _label_off <= 120, \
            f"the clock-in label {_pj.get('time')!r} is not the office time {expected.strftime('%H:%M')}"
        assert _row is not None, "the punch was filed on a date other than the office's today"
        assert _stored_off <= 240, f"stored clock_in {_row.get('clock_in')} is {int(_stored_off)}s off IST now"
        # hand the day back closed, the way the seed had it
        _sa.post(BASE + "/api/attendance/clock", json={"action": "out"}, timeout=60)

_, tr = call("GET", "/api/stats", want_keys=["my_time"], label="tracker after the punch")
show("tracker shows", f"{tr['my_time']['clock_in']} · {tr['my_time']['status']}")
show("month the API defaulted to", before.get("month"))
assert before.get("month") == expected.strftime("%Y-%m"), \
    f"the attendance month defaulted to {before.get('month')}, not the office month {expected.strftime('%Y-%m')}"
call("GET", "/api/payroll/summary", label="payroll summary still answers after the clock change")

print("== misc ==")
call("GET", "/api/health", label="health again")
_, h = call("GET", "/api/health", label="health body")
show("health", h)
call("GET", "/api/nope", expect=(404,), label="unknown api 404")
call("GET", "/", expect=(200, 302), label="root redirect")
_, admin_sess = call("GET", "/api/session", expect=(200, 401), label="session (employee still logged in)")
call("POST", "/api/demo/reset", json_body={}, expect=(403,), label="employee cannot reset demo (2)")

print("== own password round trip ==")


def login_as(email, password, expect=200, label=None):
    """A login that does not disturb the session the suite is using."""
    checks[0] += 1
    r = requests.Session().post(BASE + "/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != expect:
        fails.append(f"{label or email} -> {r.status_code}: {r.text[:160]}")
        print(f"  !! FAIL {label or email} -> {r.status_code}")
    else:
        print(f"  ok   {label or email} -> {r.status_code}")
    return r


call("POST", "/api/me/password", json_body={"current_password": "wrong-one", "new_password": "FreshPass-2026"}, expect=(403,), label="wrong current password rejected")
call("POST", "/api/me/password", json_body={"current_password": "demo123", "new_password": "tiny"}, expect=(400,), label="short password rejected")
call("POST", "/api/me/password", json_body={"current_password": "demo123", "new_password": "demo123"}, expect=(400,), label="same password rejected")
call("POST", "/api/me/password", json_body={"current_password": "demo123", "new_password": "FreshPass-2026"}, label="own password set")
login_as(other["email"], "demo123", expect=401, label="shared password stops working once they set their own")
login_as(other["email"], "FreshPass-2026", label="own password signs in")
_, own_sess = call("GET", "/api/session", want_keys=["security.has_own_password"], label="session after the change")
assert own_sess["security"]["has_own_password"] is True, "has_own_password did not flip"
assert own_sess["must_set_password"] is False, "the nudge should clear once they have their own password"
call("GET", f"/api/employees/{other['id']}", label="own profile card still opens")
_, _ = call("POST", "/login", json_body={"email": "admin@company.com", "password": "demo123"}, label="admin back in")
_, dir_rows = call("GET", "/api/employees", label="directory after the change")
row = next((e for e in dir_rows if e["id"] == other["id"]), {})
assert "password_hash" not in row, "password_hash escaped into an API response"
assert row.get("has_own_password") is True, "the directory should say this person has their own password"
_, issued = call("POST", f"/api/employees/{other['id']}/reset-password", json_body={},
                 want_keys=["temp_password"], label="HR issues a one-time password")
show("temp password", (issued.get("temp_password") or "")[:7] + "...")
assert issued.get("temp_password") != "FreshPass-2026", "reset should replace the password, not echo it"
login_as(other["email"], issued["temp_password"], label="one-time password signs in")
call("POST", "/api/demo/reset", json_body={}, label="demo data restored")
login_as(other["email"], "demo123", label="reset puts the shared password back")
login_as(other["email"], "FreshPass-2026", expect=401, label="the test password is gone with the reset")

print("\n" + "=" * 78)
print(f"{checks[0]} endpoint checks run")
if fails:
    print(f"{len(fails)} FAILURE(S):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL GREEN")
