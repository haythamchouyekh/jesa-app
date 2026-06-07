# JESA DCMA Validator — Web Platform

A professional schedule quality assessment platform built for JESA Engineering.
Flask + SQLite backend. No external services required — fully self-hosted.

---

## Setup

### 1. Install dependencies

```bash
pip install flask werkzeug
```

### 2. Copy your metrics code into the app folder

The `jesa_app/` folder must sit alongside (or contain) your existing
`xer_parser/`, `metrics/`, and `engineering/` packages.

**Recommended layout:**

```
jesa_app/
  app.py
  requirements.txt
  templates/
  database/          ← created automatically
  uploads/           ← created automatically
  xer_parser/        ← copy from dcma_validator
  metrics/           ← copy from dcma_validator
  engineering/       ← copy from dcma_validator
```

### 3. Run

```bash
cd jesa_app
python app.py
```

Then open: **http://localhost:5000**

---

## Default account

| Field    | Value     |
|----------|-----------|
| Username | `admin`   |
| Password | `jesa2024`|

Change the password after first login via the profile page.

---

## Features

| Page | Description |
|------|-------------|
| Login | Secure session auth with hashed passwords (SHA-256) |
| Register | Self-registration with department selection |
| Dashboard | Personal stats (total checks, avg score, good schedules) + recent checks |
| New Check | Drag-and-drop XER upload, data date picker, live progress bar, instant results |
| History | Full paginated table of all your checks |
| Report | Detailed per-metric breakdown, collapsible violation lists, delete |
| Profile | Account info + platform reference card |

---

## Database schema

SQLite database at `database/jesa.db`

- `users` — accounts with hashed passwords, department, role
- `checks` — one row per analysis run (score, grade, JSON results blob)
- `metric_details` — one row per metric per check (for fast queries)

---

## Security notes

- Passwords are SHA-256 hashed before storage
- Session secret is regenerated on every app start (use a fixed secret in production)
- File uploads are secured with `werkzeug.utils.secure_filename`
- Each user can only see their own checks

---

## Production deployment (optional)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Set a fixed `SECRET_KEY` in `app.py` for persistent sessions across restarts.
