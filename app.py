# app.py  — JESA DCMA Validator Platform
# Flask backend: authentication, SQLite persistence, XER analysis API

from __future__ import annotations
import os, sys, json, hashlib, secrets, sqlite3, csv, io, tempfile
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils  import get_column_letter
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from functools import wraps

from flask import (Flask, request, jsonify, session,
                   render_template, redirect, url_for, flash, Response)
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

# ── Path setup ──────────────────────────────────────────────────────────────
# BASE_DIR = jesa_app/ folder (where this app.py lives)
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
# PROJ_DIR = parent folder (dcma_validator/) — where xer_parser/, metrics/, engineering/ live
PROJ_DIR    = os.path.dirname(BASE_DIR)

DB_PATH         = os.path.join(BASE_DIR, 'database', 'jesa.db')
UPLOAD_DIR      = os.path.join(BASE_DIR, 'uploads')
TMP_UPLOAD_DIR  = os.path.join(BASE_DIR, 'tmp_uploads')
ALLOWED_EXT     = {'xer'}

# Add BOTH to sys.path so imports work no matter where python is invoked from
sys.path.insert(0, PROJ_DIR)   # ← finds xer_parser, metrics, engineering
sys.path.insert(0, BASE_DIR)   # ← finds anything local to jesa_app

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Persist the secret key across restarts so sessions survive server reloads
_secret_file = os.path.join(BASE_DIR, 'database', 'secret.key')
try:
    os.makedirs(os.path.dirname(_secret_file), exist_ok=True)
    if os.path.exists(_secret_file):
        with open(_secret_file, 'r') as _f:
            app.secret_key = _f.read().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        with open(_secret_file, 'w') as _f:
            _f.write(app.secret_key)
except Exception:
    app.secret_key = secrets.token_hex(32)

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024   # 50 MB
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['WTF_CSRF_TIME_LIMIT'] = None  # no expiry so long sessions stay valid
app.jinja_env.globals['zip'] = zip

csrf = CSRFProtect(app)

# The DELETE /api/check/<id> uses fetch() with X-CSRFToken header.
# Flask-WTF reads X-CSRFToken automatically for AJAX requests, so no exemption needed.
# If you add a truly token-less webhook, exempt it explicitly here with @csrf.exempt.

from flask_wtf.csrf import CSRFError

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'CSRF token missing or invalid. Refresh the page.'}), 400
    flash('Session expired or invalid request. Please try again.', 'error')
    return redirect(request.referrer or url_for('dashboard'))


@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# ── Rate limiting ────────────────────────────────────────────────────────────
_login_attempts: dict   = defaultdict(list)   # ip -> [datetime, ...]
_analyze_attempts: dict = defaultdict(list)   # ip -> [datetime, ...]
_RATE_LIMIT    = 5
_LOCKOUT_MINS  = 15
_ANALYZE_LIMIT = 20   # per 5 minutes
_ANALYZE_MINS  = 5

def _rate_limit_check(ip: str):
    """Return (allowed, wait_seconds). Prunes stale entries on each call."""
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=_LOCKOUT_MINS)
    _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]
    if len(_login_attempts[ip]) >= _RATE_LIMIT:
        wait = int(_LOCKOUT_MINS * 60 - (now - _login_attempts[ip][0]).total_seconds())
        return False, max(wait, 1)
    return True, 0

def _analyze_rate_check(ip: str):
    """Return (allowed,). Prunes stale entries on each call."""
    now    = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=_ANALYZE_MINS)
    _analyze_attempts[ip] = [t for t in _analyze_attempts[ip] if t > cutoff]
    if len(_analyze_attempts[ip]) >= _ANALYZE_LIMIT:
        return False
    _analyze_attempts[ip].append(now)
    return True


