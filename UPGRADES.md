Ekkaa HRMS — upgrade notes
What changed in this build, why, and how to check each claim yourself. Every number below was
re-derived from the code and from re-running the checks in §3 on 2026-09-08. Note on provenance:
the previous revision of this file was destroyed by an editing accident (a write to the wrong
path), so this is a reconstruction — the code, the SQL and the two test suites are the source of
truth, not this document.
22. Punch locations: every Clock in / Clock out records where the employee stood
Attendance gained `clock_in_location` and `clock_out_location` (text, added to
`SUPA_COLUMNS` and all three `.sql` files; `supabase_migrate.sql` also carries the
`add column if not exists` lines for databases created before this change). Each cell holds a
compact JSON pin - `{"lat": 28.6139, "lng": 77.209, "accuracy": 9.5, "address": "…"}` - produced
by `punch_location_payload()` and read back by `parse_punch_location()`, which also swallows the
old plain-text `location` values so every historical row keeps rendering. The Home tracker asks
the browser for a one-shot position (`geoTag()` in app.js, W3C device-location API) and
reverse-geocodes it best-effort through OSM Nominatim; if the browser GPS is unavailable
(missing API, denied permission, GPS off, timeout - or the page is plain http, where the
browser GPS API does not exist at all), `geoTag()` falls back to an approximate
network-IP pin (`ipLocation()`, labelled "approx. IP location" in the address) and only
records `{"address": "Office"}` when even that fails. A missing pin never blocks a punch,
and the client toasts why the pin is missing or approximate. `app.js` is served with a
`?v=<mtime>` cache-buster (`asset_v` in app.py) so browsers pick up JS fixes immediately.
Enriched rows now carry `clock_in_location_label / clock_out_location_label` plus
`clock_in_lat / clock_in_lng / clock_in_map` (same for `out`), the Attendance table and the
day-detail modal render both pins with a "view on map" link, the Home tracker shows
"In: … / Out: …" under the status line, and the CSV export adds the two label columns.
1. Data layer (the reason the rest could be honest)
One access path. Every module reads and writes through `db_list / db_get / db_insert / db_update / db_delete`, which talk to Supabase (PostgREST) when `SUPABASE_URL` plus a key are
configured and to the local demo store (`data/mock_store.json`) otherwise. `GET /api/health`
reports which is live (`supabase_connected`, `storage`, `mock_mode`).
Column whitelist. `SUPA_COLUMNS` (app.py) is the single source of truth: 25 tables, 250
column names the app may send. `_clean_for_table()` drops anything else, so an unknown key in
a payload can never become a Postgres 500. `LEGACY_EMPLOYEE_COLUMNS`
(`designation, department, manager, avatar`) names the pre-upgrade employee columns that are read
but never written.
Reads are enriched, not faked. `enrich_*_row` helpers attach the labels the UI shows
(department name, manager name, `date_label`, status pills) from looked-up rows; the browser never
computes a value the API could have provided.
Demo store versioning. `mock_data.MOCK_VERSION = 12`. When the seed shape changes, an
existing store is reseeded on next boot instead of half-matching the new code.
`POST /api/demo/reset` (HR only) or deleting `data/mock_store.json` forces it. The store is
generated output — never commit it.
Generated SQL, never hand-edited. `tools/gen_schema.py` derives all three `.sql` files from
`SUPA_COLUMNS` plus the demo data. Current output: `supabase_setup.sql` 1,681 lines / 490
statements (296 of them `add column if not exists`), `supabase_schema.sql` 1,378 / 212,
`supabase_migrate.sql` 1,658 / 487; the schema it emits is 25 tables / 321 columns. Before
writing anything it runs three checks and refuses on failure: the demo rows against the unique
constraints, the real Postgres grammar (`pglast`), and a statement-order lint that rejects a table
referenced before it is created, an `insert` naming a column twice, and a `not null` column added
without a default.
Two filter engines, one contract. Demo mode filters with `_matches()`, Supabase with
`.eq()`/`.gte()`/`.lte()`/`.in_()`/`.neq()`/`.is_(None)` depending on the shape of the condition.
Sorting goes through `_sort_key()`, which never raises: empty and missing values last, numbers with
numbers, dates and text as text, JSON for lists. Both sort sites used to be
`try: rows.sort(...) except TypeError: pass` - a column of mixed types (or a column that did not
exist at all) silently stayed unsorted in demo mode, and that silence is what let the `feedbacks.date`
bug in §7 survive this long.
2. Every failure reads as a sentence
`@app.errorhandler(Exception)` converts any unhandled error on `/api/*` into a JSON envelope
(`success: false`, `status`, `message`), so a browser can never be handed a raw HTML 500 page.
`_friendly_db_error()` recognises a missing column or table and says which one
(`Your database is missing cycle_start. …`), tells you to run `supabase_setup.sql` — which only
adds what is missing and never touches existing rows — and points at `GET /api/schema-check`.
Input problems are 400s with instructions: `month must be 1-12 or a period like 2026-08`,
a day-of-month out of range, a department name over 60 characters or already taken, an unknown
candidate stage, an email already in use, `to` before `from`.
`try: rows.sort(...) except TypeError: pass` fallback in `db_list` is gone (see §1).
An `ORDER BY` on a column your database does not have is not an error any more.
`order_is_usable()` probes the column once per process, PostgREST refusals trigger a single retry
without the `ORDER BY` (the rows are then sorted in Python), and the verdict is cached in
`_ABSENT_COLUMNS` so the cost is at most one extra query, once. Filters still fail loudly, because
a filter can carry row scoping — silently dropping one would leak rows.
Evidence: `tools/filter_sweep.py` puts 47 parameter-less GET routes through 50 hand-typed junk
values as two roles (4,700 requests) and fails on any 5xx. It is currently clean.
3. Verification
```bash
.venv/bin/python -m pyflakes app.py mock_data.py tests_api.py tools/gen_schema.py
node --check static/js/app.js
sh tools/domcheck/restart.sh            # fresh store + real server on :5000
.venv/bin/python tests_api.py           # endpoint suite
.venv/bin/python tools/filter_sweep.py  # junk filters, two roles
.venv/bin/python check_frontend_refs.py # every id/handler the JS touches exists
.venv/bin/python tools/gen_schema.py    # regenerate + lint all three .sql files
cd tools/domcheck && npm install && node run.js
```
Current results, on this tree:
check	result
`tests_api.py`	339 endpoint checks, ALL GREEN (270 before payroll, 321 before projects)
`tools/domcheck/run.js`	14 modules, 9 reports, 96 recorded assertions passed (75 before)
`tools/filter_sweep.py`	4,700 requests, no 5xx anywhere
`check_frontend_refs.py`	clean (its `['/api/payslips/']` line is a known false positive)
pyflakes / `node --check`	clean
`tools/gen_schema.py`	statement order OK, schema columns with no `SUPA_COLUMNS` entry: none, unique-constraint violations: none
pglast on the three `.sql` files	490 / 212 / 487 statements parse
Both suites write to the store, so the usual order is `restart.sh` then `tests_api.py`; finish with
`POST /api/demo/reset`. The clock check clears and re-closes its own day, so it can no longer skip
silently when a seeded "today" row already has punches.
Caveat that applies to every SQL claim in this file: the SQL is parsed with the real Postgres
grammar and linted for the ordering and default traps that previously bit us, but it has never been
executed against a live Postgres from this environment. Run it in the Supabase SQL editor, where a
problem shows up as a statement error rather than silence.
4. Sign-in, roles and per-person access
Who is HR. `HR Admin` iff the signed-in email is in `ADMIN_EMAILS`. Password check is
`verify_employee_password`: the employee's own `password_hash` if they have set one, otherwise the
shared `EMPLOYEE_PASSWORD`. An `Exited` account is refused at the door (401) rather than quietly
downgraded.
Sessions. `GET /api/session` (also for a signed-out visitor), `POST /api/me/password`
(current password required, `MIN_PASSWORD_LENGTH` enforced, reuse refused), and
`POST /api/employees/<id>/reset-password` which issues a one-time password and puts the account
back on the shared one. `GET /api/login-hint` is public so the sign-in screen can say which
demo logins exist. `password_hash` never leaves the API.
What an employee sees. 11 modules — `home, me, inbox, attendance, leave, timesheet, payroll, expenses, documents, performance, orgchart`. 3 are HR-only — `employees, hiring, reports` — and
are hidden in the sidebar (`applyRoleGating`) and refused server-side (`hr_area()` → 403,
`@admin_required`). Hiding, not deleting: the routes and the data still exist for HR.
Row-level scoping. `scoped_employee_id()` pins every self-service read to the signed-in
person: their attendance, leave, payslips, expenses, documents, timesheets, goals, feedback and
the CSV exports of those. A list endpoint an employee may not open is 403, not an empty 200.
`/api/employees` for a non-admin returns only the names needed for lookups.
Edit is HR-visible only. The Employees edit affordance renders for HR Admin; employees get
`Me`, where `SELF_EDITABLE_FIELDS` (8: contact, address, emergency and work-location fields) may
be changed and anything else comes back as a 403 with an explanation.
5. Wall-clock correctness (this is what broke in the cloud)
`clock.py` is the only clock the app uses. `APP_TIMEZONE` accepts an IANA name or a fixed offset
(`+05:30`) and defaults to `Asia/Kolkata`; a zone the host cannot resolve degrades to UTC and says
so in `TZ_LABEL` instead of raising. Windows hosts need the `tzdata` wheel — this project was
developed on one.
`app.py` and `mock_data.py` both take today's date and time from it, so seeded rows and live
"today" queries agree even between midnight and 05:30 IST, when UTC and IST are a whole calendar
day apart. `/api/health` publishes `timezone`, `office_time` and `wall_clock_offset_minutes` for
debugging a deployment.
`norm_time()` accepts `09:55 AM`, `9:55` and `09:55:00` and `minutes_of()` returns the pair in
minutes, so a punch typed by a person and a punch stamped by the app are comparable. `fmt_time()`
renders 12-hour labels for humans only; the stored value stays a `TIME`.
Attendance: a punch today creates today's row (it used to be possible to clock in on a row that
did not exist); a closed day refuses a second clock-in; HR corrections go through
`POST /api/attendance/entry` with validation; regularization requires a typed reason — an empty
one is refused and the modal says so.
Payroll: month parameters are ISO (`2026-08`) only, and `GET /api/payroll/summary` has a default
for its month argument. Missing that default was the 500 that took the Payroll tab down.
If rows were written while the container ran on UTC, the stored times are 5 h 30 min early.
Inspect first, then repair deliberately:
`select date, clock_in, clock_out from attendance order by date desc limit 20;` and, once you have
confirmed the direction, `update attendance set clock_in = clock_in + interval '5 hours 30 minutes', clock_out = clock_out + interval '5 hours 30 minutes' where date >= '2026-09-01';`
Known limit, unfixed: a night shift that crosses local midnight is still split at midnight, so
its hours land on two days.
6. Front-end: real data, working buttons
No simulated values. Home cards come from `/api/stats` (`renderHomeKpis`), the tracker from the
same payload (`renderTracker`), and each module's own list from its own endpoint: 100 `api()` call
sites on 63 distinct paths in `static/js/app.js`, all of them against routes that exist
(`check_frontend_refs.py` proves both halves - every id and handler the JS touches exists, and the API
paths it calls exist).
Documents record and display why a file was uploaded (`purpose`), who owns it
(`uploaded_by`, an email) and who may see it (`visibility`), plus `reviewed_at` and reviewer notes.
Attendance shows the regularization flow with a mandatory reason, and HR's manual-entry modal
(blank the pair to reopen a closed day).
Org chart got the controls that make it usable: `#orgFocus` (root on any manager), `#orgDepth`,
zoom, expand/collapse, PNG export, `#orgNotice` for the empty/filtered states, and department
management — `openDepartmentForm` / `submitDepartment` / `deleteDepartment` with pen and trash
buttons in the Departments tab. Departments are now creatable, renamable and deletable by HR
(`POST|PUT|DELETE /api/departments`): name ≤ 60 chars and unique ignoring case and whitespace,
`head_id` must be a real employee, and a delete is refused while non-Exited employees remain (its
`designations.department_id` / `jobs.department_id` links are unlinked first).
Leave and Expenses were kept as they were (they worked) and only rebound. Payroll was
rebuilt around a salary structure and a real monthly process — see §9; the tab's existing controls
(month/year/employee filters, the payslip table, the detail view) stayed where they were.
Timesheet, Hiring, Performance, Reports, Me were redesigned: candidate drawer,
goals/feedback views, a report builder whose CSV is a GET link.
Errors are rendered, not swallowed: a failed call shows `body.message` as an error toast, so a
schema problem reads as a sentence and a 500 can never paint itself over the page.
The DOM harness (`tools/domcheck/run.js`, 702 lines) executes the real `app.js` in jsdom against
the running server and clicks the buttons that used to be dead — attendance edit save, both
document modals, the clock-in/clock-out comparison with `/api/stats`, the employee page as a
separately signed-in person. Modal state is read from `#modalBackdrop`; toast tones are
`success|error|info|warn`.
7. Supabase: the two "missing column" reports
`supabase_setup.sql` is the only file you need in the SQL editor. It creates what is missing, adds
changed columns, repairs an `ON DELETE` action that differs, enables RLS, grants, and seeds
reference data; it is a no-op on the second run. `supabase_schema.sql` (fresh install) and
`supabase_migrate.sql` (the additive half on its own) remain for reference.
`GET /api/schema-check` answers "is my database current?" without guessing:
`{mode, tables_expected, tables_missing, columns_missing, unverifiable, gaps, up_to_date, advice}`.
It probes each expected column on the real database (a nullable column absent from a sample row is
not a gap — that false-alarm version was removed) and short-circuits in demo mode to `gaps: 0, up_to_date: true`.
Two reports that looked identical were not:
`performance_reviews.cycle_start` missing — the database really was behind this build. Fixed by
re-running `supabase_setup.sql`.
`feedbacks.date` missing — my bug, not theirs. `api_feedback` ordered `db_list("feedbacks", order="date")` and the POST handler wrote a `date` key, but `feedbacks` never had that column: not
in `SUPA_COLUMNS`, not in `tools/gen_schema.py`, not in any generated SQL. Demo mode hid it (every
sort key was `None`, `rows.sort` raised `TypeError`, and `except TypeError: pass` swallowed it);
against Supabase the write was silently dropped by `_clean_for_table()` — feedback dates never
persisted — and the `ORDER BY` was a hard Postgres error.
The fix makes the column real end to end: `"date"` in `SUPA_COLUMNS["feedbacks"]`, the three
`.sql` files regenerated (the setup file gains `alter table feedbacks add column if not exists date date;`, so existing projects are upgraded by re-running it), and `mock_data.py` seeding
`date` from each row's `created_at` at `MOCK_VERSION = 12`. Until the SQL is re-run the tab still
loads: the degrade path in §2 drops the `ORDER BY` and sorts in Python. `UPGRADES.md` §1's
whitelist is what makes that drop silent, so the write path is worth reading before you add a key.
The invariant that should have caught this on day one is now a test. `tests_api.py` parses
`app.py`: every `order=` and filter column in every `db_list`/`db_get` call, and every name in
every `*_FIELDS` write allowlist, must be a column of the table it is used against
(`SUPA_COLUMNS[table] | {id, created_at, updated_at}`). A `*_FIELDS` constant missing from the
explicit `_TABLE_OF_FIELDS` map fails the suite until someone maps it — which is how
`HIRE_FIELDS` turned out to belong to employees, not candidates. Failure text:
`code asks for columns the schema does not have: …`.
Four allowlist names that no form sent and no table had were deleted while I was there
(`EMPLOYEE_FIELDS`: `bank_account_name`, `shift_id`; `CANDIDATE_FIELDS`: `skills`, `location`).
Traps the generator now refuses to emit, each of which once produced a real error in the SQL
editor: an inline `references` on a column whose table is created later, foreign-key cycles,
`default x default y`, `add column … not null` without a default, and a unique index over
duplicate demo rows.
The generator's `demo rows whose columns the app would drop` line is informational, not a warning:
those are keys the demo seed carries for its own bookkeeping (`shifts.start_minutes`,
`leave_requests.leave_type`, `jobs.applicants`, `candidates.experience`, `documents.file_path`) that
have no column and no need of one.
8. Limits, and what to do when you add a column
`SUPA_COLUMNS` constrains writes and order/filter keys; reads are `select("*")`, so a column
can exist in the database and simply be ignored by the app.
List endpoints return whole tables (only a few implement paging), which is fine at demo scale and
worth revisiting past a few thousand rows.
To add a column: put it in `SUPA_COLUMNS`, run `python tools/gen_schema.py`, run
`supabase_setup.sql` in the editor, then `tests_api.py`. If you order or filter by it, the
invariant test in §7 fails until the SQL exists — that is the intended loop.
Never push: `data/mock_store.json`, `uploads/`, `logfile/`, `.venv/`, `node_modules/`,
`__pycache__`, `.env`, `deploy-ready/`.
Environment variables: `SUPABASE_URL`, `SUPABASE_KEY` / `SUPABASE_PUBLISHABLE_KEY` /
`SUPABASE_SECRET_KEY` / `SUPABASE_SERVICE_KEY`, `SUPABASE_STORAGE_BUCKET`, `USE_MOCK_DATA`,
`MOCK_PERSIST`, `ADMIN_EMAILS`, `ADMIN_PASSWORD`, `EMPLOYEE_PASSWORD`, `DEFAULT_EMPLOYEE_EMAIL`,
`MIN_PASSWORD_LENGTH`, `APP_TIMEZONE`, `FLASK_SECRET_KEY`, `FLASK_DEBUG`, `PORT` (see
`.env.example`).
9. Payroll: the salary structure, and a month that has a lifecycle
The tab used to render a number per employee from `employees.salary_ctc` — enough to look like a
payroll screen, with nothing behind it. There was no structure (no basic / HRA / allowances /
deductions), nothing was derived from attendance, and "publish" was a status string with no meaning.
What is there now:
A structure is a dated revision, not a field. `payroll_structures` — `employee_id`, `name`,
`effective_from`, `basic`, `hra`, `special_allowance`, `allowances` (a JSON object of any number of
named lines), then the deduction side `pf`, `esi`, `professional_tax`, `tds`, `other_deduction`, and
`employer_pf`. Twelve columns, all in `SUPA_COLUMNS` and in `supabase_setup.sql`; bank account,
IFSC, PAN and UAN deliberately stay on `employees`, because a revision to a salary is not a new
bank account. Which structure governs a month = the latest `effective_from` on or before that
month's last day, so an increase dated 1 Oct changes October and leaves September's payslip alone.
Components are the truth; CTC is derived and only then checked. `ctc = 12 × (gross + employer_pf)`. A save that carries an explicit `ctc` must agree with that within `max(₹100, 1 %)`,
or the write is refused with the computed figure in the message — so nobody can store a CTC that the
paylines do not add up to. The seed does the same in reverse: the components are solved from
`salary_ctc` rather than rounded independently and summed, which is what produced a −₹93,600
difference between the roster and payroll in an earlier build. `GET /api/payroll/structures` reports
`ctc_drift` per row; the roster-wide drift is now ±₹0.04 on rounding alone.
Refusals read as sentences (`parse_structure_payload`): HRA above basic, a negative component, a
net that is not positive, a name over 60 chars, a second structure with the same name for the same
employee, and a delete while that employee still has a draft payslip waiting (`"This structure backs 2 draft payslip(s) for that employee - publish, revoke or delete them first"`). `PUT` merges: an edit that
sends only `basic` keeps the allowances, the name and the rest, and recomputes gross/net from the
merge — so the partial-form bug that silently zeroed fields cannot come back.
A month is computed, not typed. `POST /api/payroll/run` works out the period's calendar
(Mon–Fri minus that month's `holidays`, clipped by joining date, exit date and today), then for each
employee: gross per day = monthly gross ÷ working days; loss of pay = 1 day per `Absent`, 0.5 per
`Half Day`, 1 per `On Leave` whose type is unpaid — and a working day that is already over with no
punch on file counts as `Absent` as well (`missing_attendance_rows`, the same verdict the attendance
screen shows), so a forgotten punch costs the day. Today is never docked, and a pending
regularization request or approved paid leave keeps the day off the list — regularize to win it back;
then
`net = gross + bonus − deductions − LOP`, with the day counts stored on the slip so the payslip can
show its own working. Re-running is idempotent: existing `Published`/`Paid` slips are left alone and
reported under `kept` unless you ask for `overwrite`. The response is a report — `created`,
`updated`, `kept`, `skipped` (each with a reason, e.g. "no salary structure in force"), `net_payroll`.
Draft → Published → Paid, and the employee sees only what was released. A slip in `Draft` is not
in an employee's list and its `/detail` answers 404 with "still being prepared" — HR can re-run the
month five times and no half-built number reaches anyone. `POST /api/payroll/publish` releases a
whole period (or one id) and stamps `published_at`; `POST /api/payroll/mark-paid` takes a `paid_on`
date and refuses to pay a period that is not published yet. `POST /api/payslips/<id>/revoke` needs a
reason of at least 8 characters, reopens the slip as a draft, and records why; `PUT /api/payslips/<id>`
will move a released slip's status or paid-on date — that is what Mark paid is for — but refuses
to change its amounts until it is a draft again, so "publish, then quietly edit" cannot leave the
employee with a PDF that no longer matches the bank file. The edit modal greys the amount fields out
in the same rule, so the refusal is not the first you hear of it.
`DELETE` likewise only on a draft.
The payslip itself. `GET /api/payslips/<id>/detail` returns the earning lines (basic, HRA, each
named allowance), the deduction lines (PF, ESI, PT, TDS, and a computed `Loss of pay` line), the day
counts, `net_in_words` (`Rupees Eighty One Thousand Six Hundred Forty One and Thirty Three Paisa Only` — the Indian grouping, generated from the number, not stored), the bank block pulled from
`employees`, the structure that was used, and the approved leave in the period. The arithmetic is
asserted, not assumed: the earnings lines add to `gross`, the deduction lines add to `total_deductions`,
and `gross − deductions = net`.
The HR-facing outputs. `GET /api/payroll/register?period=YYYY-MM` (rows + totals, one source for
the table, the KPIs and the file) and `GET /api/payroll/register/export` — the bank CSV: employee
code, name, department, designation, period, days, payable days, LOP days, bonus, gross, deductions,
net, status, paid-on, account no, IFSC, bank, branch. `csv_response` title-cases the headers, so the
file's columns read `Account No`, not `account_no`.
The UI is the process. Payroll now has two tabs (an employee's second tab is My structure and
shows a read-only card, not the HR table), a notice bar that states what is outstanding and offers
Fix that / Publish the drafts / Download the bank file, the toolbar's Run payroll,
Publish, Mark paid, Register CSV (all `data-admin-only`), a 9-column slip table, a
structure form whose totals strip moves while you type and whose allowance lines are add/remove, and a
slip modal with the days strip, the LOP chips, the amount in words, the bank grid, and Edit / Publish
/ Revoke for HR. `?period=` on `/api/payslips` and `/api/payroll/summary` means the register, the
table and the CSV always describe the month on screen, not the current one.
And the month is the office's month. `payPeriod()` and every date default in the app used to
come from `todayIso()`, which read the browser's clock through an expression that was a no-op
timezone shift — after 18:30 UTC it handed back yesterday, so a run started on the first of the
month at 12:30 a.m. IST targeted the previous month. `/api/session` now returns
`office_date`/`office_time` and `todayIso()` returns that; the harness asserts the served date equals
the office date the server's own calendar reports.
How to see it move, in five requests:
```bash
curl -s -b c.txt 'localhost:5000/api/payroll/summary' | head -c 300      # period, drafts, LOP days
curl -s -b c.txt -H 'Content-Type: application/json' -d '{"period":"2026-09"}' \
     -X POST localhost:5000/api/payroll/run | head -c 400               # the run report, per employee
curl -s -b c.txt 'localhost:5000/api/payslips/<an id from that period>/detail' | head -c 400
curl -s -b c.txt 'localhost:5000/api/payroll/register?period=2026-09' | head -c 300
curl -s -b c.txt 'localhost:5000/api/payroll/register/export?period=2026-09' | head -2
```
Covered by `tests_api.py`: HR/employee scoping of structures, 403 on run/publish/mark-paid/register/
CSV for an Employee, each validation refusal by its sentence, create → duplicate-name → partial `PUT`
→ delete → the previous revision falling back into force, an idempotent re-run, a future and a junk
period, every slip in `Draft` right after a run, LOP present only where attendance says so, the
employee's empty list before publish and their one slip after, paying before publishing, register
totals against its own rows, `paid_on_label`, revoke needing a reason, a revoked slip reopened and
re-released with the new bonus, and the CSV's row count, header and `text/csv`. Plus in the DOM
harness: the totals strip reacting to typing, a structure saved through the form, revision fallback,
the run modal's prefill, publishing from the toolbar and the table's pills, and the slip's net on
screen equal to the API's number.
10. Timesheet projects: a list anyone can extend
Five seeded projects, all of them `Active`, and the grid offered exactly those — so the honest answer
to "what did I actually work on this week?" had to be squeezed into Admin / Meetings / Learning.
The names are no longer fixed.
`POST /api/projects` is open to any signed-in person, deliberately: whoever needs a place to log
hours is the one who knows its name. `PUT /api/projects/<id>` and `DELETE` are guarded by
`project_mutable()` — an HR Admin, or the person the project is filed under as `manager_id`.
Creating one makes you its manager, so a typo is yours to fix without a ticket; HR can reassign
the manager when someone leaves.
`_clean_project()` keeps the row honest the way the department and structure forms do: a name,
under 60 characters, not the same name as another project ignoring case and spacing; a `code` that
is slug-uppercased, at least three characters, and unique — `projects.code` is `not null` with a
unique index, so a generated code is checked against the rows on file rather than being handed to
Postgres to reject. Left blank, the code is made from the first two words (`Northwind Migration` →
`PRJ-NORT-MIGRA`) with a `-2` suffix if that is taken. Billing rate cannot be negative; status must
be one of `Active, On Hold, Completed, Closed`; a manager must be someone on the roster. A `PUT`
carries only what it touched and the rest is taken from the row on file, so a one-field edit
("mark it Completed") cannot blank a client or a rate.
A project with hours on it cannot be deleted. `DELETE` counts the `timesheet_entries` that
point at it and refuses with the number and the hours — `Ekkaa HRMS already has 62 logged entries worth 208.5 h - mark it Completed instead` — because deleting it would leave logged time
attributed to nothing. Closing is the way to retire it, and `Closed`/`Completed` projects drop out
of the dropdown for new rows while staying listed on the row that already carries their hours.
No schema change. Every field this needed (`code`, `name`, `client`, `manager_id`,
`billing_rate`, `status`) already existed in `SUPA_COLUMNS["projects"]` and in the SQL, so an
existing Supabase deployment needs nothing re-run for this one.
The UI is a combobox, not a ticket. Each row's project select ends in + Type a new project
name…, which opens the form with that row remembered; New project sits under the grid for
creating one from nowhere. On save the new project is folded into `APP.ts.projects` and the row's
`project_id` set — the grid is not refetched, because a reload would throw away the hours being
typed. Rows show edit / remove under a project this login manages, and the Projects tab grew an
actions column with the same two plus a header button.
Covered by `tests_api.py` (employee can create; owns it; one-field PUT keeps rate and client; the
project reaches `/api/projects`, `/api/timesheet` and `/api/lookups`; eight bad forms each answered
with a sentence; a stranger gets 403 naming the manager; delete refused while 208.5 h point at it;
own empty project deleted and gone) and by the DOM harness, which types a name into the grid's
select, saves, logs 2 h against it, is refused on delete, then puts the borrowed row back — the
week ends at the exact total it started at, with nothing left pointing at the scratch project —
and only then removes it from the Projects tab.
