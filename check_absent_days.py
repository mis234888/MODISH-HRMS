"""The register has no holes: every past working day has an answer on file.

Guards the fix that made an unpunched day read `Absent` instead of vanishing (22/09/2026 was simply
missing from every screen). Read-only against a real database: the joiner / fill-the-gap steps run
only when the server reports `mock_mode`, so pointing this at production never writes a row.

Usage:  BASE=http://127.0.0.1:5001 python check_absent_days.py
"""
import datetime as dt
import os
import uuid

import requests

BASE = os.environ.get("BASE", "http://127.0.0.1:5000")
s = requests.Session()
health = s.get(f"{BASE}/api/health", timeout=30).json()
mock = bool(health.get("mock_mode"))
print(f"{BASE}  mode={'mock' if mock else 'supabase'}  office={health.get('office_time')}")
print("login:", s.post(f"{BASE}/login", json={"email": "admin@company.com", "password": "demo123"}).status_code)

me = s.get(f"{BASE}/api/me").json()
EMP = os.environ.get("EMP_ID") or me["employee"]["id"]
today = health["timestamp"][:10]
month = s.get(f"{BASE}/api/attendance", params={"employee_id": EMP}).json()
ym = month["month"]
first, last = dt.date.fromisoformat(month["from_date"]), dt.date.fromisoformat(month["to_date"])
holidays = {str(h.get("date"))[:10] for h in s.get(f"{BASE}/api/holidays").json()}
workdays = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)
            if (first + dt.timedelta(days=i)).weekday() < 5
            and (first + dt.timedelta(days=i)).isoformat() not in holidays]
past = [d.isoformat() for d in workdays if d.isoformat() < today]
rows = month["rows"]
row_dates = {str(r["date"])[:10] for r in rows}

# 1. THE invariant: for the signed-in person every past working day answers - a punch or Absent
missing = [d for d in past if d not in row_dates]
print(f"past working days in {ym}: {len(past)} | days with an answer: {len(past) - len(missing)}")
assert not missing, f"{len(missing)} past working day(s) with nothing on file: {missing}"

# 2. an answer that says Absent must be a real absence: working day, already behind us, not a weekend
absent = [r for r in rows if r["status"] == "Absent"]
if not absent:                # the seeded demo employee punched every working day: widen to the company
    absent = [r for r in s.get(f"{BASE}/api/attendance", params={"month": ym}).json()["rows"]
              if r["status"] == "Absent"]
print("absent days:", sorted(str(r["date"])[:10] for r in absent),
      "| synthetic:", len([r for r in absent if r.get("synthetic")]))
assert absent, "nothing is absent at all - the register is not answering"
# the rules bind the rows the register invents; a real row is whatever HR or the seed put on file
synthetic = [r for r in absent if r.get("synthetic")]
assert all(str(r["date"]) < today for r in synthetic), "a synthetic row was invented for a day that is not over"
assert all(dt.date.fromisoformat(str(r["date"])[:10]).weekday() < 5 for r in synthetic), "a weekend was marked absent"
assert all(str(r["date"])[:10] not in holidays for r in synthetic), "a holiday was marked absent"

# 3. the summary, the calendar and the list agree, and the open days add up
summ = s.get(f"{BASE}/api/attendance/summary", params={"month": ym, "employee_id": EMP}).json()
listed = len([r for r in rows if r["status"] == "Absent"])
assert summ["absent"] == listed, f"summary says {summ['absent']} absent, the list shows {listed}"
for r in absent[:5]:                       # the calendar is drawn per person, so ask per person
    per = s.get(f"{BASE}/api/attendance/summary", params={"month": ym, "employee_id": r["employee_id"]}).json()
    assert per["calendar"].get(str(r["date"])[:10]) == "Absent", f"the calendar forgot {r['date']}"
open_days = [d for d in workdays if d.isoformat() not in row_dates]
assert summ["pending_days"] == len(open_days), f"summary says {summ['pending_days']} open, the register has {len(open_days)}"
print(f"summary: absent={summ['absent']} working_days={summ['working_days']} marked={summ['days_marked']} open={summ['pending_days']}")

# 4. a from/to window clips to the window and never doubles a day
win = s.get(f"{BASE}/api/attendance", params={"from": f"{ym}-01", "to": f"{ym}-02", "employee_id": EMP}).json()
assert all(win["from_date"] <= str(x["date"])[:10] <= win["to_date"] for x in win["rows"]), "row outside the window"
keys = [(x["employee_id"], str(x["date"])[:10]) for x in win["rows"]]
assert len(keys) == len(set(keys)), "a day came back twice for the same person"