# ── Database helpers ────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(TMP_UPLOAD_DIR, exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        username   TEXT,
        action     TEXT    NOT NULL,
        target     TEXT    DEFAULT '',
        ip         TEXT    DEFAULT '',
        created_at TEXT    DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_checks_user_id       ON checks(user_id);
    CREATE INDEX IF NOT EXISTS idx_checks_project_id    ON checks(project_id);
    CREATE INDEX IF NOT EXISTS idx_metric_details_check ON metric_details(check_id);
    CREATE INDEX IF NOT EXISTS idx_pm_project_id        ON project_members(project_id);
    CREATE INDEX IF NOT EXISTS idx_pm_user_id           ON project_members(user_id);

    CREATE TABLE IF NOT EXISTS users (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        username             TEXT    UNIQUE NOT NULL,
        full_name            TEXT    NOT NULL,
        email                TEXT    DEFAULT '',
        department           TEXT    DEFAULT 'Project Control',
        password_hash        TEXT    NOT NULL,
        role                 TEXT    DEFAULT 'engineer',
        must_change_password INTEGER DEFAULT 0,
        created_at           TEXT    DEFAULT (datetime('now')),
        last_login           TEXT
    );

    CREATE TABLE IF NOT EXISTS projects (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        code        TEXT    DEFAULT '',
        description TEXT    DEFAULT '',
        created_by  INTEGER,
        created_at  TEXT    DEFAULT (datetime('now')),
        FOREIGN KEY(created_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS project_members (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        added_at   TEXT    DEFAULT (datetime('now')),
        FOREIGN KEY(project_id) REFERENCES projects(id),
        FOREIGN KEY(user_id)    REFERENCES users(id),
        UNIQUE(project_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS checks (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        project_id   INTEGER,
        project_name TEXT    NOT NULL,
        xer_filename TEXT    NOT NULL,
        data_date    TEXT,
        activities   INTEGER DEFAULT 0,
        relationships INTEGER DEFAULT 0,
        score        INTEGER DEFAULT 0,
        grade        TEXT    DEFAULT '',
        passed       INTEGER DEFAULT 0,
        total_metrics INTEGER DEFAULT 14,
        results_json TEXT,
        created_at   TEXT    DEFAULT (datetime('now')),
        FOREIGN KEY(user_id)    REFERENCES users(id),
        FOREIGN KEY(project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS metric_details (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        check_id  INTEGER NOT NULL,
        metric_no INTEGER,
        metric_name TEXT,
        status    TEXT,
        violations INTEGER DEFAULT 0,
        total     INTEGER DEFAULT 0,
        percentage REAL    DEFAULT 0,
        details_json TEXT,
        FOREIGN KEY(check_id) REFERENCES checks(id)
    );
    """)

    # Migrations
    for migration in [
        "ALTER TABLE checks ADD COLUMN project_id INTEGER REFERENCES projects(id)",
        "ALTER TABLE checks ADD COLUMN xer_blob BLOB",
        "ALTER TABLE checks ADD COLUMN actual_proj_id TEXT DEFAULT ''",
        "ALTER TABLE checks ADD COLUMN baseline_proj_id TEXT DEFAULT ''",
        "ALTER TABLE checks ADD COLUMN baseline_proj_name TEXT DEFAULT ''",
        "ALTER TABLE checks ADD COLUMN baseline_data_date TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_code ON projects(code) WHERE code != ''",
    ]:
        try:
            c.execute(migration)
            conn.commit()
        except Exception:
            pass

    # Default admin (password: jesa2024 — forced to change on first login)
    pwd_hash = _hash_password('jesa2024')
    try:
        c.execute("""INSERT INTO users (username,full_name,email,role,password_hash,must_change_password)
                     VALUES (?,?,?,?,?,?)""",
                  ('admin', 'JESA Administrator', 'admin@jesa.internal', 'admin', pwd_hash, 1))
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    conn.close()


def _hash_password(pwd: str) -> str:
    return generate_password_hash(pwd)

def _check_password(stored_hash: str, password: str) -> bool:
    """Verify password; auto-detects legacy SHA-256 hashes (64 hex chars)."""
    if len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash):
        # Legacy plain SHA-256 hash — compare and signal upgrade needed
        return stored_hash == hashlib.sha256(password.encode()).hexdigest()
    return check_password_hash(stored_hash, password)

def _validate_password(pwd: str) -> str | None:
    """Return an error message string, or None if the password is acceptable."""
    if len(pwd) < 8:
        return 'Password must be at least 8 characters.'
    if not any(c.isupper() for c in pwd):
        return 'Password must contain at least one uppercase letter.'
    if not any(c.isdigit() for c in pwd):
        return 'Password must contain at least one number.'
    return None


def _cleanup_tmp_uploads(max_age_hours: int = 24):
    """Delete stale temp XER/meta files older than max_age_hours."""
    if not os.path.isdir(TMP_UPLOAD_DIR):
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    for fname in os.listdir(TMP_UPLOAD_DIR):
        fpath = os.path.join(TMP_UPLOAD_DIR, fname)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            if mtime < cutoff:
                os.unlink(fpath)
        except Exception:
            pass


def _audit(action: str, target: str = ''):
    """Write one row to audit_log. Silently ignores DB errors."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_log (user_id,username,action,target,ip) VALUES (?,?,?,?,?)",
            (session.get('user_id'), session.get('username', ''),
             action, target, request.remote_addr or '')
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Auth decorator ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Session expired. Please log in again.'}), 401
            return redirect(url_for('login'))
        if session.get('must_change_password') and request.endpoint != 'force_change_password':
            return redirect(url_for('force_change_password'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Routes — Auth ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip       = request.remote_addr or '0.0.0.0'
        allowed, wait = _rate_limit_check(ip)
        if not allowed:
            mins = (wait // 60) + 1
            flash(f'Too many failed attempts. Try again in {mins} minute(s).', 'error')
            return render_template('login.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE username=?', (username,)
        ).fetchone()
        conn.close()

        if user and _check_password(user['password_hash'], password):
            _login_attempts.pop(ip, None)   # clear failed attempts on success
            session.permanent = True
            session['user_id']             = user['id']
            session['username']            = user['username']
            session['full_name']           = user['full_name']
            session['role']                = user['role']
            session['must_change_password'] = bool(user['must_change_password'])
            conn = get_db()
            # Auto-upgrade legacy SHA-256 hash to werkzeug pbkdf2
            stored = user['password_hash']
            if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
                conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                             (_hash_password(password), user['id']))
            conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?",
                         (user['id'],))
            conn.commit()
            conn.close()
            _audit('login_success', user['username'])
            if user['must_change_password']:
                return redirect(url_for('force_change_password'))
            return redirect(url_for('dashboard'))

        _login_attempts[ip].append(datetime.utcnow())
        _audit('login_failed', username)
        remaining = _RATE_LIMIT - len(_login_attempts[ip])
        if remaining > 0:
            flash(f'Invalid username or password. {remaining} attempt(s) left.', 'error')
        else:
            flash(f'Too many failed attempts. Account locked for {_LOCKOUT_MINS} minutes.', 'error')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username  = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password  = request.form.get('password', '')
        confirm   = request.form.get('confirm', '')

        if password != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        pw_err = _validate_password(password)
        if pw_err:
            flash(pw_err, 'error')
            return render_template('register.html')

        try:
            conn = get_db()
            conn.execute(
                """INSERT INTO users (username,full_name,email,password_hash)
                   VALUES (?,?,?,?)""",
                (username, full_name, f'{username}@jesa.internal', _hash_password(password))
            )
            conn.commit()
            conn.close()
            flash('Account created. Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists.', 'error')
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def force_change_password():
    if request.method == 'POST':
        new_pw  = request.form.get('new_password', '').strip()
        confirm = request.form.get('confirm_password', '')
        pw_err = _validate_password(new_pw)
        if pw_err:
            flash(pw_err, 'error')
            return render_template('force_change_password.html')
        if new_pw != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('force_change_password.html')
        conn = get_db()
        conn.execute(
            "UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?",
            (_hash_password(new_pw), session['user_id'])
        )
        conn.commit()
        conn.close()
        session['must_change_password'] = False
        _audit('password_forced_change')
        flash('Password changed successfully. Welcome!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('force_change_password.html')


# ── Routes — App ─────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    uid  = session['user_id']
    role = session['role']

    # Admin number map: {user_id: 1, 2, 3, ...} ordered by creation
    admins_list = conn.execute(
        "SELECT id FROM users WHERE role='admin' ORDER BY id"
    ).fetchall()
    admin_num = {row['id']: i + 1 for i, row in enumerate(admins_list)}

    if role == 'admin':
        checks = conn.execute(
            """SELECT c.*, u.username, u.full_name, u.role as user_role,
                      p.name as admin_project_name, p.code as admin_project_code
               FROM checks c
               JOIN users u ON c.user_id=u.id
               LEFT JOIN projects p ON c.project_id=p.id
               ORDER BY c.created_at DESC LIMIT 5"""
        ).fetchall()
        stats = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN grade='GOOD' THEN 1 ELSE 0 END) as good_count,
                      SUM(CASE WHEN grade='FAIR' THEN 1 ELSE 0 END) as fair_count,
                      SUM(CASE WHEN grade='POOR' THEN 1 ELSE 0 END) as poor_count
               FROM checks"""
        ).fetchone()
        my_runs = conn.execute(
            "SELECT COUNT(*) as cnt FROM checks WHERE user_id=?", (uid,)
        ).fetchone()['cnt']
    else:
        checks = conn.execute(
            """SELECT c.*, u.username, u.full_name, u.role as user_role,
                      p.name as admin_project_name, p.code as admin_project_code
               FROM checks c
               JOIN users u ON c.user_id=u.id
               LEFT JOIN projects p ON c.project_id=p.id
               WHERE (c.project_id IS NULL AND c.user_id=?)
                  OR (c.project_id IS NOT NULL AND EXISTS (
                      SELECT 1 FROM project_members pm
                      WHERE pm.project_id=c.project_id AND pm.user_id=?
                  ))
               ORDER BY c.created_at DESC LIMIT 5""", (uid, uid)
        ).fetchall()
        stats = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN grade='GOOD' THEN 1 ELSE 0 END) as good_count,
                      SUM(CASE WHEN grade='FAIR' THEN 1 ELSE 0 END) as fair_count,
                      SUM(CASE WHEN grade='POOR' THEN 1 ELSE 0 END) as poor_count
               FROM checks WHERE user_id=?""", (uid,)
        ).fetchone()
        my_runs = stats['total'] or 0
    project_run_nos = {}
    seen_projects   = set()
    for c in checks:
        pid = c['project_id']
        if pid is not None and pid not in seen_projects:
            seen_projects.add(pid)
            rows = conn.execute(
                "SELECT id FROM checks WHERE project_id=? ORDER BY created_at, id", (pid,)
            ).fetchall()
            for i, row in enumerate(rows):
                project_run_nos[row['id']] = i + 1

    conn.close()
    return render_template('dashboard.html', checks=checks, stats=stats,
                           admin_num=admin_num, my_runs=my_runs,
                           project_run_nos=project_run_nos)


@app.route('/new-check')
@login_required
def new_check():
    conn = get_db()
    uid  = session['user_id']
    if session['role'] == 'admin':
        projects = conn.execute('SELECT * FROM projects ORDER BY name').fetchall()
    else:
        projects = conn.execute(
            """SELECT p.* FROM projects p
               JOIN project_members pm ON p.id=pm.project_id
               WHERE pm.user_id=? ORDER BY p.name""", (uid,)
        ).fetchall()
    conn.close()
    return render_template('new_check.html', projects=projects)


@app.route('/check/<int:check_id>')
@login_required
def view_check(check_id):
    conn = get_db()
    uid = session['user_id']
    if session['role'] == 'admin':
        chk = conn.execute('SELECT * FROM checks WHERE id=?', (check_id,)).fetchone()
    else:
        chk = conn.execute(
            """SELECT * FROM checks WHERE id=? AND (
                (project_id IS NULL AND user_id=?)
                OR (project_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM project_members
                    WHERE project_id=checks.project_id AND user_id=?
                ))
            )""",
            (check_id, uid, uid)
        ).fetchone()
    if not chk:
        conn.close()
        flash('Check not found or access revoked.', 'error')
        return redirect(url_for('dashboard'))

    metrics = conn.execute(
        'SELECT * FROM metric_details WHERE check_id=? ORDER BY metric_no',
        (check_id,)
    ).fetchall()
    conn.close()
    return render_template('view_check.html', chk=chk, metrics=metrics)


@app.route('/history')
@login_required
def history():
    conn  = get_db()
    uid   = session['user_id']
    role  = session['role']

    page     = max(1, request.args.get('page', 1, type=int))
    per_page = 10
    search   = request.args.get('q', '').strip()
    grade_f  = request.args.get('grade', '').strip().upper()

    # Build WHERE conditions and params
    conditions = []
    params: list = []

    if role != 'admin':
        conditions.append(
            "(c.project_id IS NULL AND c.user_id=?) OR "
            "(c.project_id IS NOT NULL AND EXISTS ("
            "  SELECT 1 FROM project_members pm "
            "  WHERE pm.project_id=c.project_id AND pm.user_id=?))"
        )
        params += [uid, uid]

    if search:
        conditions.append(
            "(c.project_name LIKE ? OR u.full_name LIKE ? OR u.username LIKE ? OR p.code LIKE ?)"
        )
        like = f'%{search}%'
        params += [like, like, like, like]

    if grade_f in ('GOOD', 'FAIR', 'POOR'):
        conditions.append("c.grade=?")
        params.append(grade_f)

    where = ("WHERE " + " AND ".join(f"({c})" for c in conditions)) if conditions else ""

    base_query = f"""
        SELECT DISTINCT c.*, u.username, u.full_name, u.role as user_role,
               p.name as admin_project_name, p.code as admin_project_code,
               pu.full_name as project_creator_name
        FROM checks c
        JOIN users u ON c.user_id=u.id
        LEFT JOIN projects p ON c.project_id=p.id
        LEFT JOIN users pu ON p.created_by=pu.id
        {where}
    """

    total = conn.execute(
        f"SELECT COUNT(*) FROM ({base_query})", params
    ).fetchone()[0]

    checks = conn.execute(
        base_query + " ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    admins_list = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id").fetchall()
    admin_num   = {row['id']: i + 1 for i, row in enumerate(admins_list)}

    # Compute per-project sequential run numbers for checks on this page
    project_run_nos = {}
    seen_projects   = set()
    for c in checks:
        pid = c['project_id']
        if pid is not None and pid not in seen_projects:
            seen_projects.add(pid)
            rows = conn.execute(
                "SELECT id FROM checks WHERE project_id=? ORDER BY created_at, id", (pid,)
            ).fetchall()
            for i, row in enumerate(rows):
                project_run_nos[row['id']] = i + 1

    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template('history.html', checks=checks,
                           page=page, total_pages=total_pages, total=total,
                           per_page=per_page, project_run_nos=project_run_nos,
                           search=search, grade_f=grade_f, admin_num=admin_num)


@app.route('/compare')
@login_required
def compare_checks():
    id1 = request.args.get('a', type=int)
    id2 = request.args.get('b', type=int)
    if not id1 or not id2:
        flash('Select two assessments to compare.', 'error')
        return redirect(url_for('history'))
    conn = get_db()
    uid  = session['user_id']
    if session['role'] == 'admin':
        chk1 = conn.execute('SELECT * FROM checks WHERE id=?', (id1,)).fetchone()
        chk2 = conn.execute('SELECT * FROM checks WHERE id=?', (id2,)).fetchone()
    else:
        _acc = """SELECT * FROM checks WHERE id=? AND (
            (project_id IS NULL AND user_id=?)
            OR (project_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM project_members WHERE project_id=checks.project_id AND user_id=?
            ))
        )"""
        chk1 = conn.execute(_acc, (id1, uid, uid)).fetchone()
        chk2 = conn.execute(_acc, (id2, uid, uid)).fetchone()
    if not chk1 or not chk2:
        conn.close()
        flash('One or both assessments not found.', 'error')
        return redirect(url_for('history'))
    metrics1 = conn.execute('SELECT * FROM metric_details WHERE check_id=? ORDER BY metric_no', (id1,)).fetchall()
    metrics2 = conn.execute('SELECT * FROM metric_details WHERE check_id=? ORDER BY metric_no', (id2,)).fetchall()
    conn.close()
    return render_template('compare.html', chk1=chk1, chk2=chk2,
                           metrics1=metrics1, metrics2=metrics2)


@app.route('/profile')
@login_required
def profile():
    conn  = get_db()
    uid   = session['user_id']
    user  = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    stats = conn.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN grade='GOOD' THEN 1 ELSE 0 END) as good_count,
                  MAX(created_at) as last_run
           FROM checks WHERE user_id=?""", (uid,)
    ).fetchone()
    conn.close()
    return render_template('profile.html', user=user, stats=stats)


@app.route('/profile/edit', methods=['POST'])
@login_required
def profile_edit():
    uid        = session['user_id']
    full_name  = request.form.get('full_name', '').strip()
    current_pw = request.form.get('current_password', '')
    new_pw     = request.form.get('new_password', '').strip()
    confirm_pw = request.form.get('confirm_password', '')

    if not full_name:
        flash('Name is required.', 'error')
        return redirect(url_for('profile'))

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()

    if new_pw:
        if not _check_password(user['password_hash'], current_pw):
            flash('Current password is incorrect.', 'error')
            conn.close()
            return redirect(url_for('profile'))
        pw_err = _validate_password(new_pw)
        if pw_err:
            flash(pw_err, 'error')
            conn.close()
            return redirect(url_for('profile'))
        if new_pw != confirm_pw:
            flash('New passwords do not match.', 'error')
            conn.close()
            return redirect(url_for('profile'))
        conn.execute(
            "UPDATE users SET full_name=?,password_hash=?,must_change_password=0 WHERE id=?",
            (full_name, _hash_password(new_pw), uid)
        )
        conn.commit()
        session['full_name'] = full_name
        session['must_change_password'] = False
        _audit('password_changed')
        flash('Profile and password updated successfully.', 'success')
    else:
        conn.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, uid))
        conn.commit()
        session['full_name'] = full_name
        flash('Profile updated successfully.', 'success')

    conn.close()
    return redirect(url_for('profile'))


# ── API — Detect projects in an XER file ─────────────────────────────────────
@app.route('/api/detect-projects', methods=['POST'])
@login_required
def api_detect_projects():
    if 'xer_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    f = request.files['xer_file']
    if not f.filename.lower().endswith('.xer'):
        return jsonify({'error': 'Only .xer files are accepted'}), 400

    os.makedirs(TMP_UPLOAD_DIR, exist_ok=True)
    token    = secrets.token_hex(16)
    tmp_path = os.path.join(TMP_UPLOAD_DIR, f'{token}.xer')
    filename = secure_filename(f.filename)

    f.save(tmp_path)

    # Save original filename alongside the temp file
    with open(os.path.join(TMP_UPLOAD_DIR, f'{token}.meta'), 'w') as mf:
        mf.write(filename)

    from xer_parser.xer_parser import XERParser
    projects = XERParser.get_projects(tmp_path)

    if len(projects) < 1:
        try:
            os.unlink(tmp_path)
            os.unlink(os.path.join(TMP_UPLOAD_DIR, f'{token}.meta'))
        except Exception:
            pass
        return jsonify({'error': 'No projects found in the XER file.'}), 400

    return jsonify({'token': token, 'filename': filename, 'projects': projects})


# ── API — XER Upload & Analysis ──────────────────────────────────────────────
@app.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    ip = request.remote_addr or '0.0.0.0'
    if not _analyze_rate_check(ip):
        return jsonify({'error': 'Too many analysis requests. Please wait a few minutes.'}), 429

    token           = request.form.get('upload_token', '').strip()
    actual_proj_id  = request.form.get('actual_proj_id', '').strip() or None
    baseline_proj_id= request.form.get('baseline_proj_id', '').strip() or None
    project_id_raw  = request.form.get('project_id', '').strip()
    project_id      = int(project_id_raw) if project_id_raw.isdigit() else None

    thresholds_raw = request.form.get('thresholds', '{}')
    try:
        thresholds = json.loads(thresholds_raw)
    except (json.JSONDecodeError, TypeError):
        thresholds = {}

    enabled_metrics_raw = request.form.get('enabled_metrics', '[]')
    try:
        enabled_metrics = set(int(x) for x in json.loads(enabled_metrics_raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        enabled_metrics = None  # None = all enabled

    if not token:
        return jsonify({'error': 'Missing upload token. Please upload the file first.'}), 400

    if not project_id:
        return jsonify({'error': 'A project must be selected before running an assessment.'}), 400

    # Verify the user belongs to the selected project (admins are exempt)
    if session.get('role') != 'admin':
        conn = get_db()
        member = conn.execute(
            "SELECT 1 FROM project_members WHERE project_id=? AND user_id=?",
            (project_id, session['user_id'])
        ).fetchone()
        conn.close()
        if not member:
            return jsonify({'error': 'You are not a member of the selected project.'}), 403

    tmp_path  = os.path.join(TMP_UPLOAD_DIR, f'{token}.xer')
    meta_path = os.path.join(TMP_UPLOAD_DIR, f'{token}.meta')

    if not os.path.exists(tmp_path):
        return jsonify({'error': 'Upload session expired. Please re-upload the file.'}), 400

    # Read filename stored during detect-projects
    try:
        with open(meta_path) as mf:
            filename = mf.read().strip()
    except Exception:
        filename = 'schedule.xer'

    # Read raw bytes now so we can store in DB after analysis
    with open(tmp_path, 'rb') as fh:
        xer_bytes = fh.read()

    # Run analysis — data date is auto-extracted from the actual project
    try:
        result = _run_analysis(tmp_path, None, thresholds,
                               actual_proj_id, baseline_proj_id,
                               enabled_metrics=enabled_metrics)
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500
    finally:
        # Clean up temp staging files
        for p in (tmp_path, meta_path):
            try:
                os.unlink(p)
            except Exception:
                pass

    baseline_proj_name = result.get('baseline_proj_name', '') if baseline_proj_id else ''
    baseline_data_date = result.get('baseline_data_date', '') if baseline_proj_id else ''

    # Persist to DB (XER stored as BLOB)
    try:
        conn = get_db()
        cur  = conn.cursor()
        # Use auto-extracted data date from the actual project
        extracted_date = result.get('data_date') or None
        if extracted_date == 'N/A':
            extracted_date = None

        cur.execute(
            """INSERT INTO checks
               (user_id, project_id, project_name, xer_filename, xer_blob,
                actual_proj_id, baseline_proj_id, baseline_proj_name,
                data_date, baseline_data_date, activities, relationships,
                score, grade, passed, total_metrics, results_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session['user_id'], project_id,
             result['project_name'], filename, xer_bytes,
             actual_proj_id or '', baseline_proj_id or '', baseline_proj_name,
             extracted_date, baseline_data_date or '',
             result['activity_count'], result['relationship_count'],
             result['score'], result['grade'],
             result['passed'], result['total'],
             json.dumps(result))
        )
        check_id = cur.lastrowid

        for m in result['metrics']:
            cur.execute(
                """INSERT INTO metric_details
                   (check_id,metric_no,metric_name,status,violations,total,percentage,details_json)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (check_id, m.get('metric_no', 0), m['metric'],
                 m['status'], m['violations'], m['total'],
                 m['percentage'], json.dumps(m.get('details', [])))
            )
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({'error': f'Database error: {str(e)}'}), 500

    _audit('analysis_run', result.get('project_name', ''))
    result['check_id'] = check_id
    return jsonify(result)


# ── API — Download original XER ───────────────────────────────────────────────
@app.route('/api/check/<int:check_id>/download-xer')
@login_required
def download_xer(check_id):
    conn = get_db()
    uid  = session['user_id']
    if session['role'] == 'admin':
        chk = conn.execute(
            'SELECT xer_filename, xer_blob FROM checks WHERE id=?', (check_id,)
        ).fetchone()
    else:
        chk = conn.execute(
            """SELECT xer_filename, xer_blob FROM checks WHERE id=? AND (
                (project_id IS NULL AND user_id=?)
                OR (project_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM project_members WHERE project_id=checks.project_id AND user_id=?
                ))
            )""", (check_id, uid, uid)
        ).fetchone()
    conn.close()

    if not chk:
        return jsonify({'error': 'Not found'}), 404
    if not chk['xer_blob']:
        return jsonify({'error': 'XER file not stored for this assessment'}), 404

    _audit('download_xer', str(check_id))
    return Response(
        bytes(chk['xer_blob']),
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{chk["xer_filename"]}"'}
    )


# ── API — Download XER without redundant relationships ───────────────────────
@app.route('/api/check/<int:check_id>/download-clean-xer')
@login_required
def download_clean_xer(check_id):
    conn = get_db()
    uid  = session['user_id']
    if session['role'] == 'admin':
        chk = conn.execute('SELECT * FROM checks WHERE id=?', (check_id,)).fetchone()
    else:
        chk = conn.execute(
            """SELECT * FROM checks WHERE id=? AND (
                (project_id IS NULL AND user_id=?)
                OR (project_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM project_members WHERE project_id=checks.project_id AND user_id=?
                ))
            )""", (check_id, uid, uid)
        ).fetchone()
    conn.close()
    if not chk:
        return jsonify({'error': 'Not found'}), 404

    if not chk['xer_blob']:
        # Fallback: try filesystem for older checks
        xer_path = os.path.join(UPLOAD_DIR, chk['xer_filename'])
        if not os.path.exists(xer_path):
            return jsonify({'error': 'Original XER file not found'}), 404
        use_tmp = False
    else:
        # Write BLOB to a temp file for text-mode processing
        tmp = tempfile.NamedTemporaryFile(suffix='.xer', delete=False)
        tmp.write(bytes(chk['xer_blob']))
        tmp.close()
        xer_path = tmp.name
        use_tmp  = True

    # Get the redundant pairs (pred_code, succ_code) stored in results_json
    try:
        results  = json.loads(chk['results_json'])
        bonus    = results.get('bonus', {})
        details  = bonus.get('details', [])
        redundant_pairs = {(d['pred_code'], d['succ_code']) for d in details}
    except Exception:
        return jsonify({'error': 'Could not read redundant relationship data'}), 500

    if not redundant_pairs:
        return jsonify({'error': 'No redundant relationships found in this assessment'}), 400

    # Parse XER to build task_id → task_code map, filtered to the actual project.
    # Without filtering, baseline and actual share the same task_code values and
    # the dict ends up mapping codes to the wrong project's task IDs.
    filter_proj_id = (chk['actual_proj_id'] or chk['baseline_proj_id'] or '').strip()

    # task_code → set of task_ids (per-project filtering applied below)
    # We keep code → task_id only for the target project.
    task_id_to_code = {}   # task_id → task_code  (target project only)
    current_table   = None
    current_cols    = []

    with open(xer_path, 'r', encoding='latin-1') as fh:
        for line in fh:
            s = line.rstrip('\r\n')
            if s.startswith('%T\t'):
                current_table = s.split('\t', 1)[1].strip()
                current_cols  = []
            elif s.startswith('%F\t') and current_table:
                current_cols = s.split('\t')[1:]
            elif s.startswith('%R\t') and current_table == 'TASK' and current_cols:
                vals     = s.split('\t')[1:]
                tid_idx  = current_cols.index('task_id')   if 'task_id'   in current_cols else -1
                code_idx = current_cols.index('task_code') if 'task_code' in current_cols else -1
                proj_idx = current_cols.index('proj_id')   if 'proj_id'   in current_cols else -1
                if tid_idx < 0 or code_idx < 0:
                    continue
                if tid_idx >= len(vals) or code_idx >= len(vals):
                    continue
                # Only collect tasks from the actual project (avoids code collisions
                # between actual and baseline which often share the same task codes)
                if filter_proj_id and proj_idx >= 0 and proj_idx < len(vals):
                    if vals[proj_idx].strip() != filter_proj_id:
                        continue
                task_id_to_code[vals[tid_idx].strip()] = vals[code_idx].strip()

    # Build set of (pred_task_id, succ_task_id) to remove
    code_to_task_id = {v: k for k, v in task_id_to_code.items()}
    pairs_to_remove = set()
    for pred_code, succ_code in redundant_pairs:
        pred_id = code_to_task_id.get(pred_code)
        succ_id = code_to_task_id.get(succ_code)
        if pred_id and succ_id:
            pairs_to_remove.add((pred_id, succ_id))

    # Second pass: rewrite file, dropping matched TASKPRED rows
    current_table = None
    current_cols  = []
    removed       = 0
    output_lines  = []

    with open(xer_path, 'r', encoding='latin-1') as fh:
        for line in fh:
            s = line.rstrip('\r\n')
            if s.startswith('%T\t'):
                current_table = s.split('\t', 1)[1].strip()
                current_cols  = []
                output_lines.append(line)
            elif s.startswith('%F\t') and current_table:
                current_cols = s.split('\t')[1:]
                output_lines.append(line)
            elif s.startswith('%R\t') and current_table == 'TASKPRED' and current_cols:
                vals     = s.split('\t')[1:]
                pred_idx = current_cols.index('pred_task_id') if 'pred_task_id' in current_cols else -1
                succ_idx = current_cols.index('task_id')      if 'task_id'      in current_cols else -1
                if pred_idx >= 0 and succ_idx >= 0 and pred_idx < len(vals) and succ_idx < len(vals):
                    pair = (vals[pred_idx].strip(), vals[succ_idx].strip())
                    if pair in pairs_to_remove:
                        removed += 1
                        continue   # drop this row
                output_lines.append(line)
            else:
                output_lines.append(line)

    content  = ''.join(output_lines).encode('latin-1')
    base     = chk['xer_filename'].rsplit('.', 1)[0]
    out_name = f"{base}_no_redundant.xer"

    if use_tmp:
        try:
            os.unlink(xer_path)
        except Exception:
            pass

    _audit('download_clean_xer', str(check_id))
    return Response(
        content,
        mimetype='application/octet-stream',
        headers={
            'Content-Disposition': f'attachment; filename="{out_name}"',
            'X-Removed-Count': str(removed),
        }
    )


# ── API — CSV Export ──────────────────────────────────────────────────────────
@app.route('/api/check/<int:check_id>/export.csv')
@login_required
def export_csv(check_id):
    conn = get_db()
    uid  = session['user_id']
    if session['role'] == 'admin':
        chk = conn.execute('SELECT * FROM checks WHERE id=?', (check_id,)).fetchone()
    else:
        chk = conn.execute(
            """SELECT * FROM checks WHERE id=? AND (
                (project_id IS NULL AND user_id=?)
                OR (project_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM project_members WHERE project_id=checks.project_id AND user_id=?
                ))
            )""", (check_id, uid, uid)
        ).fetchone()
    if not chk:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    metrics = conn.execute('SELECT * FROM metric_details WHERE check_id=? ORDER BY metric_no',
                           (check_id,)).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)

    # Summary header
    w.writerow(['JESA DCMA Assessment — Punch List Export'])
    w.writerow([])
    w.writerow(['Project',      chk['project_name']])
    w.writerow(['File',         chk['xer_filename']])
    w.writerow(['Score',        str(chk['score']) + '%'])
    w.writerow(['Grade',        chk['grade']])
    w.writerow(['Passing',      f"{chk['passed']}/{chk['total_metrics']}"])
    w.writerow(['Data Date',    chk['data_date'] or 'N/A'])
    w.writerow(['Run At',       chk['created_at'][:16]])
    w.writerow([])

    # Metric summary
    w.writerow(['--- METRIC SUMMARY ---'])
    w.writerow(['#', 'Metric', 'Status', 'Total Checked', 'Violations', 'Rate %'])
    for m in metrics:
        w.writerow([m['metric_no'], m['metric_name'], m['status'],
                    m['total'], m['violations'], m['percentage']])
    w.writerow([])

    # Violation punch list
    w.writerow(['--- VIOLATION PUNCH LIST ---'])
    w.writerow(['Metric #', 'Metric Name', 'Activity / Relationship', 'Issue'])
    for m in metrics:
        if m['violations'] > 0:
            try:
                details = json.loads(m['details_json'])
                for d in details:
                    if d.get('task_code'):
                        label = d.get('task_name') or d['task_code']
                    elif d.get('pred_code'):
                        pn = d.get('pred_name') or d['pred_code']
                        sn = d.get('succ_name') or d.get('succ_code', '?')
                        label = f"{pn} -> {sn}"
                    else:
                        label = '?'
                    w.writerow([m['metric_no'], m['metric_name'], label, d.get('issue', '')])
            except Exception:
                pass

    out.seek(0)
    safe_name = ''.join(c for c in chk['project_name'] if c.isalnum() or c in '-_ ')[:40]
    filename  = f"DCMA_{safe_name}_{chk['created_at'][:10]}.csv"
    _audit('export_csv', str(check_id))
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


# ── API — Excel Export (XER data + DCMA results) ─────────────────────────────
@app.route('/api/check/<int:check_id>/export.xlsx')
@login_required
def export_xlsx(check_id):
    conn = get_db()
    uid  = session['user_id']
    if session['role'] == 'admin':
        chk = conn.execute('SELECT * FROM checks WHERE id=?', (check_id,)).fetchone()
    else:
        chk = conn.execute(
            """SELECT * FROM checks WHERE id=? AND (
                (project_id IS NULL AND user_id=?)
                OR (project_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM project_members WHERE project_id=checks.project_id AND user_id=?
                ))
            )""", (check_id, uid, uid)
        ).fetchone()
    if not chk:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    metrics = conn.execute(
        'SELECT * FROM metric_details WHERE check_id=? ORDER BY metric_no', (check_id,)
    ).fetchall()
    conn.close()

    if not chk['xer_blob']:
        # Fallback: try filesystem for older checks
        xer_path = os.path.join(UPLOAD_DIR, chk['xer_filename'])
        if not os.path.exists(xer_path):
            return jsonify({'error': 'Original XER file not found on server'}), 404
        xlsx_tmp = None
    else:
        # Write BLOB to temp file for parsing
        _tf = tempfile.NamedTemporaryFile(suffix='.xer', delete=False)
        _tf.write(bytes(chk['xer_blob']))
        _tf.close()
        xer_path = _tf.name
        xlsx_tmp = xer_path

    # Re-parse the XER to get raw activity / relationship data
    from xer_parser.xer_parser import XERParser
    actual_proj_id   = chk['actual_proj_id']   if chk['actual_proj_id']   else None
    baseline_proj_id = chk['baseline_proj_id'] if chk['baseline_proj_id'] else None
    parser = XERParser(xer_path)
    parser.parse(actual_proj_id=actual_proj_id, baseline_proj_id=baseline_proj_id)

    # ── Workbook & styles ────────────────────────────────────────────────────
    wb = openpyxl.Workbook()

    HDR_FILL   = PatternFill('solid', fgColor='1F3864')   # dark navy
    HDR_FONT   = Font(color='FFFFFF', bold=True, size=10)
    TITLE_FONT = Font(color='1F3864', bold=True, size=13)
    PASS_FILL  = PatternFill('solid', fgColor='C6EFCE')
    FAIL_FILL  = PatternFill('solid', fgColor='FFC7CE')
    ALT_FILL   = PatternFill('solid', fgColor='EEF2F7')
    CENTER     = Alignment(horizontal='center', vertical='center')
    LEFT       = Alignment(horizontal='left',   vertical='center', wrap_text=True)
    thin       = Side(style='thin', color='BFBFBF')
    BORDER     = Border(left=thin, right=thin, top=thin, bottom=thin)

    def style_header_row(ws, row_no, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=row_no, column=c)
            cell.fill      = HDR_FILL
            cell.font      = HDR_FONT
            cell.alignment = CENTER
            cell.border    = BORDER

    def auto_width(ws, min_w=8, max_w=40):
        for col in ws.columns:
            length = max(
                len(str(cell.value)) if cell.value is not None else 0
                for cell in col
            )
            ws.column_dimensions[get_column_letter(col[0].column)].width = \
                min(max(length + 2, min_w), max_w)

    def style_data_row(ws, row_no, ncols, alt=False):
        fill = ALT_FILL if alt else None
        for c in range(1, ncols + 1):
            cell = ws.cell(row=row_no, column=c)
            if fill:
                cell.fill = fill
            cell.alignment = LEFT
            cell.border    = BORDER

    # ── Sheet 1 — Summary ────────────────────────────────────────────────────
    ws = wb.active
    ws.title = 'Summary'
    ws.sheet_view.showGridLines = False

    ws.merge_cells('A1:D1')
    ws['A1'] = 'JESA DCMA 14-Point Assessment'
    ws['A1'].font      = Font(bold=True, size=16, color='1F3864')
    ws['A1'].alignment = CENTER
    ws.row_dimensions[1].height = 30

    rows = [
        ('Project',       chk['project_name']),
        ('XER File',      chk['xer_filename']),
        ('Data Date',     chk['data_date'] or 'N/A'),
        ('Run At',        chk['created_at'][:16]),
        ('Activities',    chk['activities']),
        ('Relationships', chk['relationships']),
        ('Score',         f"{chk['score']}%"),
        ('Grade',         chk['grade']),
        ('Passed / Total',f"{chk['passed']} / {chk['total_metrics']}"),
    ]
    for i, (label, value) in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=label).font  = Font(bold=True, color='1F3864')
        ws.cell(row=i, column=1).alignment           = LEFT
        ws.cell(row=i, column=2, value=value).alignment = LEFT
        ws.cell(row=i, column=2).border              = BORDER
        ws.cell(row=i, column=1).border              = BORDER
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 35

    # ── Sheet 2 — Activities ─────────────────────────────────────────────────
    ws2 = wb.create_sheet('Activities')
    ws2.sheet_view.showGridLines = False

    act_headers = [
        'Activity ID', 'Activity Name', 'Type', 'Status',
        'Start', 'Finish', 'Actual Start', 'Actual Finish',
        'Baseline Start', 'Baseline Finish',
        'Duration (h)', 'Remaining (h)', 'Total Float (h)', 'Free Float (h)',
        'Constraint', 'Constraint Date', 'Has Resource',
    ]
    for c, h in enumerate(act_headers, 1):
        ws2.cell(row=1, column=c, value=h)
    style_header_row(ws2, 1, len(act_headers))
    ws2.freeze_panes = 'A2'

    for r, act in enumerate(parser.activities.values(), start=2):
        vals = [
            act.task_code, act.task_name, act.task_type, act.status_code,
            act.start, act.finish, act.act_start, act.act_finish,
            act.bl_start, act.bl_finish,
            act.duration, act.remaining_dur, act.total_float, act.free_float,
            act.constraint, act.constraint_date,
            'Yes' if act.has_resource else 'No',
        ]
        for c, v in enumerate(vals, 1):
            ws2.cell(row=r, column=c, value=v)
        style_data_row(ws2, r, len(act_headers), alt=(r % 2 == 0))

    auto_width(ws2)

    # ── Sheet 3 — Relationships ──────────────────────────────────────────────
    ws3 = wb.create_sheet('Relationships')
    ws3.sheet_view.showGridLines = False

    rel_headers = ['Predecessor ID', 'Successor ID', 'Type', 'Lag (h)']
    # Build task_id → code lookup
    id_to_code = {a.task_id: a.task_code for a in parser.activities.values()}

    for c, h in enumerate(rel_headers, 1):
        ws3.cell(row=1, column=c, value=h)
    style_header_row(ws3, 1, len(rel_headers))
    ws3.freeze_panes = 'A2'

    for r, rel in enumerate(parser.relationships, start=2):
        vals = [
            id_to_code.get(rel.pred_task_id, rel.pred_task_id),
            id_to_code.get(rel.succ_task_id, rel.succ_task_id),
            rel.pred_type,
            rel.lag,
        ]
        for c, v in enumerate(vals, 1):
            ws3.cell(row=r, column=c, value=v)
        style_data_row(ws3, r, len(rel_headers), alt=(r % 2 == 0))

    auto_width(ws3)

    # ── Sheet 4 — DCMA Results ───────────────────────────────────────────────
    ws4 = wb.create_sheet('DCMA Results')
    ws4.sheet_view.showGridLines = False

    res_headers = ['#', 'Metric', 'Status', 'Total Checked', 'Violations', 'Rate %']
    for c, h in enumerate(res_headers, 1):
        ws4.cell(row=1, column=c, value=h)
    style_header_row(ws4, 1, len(res_headers))
    ws4.freeze_panes = 'A2'

    for r, m in enumerate(metrics, start=2):
        vals = [m['metric_no'], m['metric_name'], m['status'],
                m['total'], m['violations'], round(m['percentage'], 1)]
        for c, v in enumerate(vals, 1):
            ws4.cell(row=r, column=c, value=v)
        # Colour status cell
        status_cell = ws4.cell(row=r, column=3)
        status_cell.fill = PASS_FILL if m['status'] == 'PASS' else FAIL_FILL
        style_data_row(ws4, r, len(res_headers), alt=(r % 2 == 0))
        # Re-apply status fill after style_data_row (which may overwrite)
        status_cell.fill = PASS_FILL if m['status'] == 'PASS' else FAIL_FILL

    auto_width(ws4)

    # ── Sheet 5 — Violation Punch List ───────────────────────────────────────
    ws5 = wb.create_sheet('Punch List')
    ws5.sheet_view.showGridLines = False

    pl_headers = ['Metric #', 'Metric Name', 'Activity / Relationship', 'Issue']
    for c, h in enumerate(pl_headers, 1):
        ws5.cell(row=1, column=c, value=h)
    style_header_row(ws5, 1, len(pl_headers))
    ws5.freeze_panes = 'A2'

    row_idx = 2
    for m in metrics:
        if m['violations'] > 0:
            try:
                details = json.loads(m['details_json'])
                for d in details:
                    if d.get('task_code'):
                        label = d.get('task_name') or d['task_code']
                    elif d.get('pred_code'):
                        pn = d.get('pred_name') or d['pred_code']
                        sn = d.get('succ_name') or d.get('succ_code', '?')
                        label = f"{pn} → {sn}"
                    else:
                        label = '?'
                    vals = [m['metric_no'], m['metric_name'], label, d.get('issue', '')]
                    for c, v in enumerate(vals, 1):
                        ws5.cell(row=row_idx, column=c, value=v)
                    style_data_row(ws5, row_idx, len(pl_headers),
                                   alt=(row_idx % 2 == 0))
                    row_idx += 1
            except Exception:
                pass

    auto_width(ws5)

    # ── Stream response ──────────────────────────────────────────────────────
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    if xlsx_tmp:
        try:
            os.unlink(xlsx_tmp)
        except Exception:
            pass

    safe_name = ''.join(c for c in chk['project_name'] if c.isalnum() or c in '-_ ')[:40]
    fname = f"DCMA_{safe_name}_{chk['created_at'][:10]}.xlsx"

    _audit('export_xlsx', str(check_id))
    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )


# ── API — Delete check (admin only) ──────────────────────────────────────────
@app.route('/api/check/<int:check_id>', methods=['DELETE'])
@admin_required
def api_delete_check(check_id):
    conn = get_db()
    conn.execute('DELETE FROM metric_details WHERE check_id=?', (check_id,))
    conn.execute('DELETE FROM checks WHERE id=?', (check_id,))
    conn.commit()
    conn.close()
    _audit('check_deleted', str(check_id))
    return jsonify({'ok': True})


# ── Admin — Projects & Users ─────────────────────────────────────────────────
@app.route('/admin/projects', methods=['GET', 'POST'])
@admin_required
def admin_projects():
    conn = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip().upper()
        desc = request.form.get('description', '').strip()
        if name:
            try:
                conn.execute(
                    "INSERT INTO projects (name,code,description,created_by) VALUES (?,?,?,?)",
                    (name, code, desc, session['user_id'])
                )
                conn.commit()
                _audit('project_created', name)
                flash(f'Project "{name}" created successfully.', 'success')
            except sqlite3.IntegrityError:
                flash(f'Project code "{code}" is already in use. Use a unique code.', 'error')
            except Exception as e:
                flash(f'Error creating project: {e}', 'error')
        conn.close()
        return redirect(url_for('admin_projects'))

    projects = conn.execute(
        """SELECT p.*, u.full_name as creator,
                  COUNT(DISTINCT pm.user_id) as member_count,
                  COUNT(DISTINCT c.id) as run_count
           FROM projects p
           LEFT JOIN users u ON p.created_by=u.id
           LEFT JOIN project_members pm ON p.id=pm.project_id
           LEFT JOIN checks c ON p.id=c.project_id
           GROUP BY p.id ORDER BY p.created_at DESC"""
    ).fetchall()
    admins_list = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id").fetchall()
    admin_num = {row['id']: i + 1 for i, row in enumerate(admins_list)}
    conn.close()
    return render_template('admin_projects.html', projects=projects, admin_num=admin_num)


@app.route('/admin/projects/<int:proj_id>')
@admin_required
def admin_project_detail(proj_id):
    conn = get_db()
    project = conn.execute('SELECT * FROM projects WHERE id=?', (proj_id,)).fetchone()
    if not project:
        conn.close()
        flash('Project not found.', 'error')
        return redirect(url_for('admin_projects'))
    members = conn.execute(
        """SELECT u.*, pm.added_at FROM users u
           JOIN project_members pm ON u.id=pm.user_id
           WHERE pm.project_id=? ORDER BY u.full_name""", (proj_id,)
    ).fetchall()
    all_users = conn.execute(
        """SELECT * FROM users WHERE id NOT IN
           (SELECT user_id FROM project_members WHERE project_id=?)
           ORDER BY full_name""", (proj_id,)
    ).fetchall()
    runs = conn.execute(
        """SELECT c.*, u.full_name as runner FROM checks c
           JOIN users u ON c.user_id=u.id
           WHERE c.project_id=? ORDER BY c.created_at DESC LIMIT 20""", (proj_id,)
    ).fetchall()
    grade_stats = conn.execute(
        """SELECT COUNT(*) as total_count,
                  SUM(CASE WHEN grade='GOOD' THEN 1 ELSE 0 END) as good_count,
                  SUM(CASE WHEN grade='FAIR' THEN 1 ELSE 0 END) as fair_count,
                  SUM(CASE WHEN grade='POOR' THEN 1 ELSE 0 END) as poor_count
           FROM checks WHERE project_id=?""", (proj_id,)
    ).fetchone()
    conn.close()
    return render_template('admin_project_detail.html', project=project,
                           members=members, all_users=all_users, runs=runs,
                           grade_stats=grade_stats)


@app.route('/admin/projects/<int:proj_id>/add-member', methods=['POST'])
@admin_required
def admin_add_member(proj_id):
    user_id = request.form.get('user_id', type=int)
    if user_id:
        conn = get_db()
        try:
            conn.execute("INSERT INTO project_members (project_id,user_id) VALUES (?,?)",
                         (proj_id, user_id))
            conn.commit()
        except Exception:
            pass
        conn.close()
    return redirect(url_for('admin_project_detail', proj_id=proj_id))


@app.route('/admin/projects/<int:proj_id>/remove-member', methods=['POST'])
@admin_required
def admin_remove_member(proj_id):
    user_id = request.form.get('user_id', type=int)
    if user_id:
        conn = get_db()
        conn.execute("DELETE FROM project_members WHERE project_id=? AND user_id=?",
                     (proj_id, user_id))
        conn.commit()
        conn.close()
    return redirect(url_for('admin_project_detail', proj_id=proj_id))


@app.route('/admin/projects/<int:proj_id>/delete', methods=['POST'])
@admin_required
def admin_delete_project(proj_id):
    conn = get_db()
    proj = conn.execute('SELECT name FROM projects WHERE id=?', (proj_id,)).fetchone()
    if proj:
        # Cascade: delete all metric_details then checks for this project
        check_rows = conn.execute(
            'SELECT id FROM checks WHERE project_id=?', (proj_id,)
        ).fetchall()
        if check_rows:
            ids = [r['id'] for r in check_rows]
            conn.execute(
                f"DELETE FROM metric_details WHERE check_id IN ({','.join('?'*len(ids))})", ids
            )
            conn.execute('DELETE FROM checks WHERE project_id=?', (proj_id,))
        conn.execute('DELETE FROM project_members WHERE project_id=?', (proj_id,))
        conn.execute('DELETE FROM projects WHERE id=?', (proj_id,))
        conn.commit()
        _audit('project_deleted', proj['name'])
        flash(f'Project "{proj["name"]}" and all its assessments deleted.', 'success')
    conn.close()
    return redirect(url_for('admin_projects'))


@app.route('/admin/users/create', methods=['POST'])
@admin_required
def admin_user_create():
    username  = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role      = request.form.get('role', 'engineer')
    password  = request.form.get('password', '')
    confirm   = request.form.get('confirm', '')

    if role not in ('admin', 'engineer'):
        role = 'engineer'
    if not username or not full_name or not password:
        flash('All fields are required.', 'error')
        return redirect(url_for('admin_users'))
    pw_err = _validate_password(password)
    if pw_err:
        flash(pw_err, 'error')
        return redirect(url_for('admin_users'))
    if password != confirm:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('admin_users'))

    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO users (username,full_name,email,role,password_hash)
               VALUES (?,?,?,?,?)""",
            (username, full_name, f'{username}@jesa.internal', role, _hash_password(password))
        )
        conn.commit()
        conn.close()
        _audit('user_created', username)
        flash(f'User "{username}" created successfully as {role}.', 'success')
    except sqlite3.IntegrityError:
        flash('Username already exists.', 'error')
    return redirect(url_for('admin_users'))


