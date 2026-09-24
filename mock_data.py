"""
Ekkaa HRMS - deterministic demo data store.

Only used when the app runs in mock mode (no Supabase configured or USE_MOCK_DATA=true).
Every table mirrors a table in supabase_schema.sql so the same routes work in both modes.
"""
import random
from datetime import date, datetime, timedelta

from clock import today as office_today        # the office wall clock, not the container's

MOCK_VERSION = 14          # bump when the shape of the demo data changes
TODAY = office_today()     # seeded "today" must match the app's today() or Home shows an empty day
RNG = random.Random(20260903)

WORKING_STATUS = ("Present", "Work From Home", "Half Day")


def month_working_days(year, month, holiday_dates=()):
    """Mon-Fri days in a month minus gazetted holidays - payroll's divisor, and the same rule
    `app.payroll_days` uses, so a seeded slip and a re-run of payroll agree."""
    d, out, last = date(year, month, 1), 0, last_day_of_month(year, month)   # last is an ISO string
    while _iso_day(d) <= last:
        if d.weekday() < 5 and _iso_day(d) not in holiday_dates:
            out += 1
        d += timedelta(days=1)
    return out


def last_day_of_month(year, month):
    nxt = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    return _iso_day(nxt - timedelta(days=1))


def _iso_day(d):
    return d.isoformat()


def _stamp(d, h, m):
    """TIME-of-day string for a punch on day `d` (attendance.clock_in is a `time` column)."""
    return f"{h:02d}:{m:02d}:00"


def _uid(prefix, n):
    return f"{prefix}{n:04d}"


# ----------------------------------------------------------------------------- people
_DEPARTMENTS = [
    ("Executive",       "Leadership and strategy"),
    ("Engineering",     "Product and platform engineering"),
    ("Design",          "Product design and research"),
    ("Human Resources", "People ops, hiring and engagement"),
    ("Sales",           "Revenue, partnerships and customer growth"),
    ("Marketing",       "Brand, content and demand generation"),
    ("Finance",         "Accounts, payroll and compliance"),
    ("Operations",      "Admin, IT and facilities"),
]

# code, name, designation, department, manager code, location, status, ctc, dob, doj, gender, phone
_EMPLOYEES = [
    ("EKKA001", "Vikram Singh",   "Founder & CEO",           "Executive",       None,      "Gurgaon",   "Active",    6200000, "1985-04-11", "2018-07-01", "Male",   "+91 98100 11001"),
    ("EKKA002", "Priya Nair",     "CTO",                     "Executive",       "EKKA001", "Bangalore", "Active",    4400000, "1988-11-02", "2019-02-11", "Female", "+91 98100 11002"),
    ("EKKA003", "Ananya Gupta",   "Head of People",          "Human Resources", "EKKA001", "Bangalore", "Active",    3100000, "1989-06-24", "2020-01-06", "Female", "+91 98100 11003"),
    ("EKKA004", "Arjun Rao",      "CFO",                     "Finance",         "EKKA001", "Mumbai",    "Active",    3800000, "1983-01-30", "2019-08-19", "Male",   "+91 98100 11004"),
    ("EKKA005", "Rahul Verma",    "Head of Sales",           "Sales",           "EKKA001", "Delhi",     "Active",    2900000, "1987-09-15", "2020-03-02", "Male",   "+91 98100 11005"),
    ("EKKA006", "Neha Kulkarni",  "Head of Design",          "Design",          "EKKA001", "Pune",      "Active",    2700000, "1990-03-08", "2020-06-15", "Female", "+91 98100 11006"),
    ("EKKA007", "Kavya Menon",    "Head of Marketing",       "Marketing",       "EKKA001", "Bangalore", "Active",    2600000, "1991-12-19", "2021-01-11", "Female", "+91 98100 11007"),
    ("EKKA008", "Karan Malhotra", "Engineering Manager",     "Engineering",     "EKKA002", "Bangalore", "Active",    3300000, "1990-07-21", "2021-02-01", "Male",   "+91 98100 11008"),
    ("EKKA009", "Aarav Sharma",   "Senior Software Engineer", "Engineering",    "EKKA008", "Bangalore", "Active",    1950000, "1997-09-02", "2022-03-15", "Male",   "+91 98765 43210"),
    ("EKKA010", "Kabir Khan",     "DevOps Engineer",         "Engineering",     "EKKA008", "Remote",    "Active",    1700000, "1993-12-10", "2023-02-18", "Male",   "+91 98765 43216"),
    ("EKKA011", "Isha Nair",      "Backend Engineer",        "Engineering",     "EKKA008", "Kochi",     "Active",    1500000, "1998-02-14", "2023-05-02", "Female", "+91 98765 43218"),
    ("EKKA012", "Tanvi Joshi",    "QA Engineer",             "Engineering",     "EKKA008", "Pune",      "Active",    1150000, "1999-08-05", "2023-08-14", "Female", "+91 98765 43219"),
    ("EKKA013", "Sneha Reddy",    "Product Designer",        "Design",          "EKKA006", "Hyderabad", "On Leave",  1450000, "1997-07-22", "2022-11-12", "Female", "+91 98765 43215"),
    ("EKKA014", "Manav Shah",     "UX Researcher",           "Design",          "EKKA006", "Ahmedabad", "Active",    1350000, "1996-01-27", "2023-01-09", "Male",   "+91 98765 43220"),
    ("EKKA015", "Rohan Mehta",    "Sales Executive",         "Sales",           "EKKA005", "Mumbai",    "Active",    1200000, "1996-03-15", "2023-06-01", "Male",   "+91 98765 43212"),
    ("EKKA016", "Devika Pillai",  "Sales Executive",         "Sales",           "EKKA005", "Delhi",     "Active",    1150000, "1998-05-16", "2024-02-05", "Female", "+91 98765 43221"),
    ("EKKA017", "Ishita Patel",   "Content Strategist",      "Marketing",       "EKKA007", "Bangalore", "Probation",  980000, "2000-04-18", "2026-07-06", "Female", "+91 98765 43217"),
    ("EKKA018", "Farhan Ali",     "Finance Analyst",         "Finance",         "EKKA004", "Mumbai",    "Active",    1250000, "1995-10-09", "2022-09-01", "Male",   "+91 98765 43222"),
    ("EKKA019", "Suresh Iyer",    "HR Executive",            "Human Resources", "EKKA003", "Bangalore", "Active",     850000, "1994-02-03", "2024-04-15", "Male",   "+91 98765 43223"),
    ("EKKA020", "Nikhil Bose",    "IT Administrator",        "Operations",      "EKKA003", "Bangalore", "Notice Period", 1050000, "1992-06-11", "2021-10-04", "Male", "+91 98765 43224"),
    ("EKKA021", "Deepak Chauhan", "Backend Engineer",        "Engineering",     "EKKA008", "Jaipur",    "Exited",    1400000, "1994-09-30", "2021-06-14", "Male",   "+91 98765 43225"),
]