if not mock:
    print("\nmock_mode is off - the write steps (a new joiner, filling a gap) were skipped on purpose")
else:
    # 5. a mid-month joiner is answered for from the joining date, and never before it
    join = f"{ym}-15"
    made = s.post(f"{BASE}/api/employees", json={"full_name": "Gap Tester", "department_id": 2, "designation_id": 2,
                                                 "date_of_joining": join, "salary_ctc": 900000,
                                                 "email": f"gap.tester.{uuid.uuid4().hex[:6]}@company.com"})
    new_id = made.json()["employee"]["id"]
    new_rows = s.get(f"{BASE}/api/attendance", params={"month": ym, "employee_id": new_id}).json()["rows"]
    new_absent = sorted(str(r["date"])[:10] for r in new_rows if r["status"] == "Absent")
    print("new joiner on", join, "->", new_absent)
    assert new_rows and all(r.get("synthetic") for r in new_rows), "a new joiner has no answerable days"
    assert new_absent and all(d >= join for d in new_absent), "marked absent before the joining date"
    assert all(d < today for d in new_absent), "marked absent on a day that is not over"
    new_summ = s.get(f"{BASE}/api/attendance/summary", params={"month": ym, "employee_id": new_id}).json()
    assert new_summ["absent"] == len(new_absent), "the summary disagrees with the register for the joiner"

    # 6. filing a punch turns that day from Absent into Present, and the calendar follows
    day = new_absent[0]
    assert s.post(f"{BASE}/api/attendance/entry", json={"employee_id": new_id, "date": day, "status": "Present",
                                                        "clock_in": "09:40", "clock_out": "18:30",
                                                        "break_minutes": 45}).status_code == 200
    after = next(r for r in s.get(f"{BASE}/api/attendance", params={"month": ym, "employee_id": new_id}).json()["rows"]
                 if str(r["date"])[:10] == day)
    assert after["status"] == "Present" and not after.get("synthetic"), "the punch did not replace the absence"
    assert s.get(f"{BASE}/api/attendance/summary", params={"month": ym,
                                                          "employee_id": new_id}).json()["calendar"].get(day) == "Present"
    print("filled", day, "->", after["status"], after["clock_in_label"], "->", after["clock_out_label"])

    # 7. and the days they never punched cost pay: run payroll for the joiner and read the slip
    st = s.post(f"{BASE}/api/payroll/structures", json={"employee_id": new_id, "name": "Absence check FY27",
                                                        "basic": 40000, "hra": 8000, "special_allowance": 2000,
                                                        "pf": 4800, "esi": 0, "professional_tax": 200, "tds": 2000,
                                                        "effective_from": f"{ym}-01"})
    assert st.status_code == 200, f"the structure was refused: {st.text[:200]}"
    s.post(f"{BASE}/api/payroll/run", json={"period": ym, "employee_ids": [new_id], "publish": True})
    slip = next(x for x in s.get(f"{BASE}/api/payslips", params={"period": ym}).json()
                if str(x["employee_id"]) == str(new_id))
    detail = s.get(f"{BASE}/api/payslips/{slip['id']}/detail")
    det = detail.json()
    assert detail.status_code == 200, f"the slip would not open: {detail.status_code} {det}"
    pay_days = det["days"]
    want_lop = len(new_absent) - 1                      # step 6 punched the first of those days
    want_working = len([d for d in workdays if join <= d.isoformat() <= today])
    print(f"payslip: working={pay_days['working_days']:g} payable={pay_days['payable_days']:g} "
          f"lop={pay_days['lop_days']:g} net={det['net']:,.0f}")
    assert pay_days["lop_days"] == want_lop, f"the slip docked {pay_days['lop_days']} days, expected {want_lop}"
    assert pay_days["working_days"] == want_working, f"working days {pay_days['working_days']} != {want_working}"
    assert pay_days["payable_days"] == want_working - want_lop, f"payable days do not add up: {pay_days}"
    assert abs(det["gross"] - det["deductions_total"] - det["net"]) < 0.01, "gross - deductions != net"
    assert any("Loss of Pay" in l["label"] for l in det["deductions"]), "no Loss of Pay line on the slip"

    try:                                                # the throwaway employee goes with its slip
        s.delete(f"{BASE}/api/employees/{new_id}")
    except requests.RequestException as exc:
        print("cleanup note:", exc)

print("\nABSENT-DAY CHECKS PASSED")