@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute(
        """SELECT u.*, COUNT(DISTINCT c.id) as run_count,
                  COUNT(DISTINCT pm.project_id) as project_count
           FROM users u
           LEFT JOIN checks c ON u.id=c.user_id
           LEFT JOIN project_members pm ON u.id=pm.user_id
           GROUP BY u.id ORDER BY u.created_at DESC"""
    ).fetchall()
    admins_list = conn.execute("SELECT id FROM users WHERE role='admin' ORDER BY id").fetchall()
    admin_num   = {row['id']: i + 1 for i, row in enumerate(admins_list)}
    conn.close()
    return render_template('admin_users.html', users=users, admin_num=admin_num)


@app.route('/admin/users/<int:user_id>/toggle-role', methods=['POST'])
@admin_required
def admin_toggle_role(user_id):
    if user_id == session['user_id']:
        flash('You cannot change your own role.', 'error')
        return redirect(url_for('admin_users'))
    conn = get_db()
    user = conn.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    if user:
        new_role = 'engineer' if user['role'] == 'admin' else 'admin'
        conn.execute('UPDATE users SET role=? WHERE id=?', (new_role, user_id))
        conn.commit()
    conn.close()
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        conn.close()
        flash('User not found.', 'error')
        return redirect(url_for('admin_users'))
    user_projects = conn.execute(
        """SELECT p.*, pm.added_at FROM projects p
           JOIN project_members pm ON p.id=pm.project_id
           WHERE pm.user_id=? ORDER BY p.name""", (user_id,)
    ).fetchall()
    recent_runs = conn.execute(
        "SELECT * FROM checks WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,)
    ).fetchall()
    run_stats = conn.execute(
        """SELECT COUNT(*) as total,
                  SUM(CASE WHEN grade='GOOD' THEN 1 ELSE 0 END) as good_count,
                  MAX(created_at) as last_run
           FROM checks WHERE user_id=?""", (user_id,)
    ).fetchone()
    conn.close()
    return render_template('admin_user_edit.html', user=user,
                           user_projects=user_projects, recent_runs=recent_runs,
                           run_stats=run_stats)


