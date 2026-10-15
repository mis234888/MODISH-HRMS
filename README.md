# Ekkaa HRMS - Python + Supabase

A complete, production-ready HRMS built with **Python Flask** and **Supabase**. Modern, clean UI with all major HR modules.

## Team chat

Private one-to-one chat, saved conversations, unread counts, read receipts, and
clickable dashboard/desktop notifications are available in **Chat**. See
[CHAT_SETUP.md](CHAT_SETUP.md) for the separate Supabase migration, encryption
keys, HTTPS/Web Push setup, privacy boundaries, and verification steps.

![Ekkaa HRMS](https://img.shields.io/badge/Stack-Flask%20%2B%20Supabase-15803d) ![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

## âœ¨ Features - Complete HRMS Suite

### 1. **Dashboard / Home**
- Live clock in/out widget
- Stats: Total employees, present, on leave, open positions
- Attendance trend chart (Chart.js)
- Department distribution doughnut
- Announcements, birthdays, anniversaries, who's on leave
- Pending approvals with approve/reject inline
- Quick actions

### 2. **Core HR - Employees**
- Employee directory with search, department & status filters
- Add employee (auto code generation KEKA001...)
- Employee cards with avatar initials, department tags
- Mock + Supabase dual mode

### 3. **Time & Attendance**
- Clock in / Clock out with live timestamp
- Attendance log table (date, in/out, work hours, status)
- Monthly summary, shift details
- Regularization flow
- Stores in `attendance` table

### 4. **Leave Management**
- Leave balances cards (CL, SL, EL, WFH) with color coding
- Apply leave modal (calculates days automatically)
- Approval workflow (Pending â†’ Approved/Rejected)
- Team calendar mini-view
- `leave_types`, `leave_balances`, `leave_requests` tables

### 5. **Payroll**
- Payroll cost overview
- Payslips table (gross, deductions, net)
- Run payroll button, download payslips
- `payroll_structures`, `payslips` tables

### 6. **Recruitment / ATS**
- Job openings grid with applicant counts
- Candidate pipeline kanban (Applied, Screening, Interview, Offer, Hired)
- Candidate cards with ratings
- `jobs`, `candidates` tables

### 7. **Performance**
- OKRs / Goals with progress bars
- Performance reviews (Q1, Q2 cycles)
- Feedback with tags (#teamwork)
- `goals`, `performance_reviews` tables

### 8. **Other Modules**
- Me (profile)
- Inbox (approvals)
- Org Chart
- Documents
- Timesheet
- Expenses / Reimbursements
- Reports

---

## ðŸ—ï¸ Tech Stack

- **Backend:** Python Flask 3.0, Flask-Cors, Gunicorn
- **Database:** Supabase (Postgres + Auth + Storage)
- **Frontend:** Tailwind CSS (CDN), Vanilla JS, Chart.js, Font Awesome
- **Auth:** Session-based (demo), ready for Supabase Auth
- **Deployment:** Works on Render, Railway, Fly.io, Vercel (with adaptor)

---

## ðŸ“ Project Structure

```
keka-hrms-clone/
â”œâ”€â”€ app.py                 # Main Flask app + all API routes
â”œâ”€â”€ requirements.txt       # Python deps
â”œâ”€â”€ .env.example           # Env template
â”œâ”€â”€ supabase_schema.sql    # Full DB schema (run in Supabase SQL editor)
â”œâ”€â”€ templates/
â”‚   â”œâ”€â”€ base.html          # Base layout (Tailwind config)
â”‚   â”œâ”€â”€ login.html         # Login page (dark branding)
â”‚   â””â”€â”€ dashboard.html     # Main SPA - all modules
â””â”€â”€ static/
    â””â”€â”€ js/app.js          # Frontend logic, charts, API calls
```

---

## ðŸš€ Setup From Scratch - Step by Step

### Step 1: Create Supabase Project
1. Go to https://supabase.com â†’ New Project
2. Name: `keka-hrms-clone`, set DB password
3. Wait ~2 mins for provisioning
4. Go to **Project Settings â†’ API** â†’ Copy:
   - `Project URL` (e.g. https://xyz.supabase.co)
   - `anon public key`
   - `service_role key` (keep secret)

### Step 2: Run Database Schema
1. In Supabase Dashboard â†’ **SQL Editor** â†’ New Query
2. Paste entire `supabase_schema.sql` file content
3. Click **Run** â†’ Should create 18 tables + seed data
4. Verify in **Table Editor** â†’ you should see `departments`, `employees`, etc.

### Step 3: Clone & Setup Python Env
```bash
git clone <your-repo>
cd keka-hrms-clone

# Create venv
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### Step 4: Configure Environment
```bash
cp .env.example .env
# Edit .env
nano .env
```
Fill:
```
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-role-key
FLASK_SECRET_KEY=random-string-here-123
PORT=5000
USE_MOCK_DATA=false
```

> **Tip:** If you leave SUPABASE_URL empty or set `USE_MOCK_DATA=true`, app runs in **Mock Mode** with sample data (no DB needed). Perfect for demo.

### Step 5: Run App
```bash
python app.py
```
Open:
- Login: http://localhost:5000/login
- Dashboard: http://localhost:5000/dashboard
- Health: http://localhost:5000/api/health

Demo login: **any email + any password** (e.g. admin@company.com / demo123)

### Step 6: (Optional) Enable Supabase Auth
In `app.py`, uncomment Supabase Auth code in `/login` route:
```python
if supabase:
  res = supabase.auth.sign_in_with_password({"email": email, "password": password})
  session['user'] = res.user
```
And create users in Supabase **Authentication â†’ Users**.

### Step 7: Deploy
**Render.com:**
- New Web Service â†’ Connect repo
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`
- Add env vars from .env

**Railway / Fly.io:** Same - Flask + Gunicorn works out of the box.

---

## ðŸ”Œ API Endpoints

All under `/api/`:

- `GET /api/stats` - dashboard stats
- `GET/POST /api/employees` - CRUD employees
- `POST /api/attendance` - clock in/out
- `GET /api/attendance` - logs
- `GET/POST /api/leave-requests` - leave workflow
- `POST /api/leave-requests/<id>/action` - approve/reject
- `GET /api/departments`, `/api/leave-types`, `/api/jobs`, `/api/candidates`, `/api/payslips`, `/api/announcements`, `/api/goals`, `/api/holidays`, `/api/health`

All endpoints work in both Mock and Supabase mode via `get_supabase_data()` wrapper.

---

## ðŸŽ¨ UI Details - Design System

- **Sidebar:** #052e16 dark, active state #16a34a, icons with opacity
- **Primary:** #15803d (brand green)
- **Background:** #f0fdf4 (light green tint)
- **Cards:** 16px radius, 1px #dcfce7 border, soft shadow
- **Typography:** Inter + Plus Jakarta Sans
- **Components:** Pill filters, avatar initials, status dots

---

## ðŸ”’ Production Hardening TODO

- Replace mock auth with Supabase Auth + RLS strict policies
- Add role-based access (HR Admin, Manager, Employee)
- File uploads â†’ Supabase Storage (resumes, docs, receipts)
- Add pagination & server-side search
- Email notifications for leave approvals (Supabase Edge Functions)
- Payroll calculation engine (PF, ESI, TDS logic)
- Biometric attendance integration via webhooks

---

## ðŸ“¸ Screenshots Flow

Login â†’ Dashboard with clock widget â†’ Employees table â†’ Leave apply â†’ Payroll â†’ Hiring kanban â†’ Performance OKRs

All modules are SPA sections inside `dashboard.html` - no page reloads.

---

## ðŸ¤ Contributing

PRs welcome! This is meant as a starter kit for anyone building HRMS in Python.

---

## ðŸ“„ License

MIT - Use freely for your company.

Built with â¤ï¸ - Python + Supabase edition.