_LEAVE_TYPES = [
    ("Casual Leave",   "CL",  "#6c5ce7", 12, True),
    ("Sick Leave",     "SL",  "#00b894", 12, True),
    ("Earned Leave",   "EL",  "#0984e3", 18, True),
    ("Work From Home", "WFH", "#fdcb6e", 24, True),
    ("Optional Holiday", "OH", "#e17055", 2, True),
]

_HOLIDAYS = [
    ("New Year",         "2026-01-01", "Public"),
    ("Republic Day",     "2026-01-26", "Public"),
    ("Holi",             "2026-03-03", "Public"),
    ("Good Friday",      "2026-04-03", "Public"),
    ("Labour Day",       "2026-05-01", "Optional"),
    ("Independence Day", "2026-08-15", "Public"),
    ("Gandhi Jayanti",   "2026-10-02", "Public"),
    ("Dussehra",         "2026-10-20", "Public"),
    ("Diwali",           "2026-11-09", "Company"),
    ("Christmas",        "2026-12-25", "Public"),
]


def build_mock_db():
    """Return the fully seeded in-memory database (list of dicts per table)."""
    db = {k: [] for k in (
        "departments", "designations", "employees", "shifts", "attendance", "leave_types",
        "leave_balances", "leave_requests", "holidays", "payroll_structures", "payslips",
        "reimbursements", "jobs", "candidates", "goals", "performance_reviews", "feedbacks",
        "checkins", "announcements", "documents", "document_requests",
        "attendance_regularizations", "projects", "timesheets", "timesheet_entries",
    )}

    # ---------------- departments + designations ----------------
    dept_id = {}
    for i, (name, desc) in enumerate(_DEPARTMENTS, start=1):
        did = _uid("d", i)
        dept_id[name] = did
        db["departments"].append({"id": did, "name": name, "description": desc, "head_id": None})

    desig_id = {}
    for i, (_code, _n, designation, dept, *_rest) in enumerate(_EMPLOYEES, start=1):
        key = (designation, dept)
        if key in desig_id:
            continue
        did = _uid("dg", len(desig_id) + 1)
        desig_id[key] = did
        db["designations"].append({"id": did, "title": designation, "department_id": dept_id[dept], "level": 5 - min(4, i % 5)})

    # ---------------- employees ----------------
    emp_by_code = {}
    for i, (code, name, designation, dept, mgr_code, loc, status, ctc, dob, doj, gender, phone) in enumerate(_EMPLOYEES, start=1):
        eid = _uid("e", i)
        email = f"{name.split()[0].lower()}.{name.split()[-1].lower()}@company.com"
        db["employees"].append({
            "id": eid,
            "employee_code": code,
            "full_name": name,
            "email": email,
            "personal_email": f"{name.split()[0].lower()}{dob[2:4]}@gmail.com",
            "phone": phone,
            "gender": gender,
            "date_of_birth": dob,
            "date_of_joining": doj,
            "department_id": dept_id[dept],
            "designation_id": desig_id[(designation, dept)],
            "manager_id": None,
            "employment_type": "Full-time" if code != "EKKA017" else "Full-time",
            "work_location": loc,
            "status": status,
            "salary_ctc": ctc,
            "avatar": "".join(w[0] for w in name.split())[:2].upper(),
            "blood_group": RNG.choice(["O+", "B+", "A+", "A-", "O-"]),
            "nationality": "Indian",
            "address": RNG.choice([
                "412, Whitefield Road, Bangalore 560066",
                "7/B Sea Fold Apartments, Andheri West, Mumbai 400058",
                "18 Sector 62, Noida 201301",
                "Villa 9, Gachibowli, Hyderabad 500032",
            ]),
            "pan_no": f"ABCDE{1000 + i}F",
            "uan_no": f"1002{30000000 + i}",
            "pf_no": f"BN/BLR/019{400 + i}",
            "bank_name": RNG.choice(["HDFC Bank", "ICICI Bank", "Axis Bank", "SBI"]),
            "bank_account_no": f"5020{20000000 + i * 7}",
            "ifsc_code": RNG.choice(["HDFC0001234", "ICIC0004321", "AXIS0009876", "SBIN0012345"]),
            "emergency_contact_name": RNG.choice(["Anil Sharma", "Meena Nair", "Suresh Rao", "Kavita Verma"]),
            "emergency_contact_phone": f"+91 90000 {10000 + i}",
            "emergency_contact_relation": RNG.choice(["Spouse", "Parent", "Sibling"]),
            "exit_date": None,
            "exit_reason": None,
        })
        emp_by_code[code] = eid
        db["employees"][-1]["_designation"] = designation
        db["employees"][-1]["_department"] = dept
        db["employees"][-1]["_manager_code"] = mgr_code

    for emp in db["employees"]:
        mgr = emp.pop("_manager_code")
        emp["manager_id"] = emp_by_code.get(mgr) if mgr else None
        emp["designation"] = emp.pop("_designation")
        emp["department"] = emp.pop("_department")

    # department heads: senior-most person (shortest path to the CEO) inside the department
    for dept_name, did in dept_id.items():
        members = [e for e in db["employees"] if e["department_id"] == did and e["status"] != "Exited"]
        if not members:
            continue
        head = next((e for e in members if (e["designation"] or "").startswith("Head of")), None)
        head = head or next((e for e in members if e["designation"] in ("CTO", "CFO", "Founder & CEO")), None)
        head = head or members[0]
        db["departments"][int(did[1:]) - 1]["head_id"] = head["id"]

    # ---------------- shifts ----------------
    for i, (nm, st, en, grace) in enumerate([("General Shift", "09:30:00", "18:30:00", 15),
                                              ("Early Shift", "07:00:00", "15:30:00", 10),
                                              ("Late Shift", "12:00:00", "21:00:00", 15)], start=1):
        db["shifts"].append({"id": _uid("s", i), "name": nm, "start_time": st, "end_time": en,
                             "grace_minutes": grace, "start_minutes": _minutes(st), "end_minutes": _minutes(en)})

    # ---------------- leave types + balances ----------------
    lt_id = {}
    for i, (nm, code, color, quota, paid) in enumerate(_LEAVE_TYPES, start=1):
        lid = _uid("lt", i)
        lt_id[code] = lid
        db["leave_types"].append({"id": lid, "name": nm, "code": code, "color": color,
                                  "yearly_quota": quota, "is_paid": paid, "requires_approval": code != "WFH"})
    for emp in db["employees"]:
        if emp["status"] == "Exited":
            continue
        for code, lid in lt_id.items():
            quota = next(t[3] for t in _LEAVE_TYPES if t[1] == code)
            # never seed more used than the quota - the UI would show a negative balance
            used = RNG.randint(0, max(0, quota - 3)) if code in ("CL", "SL", "WFH") else RNG.randint(0, min(3, quota))
            db["leave_balances"].append({"id": _uid("lb", len(db["leave_balances"]) + 1),
                                         "employee_id": emp["id"], "leave_type_id": lid,
                                         "year": TODAY.year, "total": quota, "used": used, "pending": 0})

    # ---------------- holidays ----------------
    for i, (nm, dt, typ) in enumerate(_HOLIDAYS, start=1):
        db["holidays"].append({"id": _uid("h", i), "name": nm, "date": dt, "type": typ})
    holiday_dates = {h["date"] for h in db["holidays"]}

    # ---------------- attendance (last 150 days) ----------------
    active = [e for e in db["employees"] if e["status"] != "Exited"]
    start = TODAY - timedelta(days=150)
    att_n = 0
    for emp in active:
        for offset in range((TODAY - start).days + 1):
            day = start + timedelta(days=offset)
            if day.weekday() == 6 or _iso_day(day) in holiday_dates:
                continue
            att_n += 1
            roll = RNG.random()
            idx = active.index(emp)
            if day == TODAY:
                # "today" is deliberately mid-shift so the Home tracker has something live to show
                if idx % 11 == 7:
                    continue                                     # a few people have not marked in yet
                if idx % 7 == 3:
                    status, ci, co = "Absent", None, None          # a couple of no-shows
                elif idx % 5 == 2:
                    status, ci, co = "Work From Home", RNG.randint(9 * 60 - 10, 9 * 60 + 20), None
                elif idx % 3 == 1:
                    status, ci, co = "Present", RNG.randint(9 * 60 + 35, 9 * 60 + 65), None   # running late
                else:
                    status, ci, co = "Present", RNG.randint(9 * 60 - 25, 9 * 60 + 5), None
                if emp["employee_code"] == "EKKA009":
                    status, ci, co = "Present", 9 * 60 + 25, None   # Aarav - the demo login
            elif roll < 0.90:
                status = "Present"
                ci = RNG.randint(9 * 60 - 40, 9 * 60 + 15)      # in on time, 08:50-09:45
                co = RNG.randint(18 * 60, 20 * 60 + 30)
            elif roll < 0.94:
                status = "Present"
                ci = RNG.randint(9 * 60 + 55, 10 * 60 + 25)     # genuinely late, ~4% of days
                co = RNG.randint(18 * 60 + 30, 20 * 60 + 45)
            elif roll < 0.965:
                status = "Work From Home"
                ci = RNG.randint(9 * 60, 10 * 60)
                co = RNG.randint(17 * 60 + 30, 19 * 60)
            elif roll < 0.978:
                status = "Half Day"
                ci = RNG.randint(9 * 60, 9 * 60 + 40)
                co = ci + 4 * 60 + RNG.randint(0, 40)
            elif roll < 0.99:
                status = "Absent"
                ci = co = None
            else:
                status = "On Leave"
                ci = co = None
            demo_now = 13 * 60 + 40          # the demo day "ends" at 13:40 so open rows have a sensible total
            if day == TODAY and ci is not None and co is None:
                co = demo_now
            hours = 0.0 if ci is None or co is None else round((co - ci - 45) / 60, 1)
            if day == TODAY and co == demo_now:
                co = None                    # still clocked in on the demo day
            db["attendance"].append({
                "id": _uid("a", att_n),
                "employee_id": emp["id"],
                "date": _iso_day(day),
                "clock_in": _stamp(day, ci // 60, ci % 60) if ci is not None else None,
                "clock_out": _stamp(day, co // 60, co % 60) if co is not None else None,
                "work_hours": hours,
                "break_minutes": 45 if ci is not None else 0,
                "status": status,
                "shift_id": "s1",
                "location": emp["work_location"],
                "is_late": bool(ci is not None and ci > 9 * 60 + 45),
                "regularization_status": "None",
                "regularization_reason": None,
            })

    # ---------------- leave requests (past 6 months + upcoming) ----------------
    reasons = ["Personal work", "Family function", "Not feeling well", "Medical appointment",
               "Village trip", "Child's school event", "Home renovation", "Fever and body ache"]
    ln = 0
    for emp in active:
        for _ in range(RNG.randint(2, 5)):
            start_off = RNG.randint(-160, 20)
            s = TODAY + timedelta(days=start_off)
            days = 1 if RNG.random() < 0.6 else RNG.randint(2, 4)
            e = s + timedelta(days=days - 1)
            code = RNG.choice(["CL", "SL", "EL", "WFH", "CL", "SL"])
            if s <= TODAY <= e:
                status = "Approved"
            elif s > TODAY:
                status = RNG.choice(["Approved", "Pending", "Pending"])
            else:
                status = RNG.choice(["Approved", "Approved", "Approved", "Rejected"])
            ln += 1
            db["leave_requests"].append({
                "id": _uid("l", ln),
                "employee_id": emp["id"],
                "leave_type_id": lt_id[code],
                "leave_type": next(t[0] for t in _LEAVE_TYPES if t[1] == code),
                "start_date": _iso_day(s),
                "end_date": _iso_day(e),
                "days": days,
                "half_day": False,
                "reason": RNG.choice(reasons),
                "status": status,
                "approver_id": emp["manager_id"],
                "applied_at": _iso_day(s - timedelta(days=RNG.randint(2, 9))),
                "actioned_at": _iso_day(s - timedelta(days=1)) if status != "Pending" else None,
                "admin_remark": None if status == "Pending" else RNG.choice([None, "Approved as per policy", "Please plan cover with the team"]),
            })

    # Sneha is on planned leave right now (used by the "On Leave" home card)
    on_leave_emp = next((e for e in db["employees"] if e["status"] == "On Leave"), None)
    if on_leave_emp:
        db["leave_requests"].append({
            "id": _uid("l", len(db["leave_requests"]) + 1),
            "employee_id": on_leave_emp["id"], "leave_type_id": lt_id["EL"], "leave_type": "Earned Leave",
            "start_date": _iso_day(TODAY - timedelta(days=1)), "end_date": _iso_day(TODAY + timedelta(days=3)),
            "days": 5, "half_day": False, "reason": "Family function in Hyderabad", "status": "Approved",
            "approver_id": on_leave_emp["manager_id"], "applied_at": _iso_day(TODAY - timedelta(days=12)),
            "actioned_at": _iso_day(TODAY - timedelta(days=10)), "admin_remark": None,
        })

    # ---------------- jobs + candidates ----------------
    jobs = [
        ("Senior Frontend Engineer", "Engineering", "Bangalore", 2, "Open", "React, TypeScript, design systems. Own the customer dashboard.", "5-8 yrs", "₹18-26 LPA", "EKKA008"),
        ("Product Marketing Manager", "Marketing", "Mumbai", 1, "Open", "Own positioning, launches and the demand-gen funnel for the HR product line.", "4-7 yrs", "₹14-20 LPA", "EKKA007"),
        ("HR Intern - Talent Ops", "Human Resources", "Bangalore", 3, "Open", "Support onboarding, engagement surveys and the ATS hygiene drive.", "0-1 yrs", "₹25k /month", "EKKA003"),
        ("Sales Development Rep", "Sales", "Remote", 5, "Open", "Outbound pipeline for mid-market accounts across APAC.", "1-3 yrs", "₹6-10 LPA + incentives", "EKKA005"),
        ("Backend Engineer (Python)", "Engineering", "Pune", 2, "On Hold", "FastAPI + Postgres services for payroll computation.", "2-5 yrs", "₹12-18 LPA", "EKKA008"),
        ("QA Automation Lead", "Engineering", "Bangalore", 1, "Closed", "Playwright suite ownership for the mobile app.", "5-9 yrs", "₹16-22 LPA", "EKKA008"),
    ]
    job_id = {}
    for i, (title, dept, loc, openings, status, desc, exp, ctc, owner_code) in enumerate(jobs, start=1):
        jid = _uid("j", i)
        job_id[jid] = title
        db["jobs"].append({
            "id": jid, "title": title, "department_id": dept_id[dept], "department": dept,
            "location": loc, "openings": openings, "employment_type": "Full-time" if "Intern" not in title else "Internship",
            "experience": exp, "salary_range": ctc, "description": desc, "status": status,
            "hiring_manager_id": emp_by_code.get(owner_code), "applicants": 0,
            "posted_at": _iso_day(TODAY - timedelta(days=RNG.randint(12, 70))),
            "closed_at": _iso_day(TODAY - timedelta(days=6)) if status == "Closed" else None,
            "closure_reason": "Position filled - offer accepted by the internal candidate." if status == "Closed" else None,
        })
    cand_names = [
        ("Aditya Verma", "5 yrs", "Interview", 4), ("Neha Singh", "3 yrs", "Screening", 3),
        ("Rahul Bose", "6 yrs", "Offer", 5), ("Pooja Nair", "2 yrs", "Applied", 0),
        ("Sameer Khan", "7 yrs", "Interview", 4), ("Trisha Roy", "4 yrs", "Screening", 2),
        ("Varun Kapoor", "8 yrs", "Hired", 5), ("Ananya Iyer", "1 yrs", "Applied", 0),
        ("Gaurav Sinha", "5 yrs", "Rejected", 2), ("Riya Shah", "3 yrs", "Offer", 4),
        ("Mohit Arora", "6 yrs", "Interview", 3), ("Divya Nambiar", "2 yrs", "Applied", 0),
        ("Karthik Rao", "9 yrs", "Screening", 4), ("Sana Sheikh", "1 yrs", "Applied", 0),
    ]
    open_jobs = [j["id"] for j in db["jobs"] if j["status"] != "Closed"]
    for i, (nm, exp, stage, rating) in enumerate(cand_names, start=1):
        jid = RNG.choice(open_jobs)
        db["candidates"].append({
            "id": _uid("c", i), "job_id": jid, "full_name": nm,
            "email": f"{nm.split()[0].lower()}{i}@example.com", "phone": f"+91 90000 {50000 + i}",
            "experience": exp, "experience_years": int(exp.split()[0]), "current_ctc": RNG.randint(6, 24) * 100000,
            "expected_ctc": RNG.randint(8, 32) * 100000, "stage": stage, "rating": rating,
            "source": RNG.choice(["Careers page", "Referral", "LinkedIn", "Naukri"]),
            "owner_id": next(j["hiring_manager_id"] for j in db["jobs"] if j["id"] == jid),
            "resume_url": None, "notes": RNG.choice([None, "Strong communication. Schedule tech round 2.", "Notice period 60 days.", "Internal referral by Priya."]),
            "applied_at": _iso_day(TODAY - timedelta(days=RNG.randint(3, 45))),
            "converted_employee_id": None,
        })

    # ---------------- payroll ----------------
    pn = 0
    att_by_emp = {}
    for a in db["attendance"]:
        att_by_emp.setdefault(str(a["employee_id"]), []).append(a)
    for i, emp in enumerate([e for e in db["employees"] if e["status"] != "Exited"]):
        monthly = round(emp["salary_ctc"] / 12, 2)
        basic = round(monthly * 0.40)
        extras = {"Travel": 2500, "Learning": 1000} if i % 3 == 0 else ({"Internet": 1200} if i % 3 == 1 else {})
        # components are solved from the CTC instead of rounded off it, and the employer's own PF is
        # part of CTC but not of gross - so the seed reconciles exactly the way the app computes it,
        # and nobody opens a structure that reports a ₹93,600 difference against itself.
        employer_pf = round(basic * 0.12)
        gross = round(monthly - employer_pf, 2)
        special = round(gross - basic - round(monthly * 0.20) - sum(extras.values()), 2)
        db["payroll_structures"].append({
            "id": _uid("ps", len(db["payroll_structures"]) + 1), "employee_id": emp["id"],
            "name": "Standard FY26-27",
            "basic": basic, "hra": round(monthly * 0.20), "special_allowance": special,
            "allowances": extras,
            "pf": round(basic * 0.12), "esi": 0 if monthly > 21000 else 75, "professional_tax": 200,
            "tds": round(monthly * 0.05), "employer_pf": employer_pf,
            "ctc": emp["salary_ctc"], "effective_from": emp["date_of_joining"],
        })
    for m in range(TODAY.month - 4, TODAY.month + 1):
        month = (m - 1) % 12 + 1
        working = month_working_days(TODAY.year, month, holiday_dates)
        for idx, emp in enumerate([e for e in db["employees"] if e["status"] != "Exited"]):
            ps = next(p for p in db["payroll_structures"] if p["employee_id"] == emp["id"])
            # the same gross the app would compute: components + the structure's own allowances
            gross = ps["basic"] + ps["hra"] + ps["special_allowance"] + sum((ps.get("allowances") or {}).values())
            # loss of pay straight out of the seeded attendance, so a slip and a payroll re-run agree
            lop = sum(0.5 if a["status"] == "Half Day" else 1.0
                      for a in att_by_emp.get(str(emp["id"]), [])
                      if str(a["date"])[:7] == f"{TODAY.year:04d}-{month:02d}"
                      and a["status"] in ("Absent", "Half Day"))
            lop = min(round(lop, 2), working)
            payable = round(working - lop, 2) or working
            lwp = round(gross / max(working, 1) * lop, 2) if lop else 0.0
            bonus = round(monthly * 0.10) if month in (TODAY.month - 1, 12) and idx % 4 == 0 else 0
            ded = ps["pf"] + ps["esi"] + ps["professional_tax"] + ps["tds"] + lwp
            pn += 1
            # the current month is where the process is still open: two slips sit in Draft on purpose,
            # so the "employees never see an unreleased payslip" rule has something real to demonstrate
            status = ("Draft" if month == TODAY.month and idx < 2
                      else "Paid" if month < TODAY.month else "Published")
            db["payslips"].append({
                "id": _uid("p", pn), "employee_id": emp["id"], "month": month, "year": TODAY.year,
                "period": f"{TODAY.year:04d}-{month:02d}",
                "gross_earnings": round(gross + bonus, 2), "total_deductions": round(ded, 2),
                "net_pay": round(gross + bonus - ded, 2),
                "bonus": bonus, "deductions": 0, "lop_days": lop, "payable_days": payable,
                "working_days": working, "status": status, "payslip_url": None,
                "generated_by": "hr@company.com", "notes": None,
                "generated_at": _iso_day(date(TODAY.year, month, 28)),
                "published_at": _iso_day(date(TODAY.year, month, 28)) if status != "Draft" else None,
                "paid_on": (last_day_of_month(TODAY.year, month) if status == "Paid" else None),
            })

    # ---------------- reimbursements ----------------
    exp_rows = [
        ("EKKA009", "Travel", 4500, "Client visit - Mumbai", "Approved", 12),
        ("EKKA013", "Medical", 2200, "Dental consultation", "Pending", 2),
        ("EKKA010", "Internet", 1200, "Monthly broadband reimbursement", "Pending", 5),
        ("EKKA015", "Food", 800, "Client lunch", "Approved", 8),
        ("EKKA011", "Office Supplies", 1450, "Mechanical keyboard", "Rejected", 20),
        ("EKKA018", "Travel", 6100, "Audit visit - Hyderabad", "Paid", 30),
        ("EKKA017", "Learning", 3200, "Content marketing course", "Pending", 1),
        ("EKKA016", "Food", 640, "Team dinner", "Approved", 4),
    ]
    for i, (code, cat, amt, desc, status, ago) in enumerate(exp_rows, start=1):
        db["reimbursements"].append({
            "id": _uid("r", i), "employee_id": emp_by_code[code], "category": cat, "amount": amt,
            "date": _iso_day(TODAY - timedelta(days=ago)), "description": desc, "receipt_url": None,
            "status": status, "reviewer_remark": None if status == "Pending" else "Verified against policy",
            "created_at": _iso_day(TODAY - timedelta(days=ago)),
        })

    # ---------------- announcements ----------------
    ann = [
        ("🎉 Independence Day Celebration", "Join us on 15th Aug at 4 PM in the Cafeteria for flag hoisting and sweets distribution.", "Event", 12, True),
        ("New Leave Policy Update", "WFH quota increased from 12 to 24 days per year effective Sep 1st. Check HR portal for details.", "Policy", 5, True),
        ("Welcome New Joiners - September", "Please welcome 3 new members who joined us this month across Engineering and Sales.", "General", 1, True),
        ("Q2 All-Hands on Friday", "Town hall at 3 PM IST in the Auditorium and on Zoom. Agenda: revenue, product roadmap, hiring plan.", "Event", 3, False),
        ("Health Insurance Enrolment Closes 20th", "Submit your family details in the Documents section before 20 Sep to be covered in the FY renewal.", "Urgent", 2, False),
    ]
    for i, (title, content, typ, ago, pinned) in enumerate(ann, start=1):
        db["announcements"].append({"id": _uid("an", i), "title": title, "content": content, "type": typ,
                                    "date": _iso_day(TODAY - timedelta(days=ago)), "is_pinned": pinned,
                                    "created_by": emp_by_code["EKKA003"]})

    # ---------------- documents ----------------
    doc_types = ["PAN Card", "Aadhaar Card", "Educational Certificate", "Experience Letter",
                 "Offer Letter", "Appointment Letter", "Cancelled Cheque", "Photo ID", "NDA", "Tax Declaration"]
    dn = 0
    for emp in db["employees"]:
        if emp["status"] == "Exited":
            continue
        for typ in RNG.sample(doc_types, RNG.randint(2, 5)):
            dn += 1
            status = RNG.choice(["Verified", "Verified", "Pending", "Verified"])
            db["documents"].append({
                "id": _uid("doc", dn), "employee_id": emp["id"], "title": f"{typ} - {emp['full_name'].split()[0]}",
                "doc_type": typ, "purpose": RNG.choice(["Statutory / compliance record", "Onboarding file", "Payroll & bank verification", "Tax filing"]),
                "file_name": f"{typ.lower().replace(' ', '_')}.pdf", "file_path": None, "file_size": RNG.randint(80, 900) * 1024,
                "mime_type": "application/pdf", "description": None, "uploaded_by": emp["id"],
                "uploaded_at": _iso_day(TODAY - timedelta(days=RNG.randint(3, 400))),
                "valid_from": None, "valid_till": _iso_day(TODAY + timedelta(days=RNG.randint(30, 900))) if typ in ("PAN Card", "Aadhaar Card", "Photo ID") else None,
                "visibility": RNG.choice(["Employee & HR", "HR only", "Employee & HR"]),
                "status": status, "reviewer_id": emp_by_code["EKKA019"] if status == "Verified" else None,
                "reviewed_at": _iso_day(TODAY - timedelta(days=RNG.randint(1, 40))) if status == "Verified" else None,
                "reviewer_remark": None,
            })
    for i, (code, typ, due_in) in enumerate([("EKKA017", "Experience Letter", 3), ("EKKA016", "Cancelled Cheque", 5),
                                              ("EKKA011", "Tax Declaration", -2), ("EKKA012", "NDA", 7)], start=1):
        db["document_requests"].append({
            "id": _uid("dr", i), "employee_id": emp_by_code[code], "doc_type": typ,
            "reason": RNG.choice(["Mandatory for the onboarding file", "Required for FY tax filing", "Legal team needs a signed copy", "Payroll needs bank proof for the next run"]),
            "due_date": _iso_day(TODAY + timedelta(days=due_in)), "requested_by": emp_by_code["EKKA003"],
            "status": "Pending", "created_at": _iso_day(TODAY - timedelta(days=2)), "fulfilled_document_id": None,
        })

    # ---------------- attendance regularizations ----------------
    for i, (code, off, typ, status) in enumerate([("EKKA009", 3, "Missing punch-out", "Pending"), ("EKKA011", 6, "Missing punch-in", "Pending"),
                                                   ("EKKA015", 9, "On duty / field visit", "Approved"), ("EKKA012", 12, "Late arrival", "Rejected"),
                                                   ("EKKA010", 15, "Work from home", "Approved")], start=1):
        day = TODAY - timedelta(days=off)
        db["attendance_regularizations"].append({
            "id": _uid("reg", i), "employee_id": emp_by_code[code], "date": _iso_day(day), "request_type": typ,
            "clock_in_correction": None, "clock_out_correction": None,
            "reason": RNG.choice(["Biometric device was down, punched on the register.", "Left early for a client call and forgot to punch out.",
                                  "Client site visit - no office punch available.", "Traffic due to marquee, reported late."]),
            "status": status, "requested_at": _iso_day(day + timedelta(days=1)),
            "reviewer_id": None if status == "Pending" else emp_by_code["EKKA019"],
            "reviewed_at": None if status == "Pending" else _iso_day(day + timedelta(days=2)),
            "reviewer_remark": None if status == "Pending" else ("OK as per manager email" if status == "Approved" else "Attach manager approval mail"),
        })
        for att in db["attendance"]:
            if att["employee_id"] == emp_by_code[code] and att["date"] == _iso_day(day):
                att["regularization_status"] = status
                att["regularization_reason"] = "Approved - hours corrected" if status == "Approved" else None

    # ---------------- performance: goals, reviews, feedback, check-ins ----------------
    goal_titles = [
        ("Launch Payroll Module v2", 75, "In Progress", "Product"),
        ("Reduce API p95 latency by 30%", 40, "In Progress", "Engineering"),
        ("Zero critical bugs in release trains", 65, "In Progress", "Quality"),
        ("Mentor 2 junior engineers to promotion", 50, "In Progress", "People"),
        ("Improve onboarding NPS to 60", 80, "In Progress", "People"),
        ("Hire 5 engineers for the backend team", 100, "Completed", "Hiring"),
        ("Cut cost-of-payroll-run by 20%", 25, "At Risk", "Finance"),
        ("Ship mobile app 2.0", 15, "Not Started", "Product"),
        ("Automate attendance exceptions", 55, "In Progress", "Operations"),
        ("Grow pipeline by 40%", 70, "In Progress", "Revenue"),
    ]
    for i, (title, progress, status, cat) in enumerate(goal_titles, start=1):
        owner = active[(i * 3) % len(active)]
        db["goals"].append({"id": _uid("g", i), "employee_id": owner["id"], "title": title,
                            "description": "Tracked weekly in the 1:1 with the reporting manager.", "category": cat,
                            "metric": RNG.choice(["% complete", "count", "score"]), "target": "100%",
                            "progress": progress, "status": status,
                            "due_date": _iso_day(TODAY + timedelta(days=RNG.randint(-10, 120))),
                            "created_at": _iso_day(TODAY - timedelta(days=RNG.randint(20, 120)))})
    cycles = [("Q1 FY26", "2026-04-01", "2026-06-30", "Completed"), ("Q2 FY26", "2026-07-01", "2026-09-30", "In Review")]
    rn = 0
    for emp in active[:14]:
        for cyc, s, e, st in cycles:
            rn += 1
            mgr_rating = round(RNG.uniform(2.8, 4.9), 1) if st == "Completed" else 0
            db["performance_reviews"].append({
                "id": _uid("pr", rn), "employee_id": emp["id"], "reviewer_id": emp["manager_id"] or emp_by_code["EKKA002"],
                "period": cyc, "cycle_start": s, "cycle_end": e, "due_date": _iso_day(TODAY + timedelta(days=RNG.randint(-20, 25))),
                "self_rating": round(RNG.uniform(3.0, 5.0), 1) if st == "Completed" else 0,
                "manager_rating": mgr_rating, "final_rating": mgr_rating,
                "potential": RNG.choice(["High", "Medium", "Low"]) if st == "Completed" else None,
                "strengths": "Ownership, quality of delivery and documentation." if st == "Completed" else None,
                "improvements": "Needs to delegate more and improve estimation accuracy." if st == "Completed" else None,
                "comments": None, "status": st,
                "competencies": {"Technical": round(RNG.uniform(2.5, 5), 1), "Communication": round(RNG.uniform(2.5, 5), 1),
                                 "Collaboration": round(RNG.uniform(2.5, 5), 1), "Ownership": round(RNG.uniform(2.5, 5), 1)} if st == "Completed" else None,
            })
    fb = [("EKKA002", "EKKA009", "Great work on the performance module launch!", "#teamwork,#ownership"),
          ("EKKA003", "EKKA019", "Onboarding surveys are now back on time every week.", "#reliability"),
          ("EKKA008", "EKKA011", "Your API refactor cut our p95 by 22%. Brilliant.", "#impact,#quality"),
          ("EKKA006", "EKKA013", "Design QA checklist saved us a release. Thank you!", "#initiative"),
          ("EKKA005", "EKKA015", "Kept 3 renewal accounts warm during my leave.", "#customer")]
    for i, (fromc, toc, msg, tags) in enumerate(fb, start=1):
        fb_day = _iso_day(TODAY - timedelta(days=RNG.randint(1, 25)))
        db["feedbacks"].append({"id": _uid("fb", i), "from_employee_id": emp_by_code[fromc], "to_employee_id": emp_by_code[toc],
                                "message": msg, "tags": tags, "category": RNG.choice(["Appreciation", "Constructive", "Peer"]),
                                "is_anonymous": False, "date": fb_day, "created_at": fb_day})
    for i, (code, off, note) in enumerate([("EKKA009", 2, "Reviewed sprint load, agreed to push the migration to next cycle."),
                                           ("EKKA011", 5, "Career chat: interested in the platform track, will pair with Kabir."),
                                           ("EKKA012", 8, "Raised concerns about test env instability - action item on DevOps.")], start=1):
        db["checkins"].append({"id": _uid("ci", i), "employee_id": emp_by_code[code],
                               "manager_id": next(e["manager_id"] for e in db["employees"] if e["id"] == emp_by_code[code]),
                               "date": _iso_day(TODAY - timedelta(days=off)), "agenda": "1:1", "notes": note,
                               "next_steps": RNG.choice(["Share the migration plan by Friday.", "Raise a ticket for test env.", "None"]),
                               "status": "Completed"})

    # ---------------- projects + timesheets ----------------
    projects = [("EK-HRMS", "Ekkaa HRMS", "Internal", "EKKA002", 0), ("EK-MOB", "Ekkaa Mobile App", "Internal", "EKKA002", 0),
                ("CLNT-AXIS", "Axis Payments Portal", "Axis Finserve", "EKKA005", 4800),
                ("CLNT-DEL", "Delta Logistics Dashboard", "Delta Logistics", "EKKA008", 3600),
                ("INT-INTERNAL", "Admin / Meetings / Learning", "Internal", "EKKA003", 0)]
    prj_id = {}
    for i, (code, nm, client, owner, rate) in enumerate(projects, start=1):
        pid = _uid("pj", i)
        prj_id[code] = pid
        db["projects"].append({"id": pid, "code": code, "name": nm, "client": client, "manager_id": emp_by_code.get(owner),
                               "billing_rate": rate, "status": "Active" if "CLNT" in code or "HRMS" in code else "Active"})
    ts_n = 0
    week = TODAY - timedelta(days=TODAY.weekday())          # Monday of this week
    for w in range(3):                                       # last 3 weeks
        wk_start = week - timedelta(days=7 * w)
        for emp in active[:12]:
            ts_n += 1
            if w == 0:
                status = "Submitted" if active.index(emp) % 4 == 0 else "Draft"
            elif w == 1 and active.index(emp) < 5:
                status = "Submitted"
            else:
                status = "Approved"
            ts_id = _uid("ts", ts_n)
            db["timesheets"].append({"id": ts_id, "employee_id": emp["id"], "week_starting": _iso_day(wk_start),
                                     "status": status, "submitted_at": _iso_day(wk_start + timedelta(days=5)) if status != "Draft" else None,
                                     "approved_by": emp["manager_id"] if status == "Approved" else None,
                                     "approved_at": _iso_day(wk_start + timedelta(days=6)) if status == "Approved" else None,
                                     "reviewer_remark": None, "total_hours": 0.0, "billable_hours": 0.0})
            total = billable = 0.0
            for d in range(5):
                day = wk_start + timedelta(days=d)
                if day > TODAY:
                    continue
                slots = RNG.choice([[4, 4], [3, 5], [2, 3, 3], [4, 2, 2], [5, 3]])
                if status == "Draft" and d >= 3:      # this week is still being filled in
                    continue
                for hours in slots:
                    pid = RNG.choice(list(prj_id.values()))
                    billable_flag = _project_billable(db, pid)
                    total += hours
                    if billable_flag:
                        billable += hours
                    db["timesheet_entries"].append({"id": f"{ts_id}-{d}-{len(db['timesheet_entries']):04d}",
                                                    "timesheet_id": ts_id, "project_id": pid,
                                                    "employee_id": emp["id"], "date": _iso_day(day), "hours": hours,
                                                    "billable": billable_flag,
                                                    "task": RNG.choice(["Feature work", "Code review", "Bug triage", "Client call", "Sprint planning", "Documentation"])})
            row = next(t for t in db["timesheets"] if t["id"] == ts_id)
            row["total_hours"] = round(total, 1)
            row["billable_hours"] = round(billable, 1)

    # employees on leave today should not have attendance for today
    for att in db["attendance"]:
        if att["date"] == _iso_day(TODAY):
            if any(l["employee_id"] == att["employee_id"] and l["status"] == "Approved"
                   and l["start_date"] <= _iso_day(TODAY) <= l["end_date"] for l in db["leave_requests"]):
                att["status"] = "On Leave"
                att["clock_in"] = att["clock_out"] = None
                att["work_hours"] = 0

    for j in db["jobs"]:
        j["applicants"] = len([c for c in db["candidates"] if c["job_id"] == j["id"]])

    return db


def _project_billable(db, pid):
    return bool(next((p["billing_rate"] for p in db["projects"] if p["id"] == pid), 0))


def _minutes(hhmmss):
    parts = [int(x) for x in str(hhmmss).split(":")]
    return parts[0] * 60 + (parts[1] if len(parts) > 1 else 0)


def _now_minutes():
    now = datetime.now()
    return now.hour * 60 + now.minute


def shift_minutes(hhmmss):
    return _minutes(hhmmss)