@app.route('/admin/users/<int:user_id>/edit', methods=['POST'])
@admin_required
def admin_user_edit(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        conn.close()
        flash('User not found.', 'error')
        return redirect(url_for('admin_users'))

    full_name    = request.form.get('full_name', '').strip()
    username     = request.form.get('username', '').strip()
    role         = request.form.get('role', 'engineer')
    new_password = request.form.get('new_password', '').strip()

    if not full_name or not username:
        flash('Name and username are required.', 'error')
        conn.close()
        return redirect(url_for('admin_user_detail', user_id=user_id))

    if role not in ('admin', 'engineer'):
        role = 'engineer'
    if user_id == session['user_id'] and role != 'admin':
        flash('You cannot remove your own admin role.', 'error')
        conn.close()
        return redirect(url_for('admin_user_detail', user_id=user_id))

    try:
        if new_password:
            pw_err = _validate_password(new_password)
            if pw_err:
                flash(pw_err, 'error')
                conn.close()
                return redirect(url_for('admin_user_detail', user_id=user_id))
            conn.execute(
                """UPDATE users SET full_name=?,username=?,role=?,
                   password_hash=?,must_change_password=0 WHERE id=?""",
                (full_name, username, role, _hash_password(new_password), user_id)
            )
        else:
            conn.execute(
                "UPDATE users SET full_name=?,username=?,role=? WHERE id=?",
                (full_name, username, role, user_id)
            )
        conn.commit()
        if user_id == session['user_id']:
            session['full_name'] = full_name
            session['username']  = username
            session['role']      = role
        _audit('user_edited', username)
        flash(f'User "{username}" updated successfully.', 'success')
    except sqlite3.IntegrityError:
        flash('Username already in use by another account.', 'error')

    conn.close()
    return redirect(url_for('admin_user_detail', user_id=user_id))


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_user_delete(user_id):
    if user_id == session['user_id']:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_users'))
    conn = get_db()
    user = conn.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()
    if user:
        conn.execute('DELETE FROM project_members WHERE user_id=?', (user_id,))
        conn.execute('UPDATE checks SET user_id=? WHERE user_id=?',
                     (session['user_id'], user_id))
        conn.execute('DELETE FROM users WHERE id=?', (user_id,))
        conn.commit()
        _audit('user_deleted', user['username'])
        flash(f'User "{user["username"]}" deleted. Their assessments transferred to you.', 'success')
    conn.close()
    return redirect(url_for('admin_users'))


# ── Core analysis runner ─────────────────────────────────────────────────────
def _run_analysis(xer_path, data_date, thresholds=None,
                  actual_proj_id=None, baseline_proj_id=None,
                  enabled_metrics=None):
    if thresholds is None:
        thresholds = {}

    from xer_parser.xer_parser import XERParser
    from metrics.open_ends             import check_open_ends
    from metrics.leads                 import check_leads
    from metrics.lags                  import check_lags
    from metrics.relationship_types    import check_relationship_types
    from metrics.hard_constraints      import check_hard_constraints
    from metrics.high_float            import check_high_float
    from metrics.negative_float        import check_negative_float
    from metrics.long_duration         import check_long_duration
    from metrics.invalid_dates         import check_invalid_dates
    from metrics.resources             import check_resources
    from metrics.remaining_metrics     import (check_missed_tasks,
                                               check_critical_path_test,
                                               check_critical_path,
                                               check_bei)
    from metrics.redundant_relationships import check_redundant_relationships

    parser = XERParser(xer_path)
    parser.parse(actual_proj_id=actual_proj_id, baseline_proj_id=baseline_proj_id)
    acts = parser.activities
    rels = parser.relationships
    dd   = data_date or parser.project_info.get('data_date')
    hpd  = parser.hours_per_day   # calendar hours/day — used for hour→day conversions

    # Helper to safely get numeric thresholds
    def _g(key, default=None):
        v = thresholds.get(key)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
        return default

    raw_metrics = [
        check_open_ends(acts, threshold_pct=_g('m1_pct')),                                         # #1  Logic
        check_leads(acts, rels, threshold_pct=_g('m2_pct')),                                        # #2  Leads
        check_lags(acts, rels, threshold_pct=_g('m3_pct'), hours_per_day=hpd),                     # #3  Lags
        check_relationship_types(acts, rels, fs_min_pct=_g('m4_fs_pct')),                          # #4  Relationships
        check_hard_constraints(acts, threshold_pct=_g('m5_pct')),                                   # #5  Hard Constraints
        check_high_float(acts, float_days=_g('m6_days'), threshold_pct=_g('m6_pct'),
                         hours_per_day=hpd),                                                        # #6  High Float
        check_negative_float(acts, threshold_pct=_g('m7_pct'), hours_per_day=hpd),                 # #7  Negative Float
        check_long_duration(acts, duration_days=_g('m8_days'), threshold_pct=_g('m8_pct'),
                            hours_per_day=hpd),                                                     # #8  High Duration
        check_invalid_dates(acts, dd, threshold_pct=_g('m9_pct')),                                 # #9  Invalid Dates
        check_resources(acts, threshold_pct=_g('m10_pct')),                                         # #10 Resources
        check_missed_tasks(acts, dd, threshold_pct=_g('m11_pct')),                                 # #11 Missed Tasks
        check_critical_path_test(acts, rels),                                                        # #12 Critical Path Test
        check_critical_path(acts, dd, cpli_threshold=_g('m13_cpli'), hours_per_day=hpd),           # #13 CPLI
        check_bei(acts, dd, bei_threshold=_g('m14_bei')),                                           # #14 BEI
    ]

    # Annotate with metric number
    for i, m in enumerate(raw_metrics, 1):
        m['metric_no'] = i

    # Filter to enabled metrics only
    if enabled_metrics is not None:
        raw_metrics = [m for m in raw_metrics if m['metric_no'] in enabled_metrics]

    passed     = sum(1 for m in raw_metrics if m['status'] == 'PASS')
    total      = len(raw_metrics)
    score      = round((passed / total) * 100)
    good_pct   = int(_g('good_pct') or 76)
    fair_pct   = int(_g('fair_pct') or 60)
    grade      = 'GOOD' if score >= good_pct else ('FAIR' if score >= fair_pct else 'POOR')

    # Bonus
    redundant = check_redundant_relationships(acts, rels)
    redundant['metric_no'] = 15

    # Resolve baseline project name and data date for display
    baseline_pname     = ''
    baseline_data_date = ''
    if baseline_proj_id:
        from xer_parser.xer_parser import Read_XER_File as _rxer
        _dfs = _rxer(xer_path)
        if 'PROJECT' in _dfs and not _dfs['PROJECT'].empty:
            _pdf = _dfs['PROJECT']
            if str(baseline_proj_id) in _pdf.index:
                _row = _pdf.loc[str(baseline_proj_id)]
                from xer_parser.xer_parser import _with_time as _wt
                baseline_data_date = _wt(str(_row.get('last_recalc_date', '') or '').strip())
                # Use WBS root name for full baseline project title
                if 'PROJWBS' in _dfs and not _dfs['PROJWBS'].empty:
                    for _, _wrow in _dfs['PROJWBS'].iterrows():
                        _wpid  = str(_wrow.get('proj_id', '') or '').strip()
                        _wflag = str(_wrow.get('proj_node_flag', '') or '').strip()
                        if _wpid == str(baseline_proj_id) and _wflag == 'Y':
                            baseline_pname = str(_wrow.get('wbs_name', '') or '').strip()
                            break
                if not baseline_pname:
                    baseline_pname = str(_row.get('proj_short_name', '') or '').strip()
            baseline_pname = baseline_pname or str(baseline_proj_id)

    # Full project title: WBS root name preferred over proj_short_name
    project_name = (parser.project_info.get('wbs_name') or
                    parser.project_info.get('proj_short_name') or 'Unknown')

    return {
        'project_name'      : project_name,
        'baseline_proj_name': baseline_pname,
        'baseline_data_date': baseline_data_date,
        'data_date'         : dd or 'N/A',
        'activity_count'    : len(acts),
        'relationship_count': len(rels),
        'score'             : score,
        'grade'             : grade,
        'passed'            : passed,
        'total'             : total,
        'good_pct'          : good_pct,
        'fair_pct'          : fair_pct,
        'metrics'           : raw_metrics,
        'bonus'             : redundant,
    }


# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


# ── Entry point ───────────────────────────────────────────────────────────────
init_db()
_cleanup_tmp_uploads()   # sweep stale uploads from any previous crashed run
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    print(f"\n  JESA Platform — http://localhost:{port}\n")
    app.run(debug=debug, host='0.0.0.0', port=port)
