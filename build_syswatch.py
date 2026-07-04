#!/usr/bin/env python3
"""
SysWatch v1.0 - Complete Project Generator (FINAL)
This script creates the entire folder structure and writes all files.
Run this ONCE to generate the full project.
All fixes from 2026-07-04 installation are incorporated.
"""

import os
import stat

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# FILE CONTENTS DEFINED AS MULTILINE STRINGS
# ============================================================

FILES = {
    # ---------- CORE ----------
    "core/__init__.py": '''# core/__init__.py - Core package
''',

    "core/config.py": '''# core/config.py - Configuration loader
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    # Database
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_USER = os.getenv("DB_USER", "monitor")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "monitoring")

    # Security
    API_KEY = os.getenv("API_KEY", "change-me-api-key")

    # Admin
    ADMIN_USER = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

    # SMTP
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")

    # Teams
    TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

    # SSL (for self-signed standalone)
    SSL_CERT = os.getenv("SSL_CERT", "")
    SSL_KEY = os.getenv("SSL_KEY", "")
''',

    "core/database.py": '''# core/database.py - Database connection and initialization
import pymysql
from flask import g
from werkzeug.security import generate_password_hash
from core.config import Config

db_config = {
    "host": Config.DB_HOST,
    "user": Config.DB_USER,
    "password": Config.DB_PASSWORD,
    "database": Config.DB_NAME,
    "autocommit": True,
    "auth_plugin_map": {
        'caching_sha2_password': 'caching_sha2_password'
    }
}

def get_db():
    if "db" not in g:
        g.db = pymysql.connect(**db_config)
    else:
        try:
            g.db.ping(reconnect=True)
        except Exception:
            g.db = pymysql.connect(**db_config)
    return g.db

def close_db(exception=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    """Initialize database tables if they don't exist."""
    db = pymysql.connect(**db_config)
    cur = db.cursor()

    # Hosts
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hosts (
            hostname VARCHAR(128) PRIMARY KEY,
            agent_id VARCHAR(64) DEFAULT NULL,
            ip VARCHAR(45),
            last_seen DATETIME,
            status VARCHAR(16) DEFAULT 'UP',
            group_id INT DEFAULT NULL
        )
    """)
    # Metrics
    cur.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hostname VARCHAR(128) NOT NULL,
            ip VARCHAR(45),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            cpu FLOAT,
            memory FLOAT,
            disk FLOAT,
            network_sent BIGINT,
            network_recv BIGINT,
            services JSON,
            network_devices JSON,
            uptime BIGINT,
            INDEX idx_hostname (hostname),
            INDEX idx_timestamp (timestamp)
        )
    """)
    # Alert Rules
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hostname VARCHAR(128),
            metric VARCHAR(32),
            threshold FLOAT,
            operator VARCHAR(2),
            severity VARCHAR(16),
            cooldown INT DEFAULT 300,
            cause TEXT,
            action TEXT
        )
    """)
    # Alerts (with lifecycle)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hostname VARCHAR(128),
            metric VARCHAR(32),
            value FLOAT,
            threshold FLOAT,
            severity VARCHAR(16),
            cause TEXT,
            action TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved INT DEFAULT 0,
            resolved_at DATETIME,
            status VARCHAR(16) DEFAULT 'OPEN',
            INDEX idx_alert_status (status),
            INDEX idx_alert_host_metric (hostname, metric)
        )
    """)
    # Host Groups
    cur.execute("""
        CREATE TABLE IF NOT EXISTS host_groups (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(64) UNIQUE NOT NULL
        )
    """)
    # Users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) UNIQUE NOT NULL,
            password_hash VARCHAR(256) NOT NULL,
            role VARCHAR(16) NOT NULL DEFAULT 'manager'
        )
    """)
    # SSL Certificates table (for grocery-store logic)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ssl_certificates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hostname VARCHAR(128) NOT NULL,
            port INT DEFAULT 443,
            expiry_date DATE NOT NULL,
            last_checked DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_host_port (hostname, port)
        )
    """)
    # AI Anomalies insights
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_insights (
            id INT AUTO_INCREMENT PRIMARY KEY,
            hostname VARCHAR(128),
            metric VARCHAR(32),
            current_value FLOAT,
            baseline_mean FLOAT,
            baseline_std FLOAT,
            deviation FLOAT,
            severity VARCHAR(16),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(16) DEFAULT 'OPEN'
        )
    """)

    # Migrations for existing alerts/hosts (if not already present)
    try:
        cur.execute("ALTER TABLE alerts ADD COLUMN status VARCHAR(16) DEFAULT 'OPEN'")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE hosts ADD COLUMN agent_id VARCHAR(64) DEFAULT NULL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE hosts ADD COLUMN group_id INT DEFAULT NULL")
    except Exception:
        pass

    db.commit()

    # Bootstrap admin user if none exist
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        admin_user = Config.ADMIN_USER
        admin_pass = Config.ADMIN_PASSWORD
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin')",
            (admin_user, generate_password_hash(admin_pass))
        )
        db.commit()

    cur.close()
    db.close()
''',

    "core/scheduler.py": '''# core/scheduler.py - APScheduler integration
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

def start_scheduler(app):
    """Start the background scheduler with all jobs."""
    with app.app_context():
        from modules.monitoring_checks.status_updater import compute_status
        from modules.monitoring_checks.ssl_expiry import check_all_certificates
        from modules.ai.anomaly import run_anomaly_detection

        # Job 1: Update host status (every 30 seconds)
        scheduler.add_job(
            func=compute_status,
            trigger='interval',
            seconds=30,
            id='status_updater',
            replace_existing=True
        )

        # Job 2: SSL expiry check (daily at 8:00 AM)
        scheduler.add_job(
            func=check_all_certificates,
            trigger='cron',
            hour=8,
            minute=0,
            id='ssl_expiry_check',
            replace_existing=True
        )

        # Job 3: AI Anomaly detection (every 5 minutes)
        scheduler.add_job(
            func=run_anomaly_detection,
            trigger='interval',
            minutes=5,
            id='anomaly_detection',
            replace_existing=True
        )

        if not scheduler.running:
            scheduler.start()
            print("✅ Scheduler started with 3 jobs.")

def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown()
        print("🛑 Scheduler stopped.")
''',

    "core/app.py": '''# core/app.py - Flask application factory
from flask import Flask
from flask_login import LoginManager
from core.config import Config
from core.database import close_db, init_db
from core.scheduler import start_scheduler

app = Flask(__name__, template_folder='../modules/web_ui/templates')
app.config['SECRET_KEY'] = Config.SECRET_KEY

# Database teardown
app.teardown_appcontext(close_db)

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "authentication.login"

# Import user loader
from modules.authentication.models import load_user
login_manager.user_loader(load_user)

# Register Blueprints
from modules.authentication.routes import auth_bp
from modules.web_ui.routes import ui_bp
from modules.api.routes import api_bp

app.register_blueprint(auth_bp)
app.register_blueprint(ui_bp)
app.register_blueprint(api_bp, url_prefix='/api')

# Initialize database
with app.app_context():
    init_db()

# Start scheduler
start_scheduler(app)

print("🚀 SysWatch Core initialized successfully.")
''',

    # ---------- MODULES ----------
    "modules/__init__.py": '''# modules/__init__.py
''',

    # --- Authentication ---
    "modules/authentication/__init__.py": '''# modules/authentication/__init__.py
''',

    "modules/authentication/models.py": '''# modules/authentication/models.py - User class and loader
from flask_login import UserMixin
from core.database import get_db

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

def load_user(user_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, username, role FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    if row:
        return User(row[0], row[1], row[2])
    return None
''',

    "modules/authentication/routes.py": '''# modules/authentication/routes.py - Login, Logout, User management
from flask import Blueprint, request, jsonify, render_template, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from core.database import get_db
from modules.authentication.models import User
import pymysql

auth_bp = Blueprint('authentication', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, username, password_hash, role FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        if user and check_password_hash(user[2], password):
            login_user(User(user[0], user[1], user[3]))
            return redirect(url_for('web_ui.dashboard'))
        error = "Invalid credentials"
    return render_template('login.html', error=error)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('authentication.login'))

# --- API: User Management (Admin only) ---

@auth_bp.route('/api/users', methods=['GET'])
@login_required
def list_users():
    if current_user.role != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, username, role FROM users ORDER BY username")
    users = [{"id": r[0], "username": r[1], "role": r[2]} for r in cur.fetchall()]
    cur.close()
    return jsonify(users)

@auth_bp.route('/api/users', methods=['POST'])
@login_required
def create_user():
    if current_user.role != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'manager')
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, generate_password_hash(password), role)
        )
        db.commit()
        return jsonify({"status": "ok", "id": cur.lastrowid})
    except pymysql.IntegrityError:
        return jsonify({"error": "User already exists"}), 409
    finally:
        cur.close()

@auth_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    if user_id == current_user.id:
        return jsonify({"error": "Cannot delete yourself"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    db.commit()
    cur.close()
    return jsonify({"status": "ok"})
''',

    # --- Web UI ---
    "modules/web_ui/__init__.py": '''# modules/web_ui/__init__.py
''',

    "modules/web_ui/routes.py": '''# modules/web_ui/routes.py - Dashboard UI
from flask import Blueprint, render_template
from flask_login import login_required

ui_bp = Blueprint('web_ui', __name__)

@ui_bp.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html')
''',

    "modules/web_ui/templates/dashboard.html": '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SysWatch - Infrastructure Monitoring</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <style>
        :root { --bg: #ffffff; --text: #333; --card-bg: #f9f9f9; }
        body.dark { --bg: #1e1e1e; --text: #ddd; --card-bg: #2a2a2a; }
        body { font-family: Arial; margin: 20px; background: var(--bg); color: var(--text); }
        .summary-cards { display: flex; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }
        .card { background: var(--card-bg); border: 1px solid #ccc; padding: 15px; border-radius: 8px; flex: 1; min-width: 120px; text-align: center;}
        .card h3 { margin: 0 0 5px; }
        .card .value { font-size: 1.8em; font-weight: bold; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 15px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: left; font-size: 0.9em; }
        th { background: #eee; color: #333; }
        tr:hover { background: rgba(0,0,0,0.05); cursor: pointer; }
        .status-UP { color: green; font-weight: bold; }
        .status-WARNING { color: orange; font-weight: bold; }
        .status-DOWN { color: red; font-weight: bold; }
        .status-OPEN { color: red; }
        .status-ACKNOWLEDGED { color: orange; }
        .status-RESOLVED { color: green; }
        .tab { overflow: hidden; border-bottom: 1px solid #ccc; margin-bottom: 10px; }
        .tab button { background: inherit; border: none; padding: 10px 20px; cursor: pointer; }
        .tab button.active { background: #ddd; color: #333; }
        .tabcontent { display: none; }
        .chart-box { width: 80%; margin: auto; margin-top: 20px; }
        .filters { margin-bottom: 10px; }
        .filters select, .filters input { margin-right: 10px; }
        .admin-section { margin-top: 20px; }
        .admin-section input, .admin-section select { margin-right: 10px; }
        .ack-btn { background: #ffc107; border: none; padding: 3px 8px; cursor: pointer; border-radius: 4px; }
    </style>
</head>
<body>
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <h1>🚀 SysWatch Monitoring</h1>
        <div>
            <button onclick="toggleDarkMode()">🌓 Dark</button>
            <a href="/logout" style="margin-left:20px">Logout</a>
        </div>
    </div>

    <div class="summary-cards">
        <div class="card"><h3>Total Hosts</h3><div class="value" id="totalHosts">-</div></div>
        <div class="card"><h3>UP</h3><div class="value" id="upHosts" style="color:green">-</div></div>
        <div class="card"><h3>WARNING</h3><div class="value" id="warnHosts" style="color:orange">-</div></div>
        <div class="card"><h3>DOWN</h3><div class="value" id="downHosts" style="color:red">-</div></div>
        <div class="card"><h3>Open Alerts</h3><div class="value" id="openAlerts" style="color:red">-</div></div>
    </div>

    <div class="tab">
        <button class="tablinks active" onclick="openTab(event,'Devices')">Devices</button>
        <button class="tablinks" onclick="openTab(event,'Alerts')">Alerts</button>
        <button class="tablinks" onclick="openTab(event,'History')">History</button>
        <button class="tablinks" onclick="openTab(event,'Settings')" id="settingsTab">Settings</button>
    </div>

    <div id="Devices" class="tabcontent" style="display:block">
        <div class="filters">
            <label>Group: <select id="groupFilter" onchange="fetchDevices()"><option value="">All Groups</option></select></label>
            <label>Status: <select id="statusFilter" onchange="fetchDevices()"><option value="">All</option><option value="UP">UP</option><option value="WARNING">WARNING</option><option value="DOWN">DOWN</option></select></label>
        </div>
        <table id="devicesTable">
            <thead><tr>
                <th>Hostname</th><th>IP</th><th>Status</th><th>Group</th><th>Last Seen</th>
                <th>CPU%</th><th>Mem%</th><th>Disk%</th>
                <th>Net Sent</th><th>Net Recv</th>
                <th>Services</th><th>Ext. Devices</th>
            </tr></thead>
            <tbody></tbody>
        </table>
        <div>
            <label for="trendRange">Trend Range:</label>
            <select id="trendRange" onchange="loadChart()">
                <option value="1h">Last Hour</option><option value="12h">Last 12 Hours</option><option value="24h">Last 24 Hours</option>
                <option value="1w">Last Week</option><option value="1m">Last Month</option><option value="1y">Last Year</option>
            </select>
        </div>
        <div class="chart-box"><canvas id="trendChart"></canvas></div>
    </div>

    <div id="Alerts" class="tabcontent">
        <div class="filters">
            <label>Status: <select id="alertStatusFilter" onchange="fetchAlerts()"><option value="">All</option><option value="OPEN">Open</option><option value="ACKNOWLEDGED">Acknowledged</option><option value="RESOLVED">Resolved</option></select></label>
        </div>
        <table id="alertsTable">
            <thead><tr>
                <th>Host</th><th>Metric</th><th>Value</th><th>Severity</th>
                <th>Cause</th><th>Action</th><th>Time</th><th>Status</th><th>Ack</th>
            </tr></thead>
            <tbody></tbody>
        </table>
    </div>

    <div id="History" class="tabcontent">
        <h3>Historical Data</h3>
        <label>Host: <input type="text" id="historyHost" placeholder="hostname"></label>
        <label>Hours: <input type="number" id="historyHours" value="1" min="1" max="720"></label>
        <label>Metric: <select id="historyMetric"><option value="cpu">CPU %</option><option value="memory">Memory %</option><option value="disk">Disk%</option><option value="network_sent">Net Sent (bytes)</option><option value="network_recv">Net Recv (bytes)</option></select></label>
        <button onclick="fetchHistory()">Fetch</button>
        <div class="chart-box"><canvas id="historyChart"></canvas></div>
        <table id="historyTable" style="margin-top:20px">
            <thead><tr><th>Timestamp</th><th>CPU%</th><th>Mem%</th><th>Disk%</th><th>Net Sent</th><th>Net Recv</th></tr></thead>
            <tbody></tbody>
        </table>
    </div>

    <div id="Settings" class="tabcontent">
        <h2>User Management</h2>
        <div class="admin-section" id="userSection">
            <input type="text" id="newUsername" placeholder="Username"><input type="password" id="newPassword" placeholder="Password">
            <select id="newRole"><option value="manager">Manager</option><option value="admin">Admin</option></select>
            <button onclick="createUser()">Create User</button>
        </div>
        <table id="usersTable"><thead><tr><th>ID</th><th>Username</th><th>Role</th><th>Action</th></tr></thead><tbody></tbody></table>
        <h2>Host Groups</h2>
        <div class="admin-section"><input type="text" id="newGroupName" placeholder="Group name"><button onclick="createGroup()">Create Group</button></div>
        <table id="groupsTable"><thead><tr><th>ID</th><th>Name</th><th>Action</th></tr></thead><tbody></tbody></table>
    </div>

    <script>
        let trendChart = null, historyChartObj = null, selectedHost = null;
        let currentUserRole = "{{ current_user.role }}";

        function toggleDarkMode() { document.body.classList.toggle('dark'); localStorage.setItem('darkMode', document.body.classList.contains('dark')); }
        if (localStorage.getItem('darkMode') === 'true') document.body.classList.add('dark');

        function openTab(evt, name) {
            document.querySelectorAll('.tabcontent').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.tablinks').forEach(el => el.classList.remove('active'));
            document.getElementById(name).style.display = 'block';
            evt.currentTarget.classList.add('active');
            if (name === 'Alerts') fetchAlerts();
            if (name === 'Settings') loadSettings();
            if (name === 'Devices') fetchDevices();
        }

        async function updateSummary() {
            const resp = await fetch('/api/summary');
            const data = await resp.json();
            document.getElementById('totalHosts').textContent = data.total;
            document.getElementById('upHosts').textContent = data.up;
            document.getElementById('warnHosts').textContent = data.warning;
            document.getElementById('downHosts').textContent = data.down;
            document.getElementById('openAlerts').textContent = data.open_alerts;
        }

        async function fetchDevices() {
            const gf = document.getElementById('groupFilter').value, sf = document.getElementById('statusFilter').value;
            let url = '/api/latest?'; if (gf) url += `group=${gf}&`; if (sf) url += `status=${sf}&`;
            const resp = await fetch(url), data = await resp.json();
            const tbody = document.querySelector('#devicesTable tbody'); tbody.innerHTML = '';
            data.forEach(d => {
                const row = tbody.insertRow();
                row.innerHTML = `<td>${d.hostname}</td><td>${d.ip}</td><td class="status-${d.status}">${d.status}</td><td>${d.group_name}</td><td>${d.last_seen||''}</td><td>${d.cpu!=null?d.cpu+'%':'N/A'}</td><td>${d.memory!=null?d.memory+'%':'N/A'}</td><td>${d.disk!=null?d.disk+'%':'N/A'}</td><td>${formatBytes(d.network_sent)}</td><td>${formatBytes(d.network_recv)}</td><td>${formatServices(d.services)}</td><td>${formatDevices(d.network_devices)}</td>`;
                row.onclick = () => { selectedHost = d.hostname; loadChart(); };
            });
            updateSummary(); loadGroupFilterOptions();
        }

        function formatBytes(bytes) {
            if (bytes == null) return 'N/A';
            if (bytes < 1024) return bytes + ' B';
            const kb = bytes / 1024; if (kb < 1024) return kb.toFixed(1) + ' KB';
            const mb = kb / 1024; if (mb < 1024) return mb.toFixed(1) + ' MB';
            return (mb / 1024).toFixed(2) + ' GB';
        }
        function formatServices(s) { if (!s || Object.keys(s).length===0) return 'N/A'; return Object.entries(s).map(([k,v])=>`${k}:${v}`).join(', '); }
        function formatDevices(d) { if (!d || d.length===0) return 'N/A'; return d.map(x=>`${x.name}(${x.reachable?'UP':'DOWN'})`).join(', '); }

        async function loadGroupFilterOptions() {
            const sel = document.getElementById('groupFilter'), cv = sel.value;
            const resp = await fetch('/api/groups'), groups = await resp.json();
            sel.innerHTML = '<option value="">All Groups</option>';
            groups.forEach(g => { sel.innerHTML += `<option value="${g.id}" ${g.id==cv?'selected':''}>${g.name}</option>`; });
        }

        async function loadChart() {
            if (!selectedHost) return;
            const range = document.getElementById('trendRange').value;
            const resp = await fetch(`/api/trends/${selectedHost}?range=${range}`), data = await resp.json();
            if (data.length===0) return;
            const labels = data.map(d=>d.timestamp), cpu = data.map(d=>d.cpu), mem = data.map(d=>d.memory), disk = data.map(d=>d.disk);
            const ctx = document.getElementById('trendChart').getContext('2d');
            if (trendChart) trendChart.destroy();
            trendChart = new Chart(ctx, { type:'line', data:{ labels, datasets:[ {label:'CPU %', data:cpu, borderColor:'red', fill:false}, {label:'Memory %', data:mem, borderColor:'blue', fill:false}, {label:'Disk %', data:disk, borderColor:'green', fill:false} ] }, options:{ responsive:true, scales:{ y:{ beginAtZero:true, max:100 } } } });
        }

        async function fetchAlerts() {
            const s = document.getElementById('alertStatusFilter').value;
            let url = '/api/alerts?'; if (s) url += `status=${s}&`;
            const resp = await fetch(url), alerts = await resp.json();
            const tbody = document.querySelector('#alertsTable tbody'); tbody.innerHTML = '';
            alerts.forEach(a => {
                const row = tbody.insertRow();
                row.innerHTML = `<td>${a.hostname}</td><td>${a.metric}</td><td>${a.value}</td><td>${a.severity}</td><td>${a.cause||''}</td><td>${a.action||''}</td><td>${a.timestamp}</td><td class="status-${a.status}">${a.status}</td><td>${a.status==='OPEN'?`<button class="ack-btn" onclick="ackAlert(${a.id})">Ack</button>`:''}</td>`;
            });
        }
        async function ackAlert(id) { await fetch(`/api/alerts/${id}/acknowledge`, {method:'POST'}); fetchAlerts(); updateSummary(); }

        async function fetchHistory() {
            const host = document.getElementById('historyHost').value, hours = document.getElementById('historyHours').value, metric = document.getElementById('historyMetric').value;
            if (!host) return alert('Enter a hostname');
            const resp = await fetch(`/api/history/${host}?hours=${hours}`), data = await resp.json();
            const tbody = document.querySelector('#historyTable tbody'); tbody.innerHTML = '';
            data.forEach(d => { const row = tbody.insertRow(); row.innerHTML = `<td>${d.timestamp}</td><td>${d.cpu}</td><td>${d.memory}</td><td>${d.disk}</td><td>${d.network_sent}</td><td>${d.network_recv}</td>`; });
            const ctx = document.getElementById('historyChart').getContext('2d'); if (historyChartObj) historyChartObj.destroy();
            const labels = data.map(d=>d.timestamp), values = data.map(d=>d[metric]);
            let yL = metric.replace('_',' ').toUpperCase(); if (metric.startsWith('network_')) yL += ' (bytes)'; else yL += ' %';
            historyChartObj = new Chart(ctx, { type:'line', data:{ labels, datasets:[{label:yL, data:values, borderColor:'purple', fill:false, tension:0.1}] }, options:{ responsive:true, scales:{ y:{ beginAtZero:true, title:{display:true, text:yL} } } } });
        }

        async function loadSettings() {
            if (currentUserRole !== 'admin') { document.getElementById('userSection').style.display='none'; return; }
            const uResp = await fetch('/api/users'), users = await uResp.json();
            const uTbody = document.querySelector('#usersTable tbody'); uTbody.innerHTML = '';
            users.forEach(u => { const row = uTbody.insertRow(); row.innerHTML = `<td>${u.id}</td><td>${u.username}</td><td>${u.role}</td><td><button onclick="deleteUser(${u.id})">Delete</button></td>`; });
            const gResp = await fetch('/api/groups'), groups = await gResp.json();
            const gTbody = document.querySelector('#groupsTable tbody'); gTbody.innerHTML = '';
            groups.forEach(g => { const row = gTbody.insertRow(); row.innerHTML = `<td>${g.id}</td><td>${g.name}</td><td><button onclick="deleteGroup(${g.id})">Delete</button></td>`; });
        }

        async function createUser() {
            const u = document.getElementById('newUsername').value, p = document.getElementById('newPassword').value, r = document.getElementById('newRole').value;
            await fetch('/api/users', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u, password:p, role:r})});
            loadSettings(); document.getElementById('newUsername').value = document.getElementById('newPassword').value = '';
        }
        async function deleteUser(id) { if (confirm('Delete user?')) { await fetch(`/api/users/${id}`, {method:'DELETE'}); loadSettings(); } }
        async function createGroup() {
            const n = document.getElementById('newGroupName').value;
            await fetch('/api/groups', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:n})});
            loadSettings(); document.getElementById('newGroupName').value = ''; fetchDevices();
        }
        async function deleteGroup(id) { if (confirm('Delete group?')) { await fetch(`/api/groups/${id}`, {method:'DELETE'}); loadSettings(); fetchDevices(); } }

        fetchDevices(); setInterval(fetchDevices, 60000); updateSummary();
    </script>
</body>
</html>
''',

    "modules/web_ui/templates/login.html": '''<h1>🔐 SysWatch Login</h1>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}
<form method="POST">
    <input type="text" name="username" placeholder="Username" required><br>
    <input type="password" name="password" placeholder="Password" required><br>
    <button type="submit">Log in</button>
</form>
''',

    # --- API ---
    "modules/api/__init__.py": '''# modules/api/__init__.py
''',

    "modules/api/routes.py": '''# modules/api/routes.py - All REST API endpoints
import json
import datetime
import pymysql
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from core.config import Config
from core.database import get_db
from modules.monitoring_checks.status_updater import update_host_status
from modules.alert_engine.lifecycle import evaluate_alerts

api_bp = Blueprint('api', __name__)

# --- Agent Ingest ---
@api_bp.route('/report', methods=['POST'])
def report():
    if request.headers.get('X-API-Key') != Config.API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True)
    hostname = data['hostname']
    agent_id = data.get('agent_id', '')
    ip = data['ip']
    group_id = data.get('group_id', None)
    update_host_status(hostname, agent_id, ip, group_id)

    db = get_db()
    cur = db.cursor()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    cur.execute(
        "INSERT INTO metrics (hostname, ip, timestamp, cpu, memory, disk, "
        "network_sent, network_recv, services, network_devices, uptime) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            hostname, ip, now,
            data['cpu'], data['memory'], data['disk'],
            data.get('network_sent', 0), data.get('network_recv', 0),
            json.dumps(data.get('services', {})),
            json.dumps(data.get('network_devices', [])),
            data['uptime']
        )
    )
    db.commit()
    evaluate_alerts(hostname, data)
    cur.close()
    return jsonify({"status": "ok"})

# --- Latest Hosts ---
@api_bp.route('/latest')
@login_required
def latest():
    group_filter = request.args.get('group', '')
    status_filter = request.args.get('status', '')
    db = get_db()
    cur = db.cursor()
    query = """
        SELECT h.hostname, h.agent_id, h.ip, h.status, h.last_seen,
               h.group_id, g.name as group_name,
               m.cpu, m.memory, m.disk, m.network_sent, m.network_recv,
               m.services, m.network_devices
        FROM hosts h
        LEFT JOIN host_groups g ON h.group_id = g.id
        LEFT JOIN (
            SELECT hostname, MAX(timestamp) as max_ts FROM metrics GROUP BY hostname
        ) latest ON h.hostname = latest.hostname
        LEFT JOIN metrics m ON m.hostname = latest.hostname AND m.timestamp = latest.max_ts
        WHERE 1=1
    """
    params = []
    if group_filter:
        query += " AND h.group_id = %s"
        params.append(group_filter)
    if status_filter:
        query += " AND h.status = %s"
        params.append(status_filter)
    query += " ORDER BY h.hostname"
    cur.execute(query, params)
    rows = cur.fetchall()
    result = []
    for r in rows:
        result.append({
            "hostname": r[0], "agent_id": r[1], "ip": r[2], "status": r[3],
            "last_seen": r[4].isoformat() if r[4] else None,
            "group_id": r[5], "group_name": r[6] or "None",
            "cpu": r[7], "memory": r[8], "disk": r[9],
            "network_sent": r[10], "network_recv": r[11],
            "services": json.loads(r[12]) if r[12] else {},
            "network_devices": json.loads(r[13]) if r[13] else []
        })
    cur.close()
    return jsonify(result)

# --- History ---
@api_bp.route('/history/<hostname>')
@login_required
def history(hostname):
    hours = request.args.get('hours', 1, type=int)
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT timestamp, cpu, memory, disk, network_sent, network_recv "
        "FROM metrics WHERE hostname = %s AND timestamp >= NOW() - INTERVAL %s HOUR "
        "ORDER BY timestamp ASC", (hostname, hours))
    rows = cur.fetchall()
    data = [{"timestamp": r[0].isoformat(), "cpu": r[1], "memory": r[2],
             "disk": r[3], "network_sent": r[4], "network_recv": r[5]} for r in rows]
    cur.close()
    return jsonify(data)

# --- Trends ---
@api_bp.route('/trends/<hostname>')
@login_required
def trends(hostname):
    range_ = request.args.get('range', '1h')
    db = get_db()
    cur = db.cursor()
    if range_ == '1h':
        cur.execute("""
            SELECT DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i') as bucket,
                   AVG(cpu), AVG(memory), AVG(disk)
            FROM metrics WHERE hostname=%s AND timestamp >= NOW() - INTERVAL 1 HOUR
            GROUP BY bucket ORDER BY bucket
        """, (hostname,))
    elif range_ == '12h':
        cur.execute("""
            SELECT DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:%%i') as bucket,
                   AVG(cpu), AVG(memory), AVG(disk)
            FROM metrics WHERE hostname=%s AND timestamp >= NOW() - INTERVAL 12 HOUR
            GROUP BY bucket ORDER BY bucket
        """, (hostname,))
    elif range_ == '24h':
        cur.execute("""
            SELECT DATE_FORMAT(timestamp, '%%Y-%%m-%%d %%H:00') as bucket,
                   AVG(cpu), AVG(memory), AVG(disk)
            FROM metrics WHERE hostname=%s AND timestamp >= NOW() - INTERVAL 24 HOUR
            GROUP BY bucket ORDER BY bucket
        """, (hostname,))
    elif range_ == '1w':
        cur.execute("""
            SELECT DATE(timestamp) as bucket,
                   AVG(cpu), AVG(memory), AVG(disk)
            FROM metrics WHERE hostname=%s AND timestamp >= NOW() - INTERVAL 7 DAY
            GROUP BY bucket ORDER BY bucket
        """, (hostname,))
    elif range_ == '1m':
        cur.execute("""
            SELECT DATE(timestamp) as bucket,
                   AVG(cpu), AVG(memory), AVG(disk)
            FROM metrics WHERE hostname=%s AND timestamp >= NOW() - INTERVAL 30 DAY
            GROUP BY bucket ORDER BY bucket
        """, (hostname,))
    elif range_ == '1y':
        cur.execute("""
            SELECT DATE_FORMAT(timestamp, '%%Y-%%m') as bucket,
                   AVG(cpu), AVG(memory), AVG(disk)
            FROM metrics WHERE hostname=%s AND timestamp >= NOW() - INTERVAL 365 DAY
            GROUP BY bucket ORDER BY bucket
        """, (hostname,))
    else:
        return jsonify([])
    rows = cur.fetchall()
    data = [{"timestamp": r[0], "cpu": round(r[1],1) if r[1] else 0,
             "memory": round(r[2],1) if r[2] else 0,
             "disk": round(r[3],1) if r[3] else 0} for r in rows]
    cur.close()
    return jsonify(data)

# --- Alerts ---
@api_bp.route('/alerts')
@login_required
def alerts_api():
    status_filter = request.args.get('status', '')
    db = get_db()
    cur = db.cursor()
    query = "SELECT id, hostname, metric, value, threshold, severity, cause, action, timestamp, status FROM alerts"
    params = []
    if status_filter:
        query += " WHERE status = %s"
        params.append(status_filter)
    query += " ORDER BY timestamp DESC LIMIT 200"
    cur.execute(query, params)
    alerts = [{"id": r[0], "hostname": r[1], "metric": r[2], "value": r[3],
               "threshold": r[4], "severity": r[5], "cause": r[6], "action": r[7],
               "timestamp": r[8].isoformat(), "status": r[9]} for r in cur.fetchall()]
    cur.close()
    return jsonify(alerts)

@api_bp.route('/alerts/<int:alert_id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_alert(alert_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE alerts SET status = 'ACKNOWLEDGED' WHERE id = %s", (alert_id,))
    db.commit()
    cur.close()
    return jsonify({"status": "ok"})

# --- Groups ---
@api_bp.route('/groups')
@login_required
def list_groups():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, name FROM host_groups ORDER BY name")
    groups = [{"id": r[0], "name": r[1]} for r in cur.fetchall()]
    cur.close()
    return jsonify(groups)

@api_bp.route('/groups', methods=['POST'])
@login_required
def create_group():
    if current_user.role != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({"error": "Group name required"}), 400
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("INSERT INTO host_groups (name) VALUES (%s)", (name,))
        db.commit()
        return jsonify({"id": cur.lastrowid, "name": name})
    except pymysql.IntegrityError:
        return jsonify({"error": "Group already exists"}), 409
    finally:
        cur.close()

@api_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@login_required
def delete_group(group_id):
    if current_user.role != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM host_groups WHERE id = %s", (group_id,))
    db.commit()
    cur.close()
    return jsonify({"status": "ok"})

@api_bp.route('/hosts/<hostname>/group', methods=['PUT'])
@login_required
def assign_host_group(hostname):
    if current_user.role != 'admin':
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json()
    group_id = data.get('group_id')
    db = get_db()
    cur = db.cursor()
    if group_id:
        cur.execute("UPDATE hosts SET group_id = %s WHERE hostname = %s", (group_id, hostname))
    else:
        cur.execute("UPDATE hosts SET group_id = NULL WHERE hostname = %s", (hostname,))
    db.commit()
    cur.close()
    return jsonify({"status": "ok"})

# --- Summary ---
@api_bp.route('/summary')
@login_required
def summary():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*), SUM(status='UP'), SUM(status='WARNING'), SUM(status='DOWN') FROM hosts")
    row = cur.fetchone()
    total, up, warning, down = row[0], row[1] or 0, row[2] or 0, row[3] or 0
    cur.execute("SELECT COUNT(*) FROM alerts WHERE status = 'OPEN'")
    open_alerts = cur.fetchone()[0]
    cur.close()
    return jsonify({"total": total, "up": up, "warning": warning, "down": down, "open_alerts": open_alerts})
''',

    # --- Monitoring Checks ---
    "modules/monitoring_checks/__init__.py": '''# modules/monitoring_checks/__init__.py
''',

    "modules/monitoring_checks/status_updater.py": '''# modules/monitoring_checks/status_updater.py
import datetime
from core.database import get_db
from core.app import app

STATUS_THRESHOLDS = {"UP": 90, "WARNING": 300}

def update_host_status(hostname, agent_id, ip, group_id=None):
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        cur.execute(
            "INSERT INTO hosts (hostname, agent_id, ip, last_seen, status, group_id) "
            "VALUES (%s, %s, %s, %s, 'UP', %s) "
            "ON DUPLICATE KEY UPDATE agent_id = VALUES(agent_id), ip = VALUES(ip), "
            "last_seen = VALUES(last_seen), group_id = VALUES(group_id)",
            (hostname, agent_id, ip, now, group_id)
        )
        db.commit()
        cur.close()

def compute_status():
    with app.app_context():
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT hostname, last_seen FROM hosts")
        rows = cur.fetchall()
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        for hostname, last_seen in rows:
            if last_seen is None:
                status = "DOWN"
            else:
                delta = (now - last_seen).total_seconds()
                if delta < STATUS_THRESHOLDS["UP"]:
                    status = "UP"
                elif delta < STATUS_THRESHOLDS["WARNING"]:
                    status = "WARNING"
                else:
                    status = "DOWN"
            cur.execute("UPDATE hosts SET status = %s WHERE hostname = %s", (status, hostname))
        db.commit()
        cur.close()
''',

    "modules/monitoring_checks/ssl_expiry.py": '''# modules/monitoring_checks/ssl_expiry.py
import ssl
import socket
import datetime
import OpenSSL.crypto
from core.database import get_db
from core.app import app
from modules.alert_engine.notifiers import dispatch_alert

def fetch_cert_expiry(hostname, port=443):
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_ASN1, cert_der)
                expiry_bytes = cert.get_notAfter()
                expiry_str = expiry_bytes.decode('ascii')
                expiry_date = datetime.datetime.strptime(expiry_str, '%Y%m%d%H%M%SZ').date()
                return expiry_date
    except Exception as e:
        print(f"SSL fetch error for {hostname}:{port} - {e}")
        return None

def check_all_certificates():
    with app.app_context():
        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT DISTINCT hostname, ip FROM hosts WHERE ip IS NOT NULL AND ip != '127.0.0.1'")
        hosts = cur.fetchall()

        today = datetime.date.today()
        for hostname, ip in hosts:
            cur.execute("SELECT expiry_date FROM ssl_certificates WHERE hostname = %s AND port = 443", (hostname,))
            row = cur.fetchone()

            if row:
                stored_expiry = row[0]
                days_remaining = (stored_expiry - today).days
                if 0 <= days_remaining <= 7:
                    severity = "WARNING" if days_remaining > 2 else "CRITICAL"
                    dispatch_alert(
                        hostname=hostname,
                        metric="ssl_expiry",
                        value=days_remaining,
                        threshold=7,
                        severity=severity,
                        cause=f"SSL certificate expires in {days_remaining} days on {stored_expiry}",
                        action="Renew the certificate and update it on the server."
                    )
                elif days_remaining < 0:
                    dispatch_alert(
                        hostname=hostname,
                        metric="ssl_expiry",
                        value=days_remaining,
                        threshold=0,
                        severity="CRITICAL",
                        cause=f"SSL certificate expired on {stored_expiry}",
                        action="Renew the certificate immediately."
                    )
                cur.execute("UPDATE ssl_certificates SET last_checked = NOW() WHERE hostname = %s AND port = 443", (hostname,))
                db.commit()
            else:
                expiry_date = fetch_cert_expiry(hostname, 443)
                if expiry_date:
                    cur.execute(
                        "INSERT INTO ssl_certificates (hostname, port, expiry_date, last_checked) VALUES (%s, 443, %s, NOW())",
                        (hostname, expiry_date)
                    )
                    db.commit()

        cur.close()
''',

    # --- Alert Engine ---
    "modules/alert_engine/__init__.py": '''# modules/alert_engine/__init__.py
''',

    "modules/alert_engine/lifecycle.py": '''# modules/alert_engine/lifecycle.py
import datetime
from core.database import get_db
from modules.alert_engine.notifiers import dispatch_alert

def evaluate_alerts(hostname, data):
    db = get_db()
    cur = db.cursor()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    cur.execute("SELECT * FROM alert_rules WHERE hostname=%s OR hostname IS NULL", (hostname,))
    rules = cur.fetchall()

    for rule in rules:
        metric = rule[2]
        if metric in data:
            value = data[metric]
            op = rule[4]
            threshold = rule[3]
            severity = rule[5]
            cooldown = rule[6]
            cause = rule[7] if len(rule) > 7 else None
            action = rule[8] if len(rule) > 8 else None

            violated = False
            if op == ">" and value > threshold:
                violated = True
            elif op == "<" and value < threshold:
                violated = True

            if violated:
                cur.execute(
                    "SELECT id, timestamp, status FROM alerts WHERE hostname=%s AND metric=%s "
                    "AND status IN ('OPEN','ACKNOWLEDGED') ORDER BY timestamp DESC LIMIT 1",
                    (hostname, metric)
                )
                existing = cur.fetchone()
                fire = True
                if existing:
                    last_time = existing[1]
                    if (now - last_time).total_seconds() < cooldown:
                        fire = False
                if fire:
                    cur.execute(
                        "INSERT INTO alerts (hostname, metric, value, threshold, severity, cause, action, status) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN')",
                        (hostname, metric, value, threshold, severity, cause, action)
                    )
                    db.commit()
                    dispatch_alert(hostname, metric, value, threshold, severity, cause, action)
            else:
                cur.execute(
                    "UPDATE alerts SET status = 'RESOLVED', resolved = 1, resolved_at = %s "
                    "WHERE hostname = %s AND metric = %s AND status IN ('OPEN','ACKNOWLEDGED')",
                    (now, hostname, metric)
                )
                db.commit()
    cur.close()
''',

    "modules/alert_engine/notifiers.py": '''# modules/alert_engine/notifiers.py
import smtplib
import requests
import datetime
from email.mime.text import MIMEText
from core.config import Config

def send_email(subject, body):
    if not Config.SMTP_USER or not Config.SMTP_PASSWORD:
        print("SMTP not configured, skipping email.")
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = Config.SMTP_USER
        msg['To'] = Config.ALERT_EMAIL_TO
        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as s:
            s.starttls()
            s.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            s.sendmail(Config.SMTP_USER, [Config.ALERT_EMAIL_TO], msg.as_string())
    except Exception as e:
        print(f"Email error: {e}")

def send_teams(title, text):
    if not Config.TEAMS_WEBHOOK_URL:
        return
    try:
        requests.post(Config.TEAMS_WEBHOOK_URL, json={"title": title, "text": text, "themeColor": "FF0000"})
    except Exception as e:
        print(f"Teams error: {e}")

def dispatch_alert(hostname, metric, value, threshold, severity, cause, action):
    subject = f"{severity.upper()}: {hostname} {metric} = {value:.1f}%"
    body = f"""Host: {hostname}
Metric: {metric}
Value: {value:.1f}%{f' (Threshold: {threshold}%)' if threshold else ''}
Severity: {severity}
Likely Cause: {cause or 'N/A'}
Suggested Actions: {action or 'N/A'}
Time: {datetime.datetime.utcnow().isoformat()}"""
    send_email(subject, body)
    send_teams(subject, body)
''',

    # --- AI ---
    "modules/ai/__init__.py": '''# modules/ai/__init__.py
''',

    "modules/ai/anomaly.py": '''# modules/ai/anomaly.py
import statistics
from core.database import get_db
from core.app import app
from modules.alert_engine.notifiers import dispatch_alert

def run_anomaly_detection():
    with app.app_context():
        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT DISTINCT hostname FROM hosts WHERE status != 'DOWN'")
        hosts = cur.fetchall()

        for (hostname,) in hosts:
            for metric in ['cpu', 'memory', 'disk']:
                cur.execute(
                    f"SELECT {metric} FROM metrics WHERE hostname = %s AND timestamp >= NOW() - INTERVAL 7 DAY "
                    f"AND {metric} IS NOT NULL ORDER BY timestamp DESC LIMIT 100",
                    (hostname,)
                )
                rows = cur.fetchall()
                if len(rows) < 10:
                    continue

                values = [r[0] for r in rows]
                mean = statistics.mean(values)
                std = statistics.stdev(values) if len(values) > 1 else 0

                if std == 0:
                    continue

                cur.execute(
                    f"SELECT {metric} FROM metrics WHERE hostname = %s AND {metric} IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                    (hostname,)
                )
                current_row = cur.fetchone()
                if not current_row:
                    continue
                current_value = current_row[0]

                if current_value > mean + (2 * std):
                    deviation = (current_value - mean) / std
                    severity = "WARNING" if deviation < 3 else "CRITICAL"

                    cur.execute(
                        "INSERT INTO ai_insights (hostname, metric, current_value, baseline_mean, baseline_std, deviation, severity) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (hostname, metric, current_value, mean, std, deviation, severity)
                    )
                    db.commit()

                    if severity == "CRITICAL":
                        dispatch_alert(
                            hostname=hostname,
                            metric=f"ai_{metric}",
                            value=current_value,
                            threshold=round(mean + (2 * std), 2),
                            severity="CRITICAL",
                            cause=f"AI detected anomaly: {metric} at {current_value:.1f}% (baseline mean: {mean:.1f}%, std: {std:.1f})",
                            action="Investigate this anomaly. Check for recent changes or processes."
                        )

                cur.execute("DELETE FROM ai_insights WHERE timestamp < NOW() - INTERVAL 7 DAY")
                db.commit()

        cur.close()
''',

    # --- Agents ---
    "agents/__init__.py": '''# agents/__init__.py
''',

    "agents/client.py": '''#!/usr/bin/env python3
"""
SysWatch Agent - Cross-platform monitoring client
Collects system metrics and sends them to the SysWatch server.
"""

import os
import time
import json
import socket
import subprocess
import platform
import uuid
import requests
import psutil
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL", "https://syswatch.fluidthoughts.co.in/api/report")
API_KEY = os.getenv("API_KEY", "")
GROUP_ID = os.getenv("GROUP_ID")
AGENT_ID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_id")

SERVICES_TO_CHECK = ["sshd", "nginx", "mysql"]
NETWORK_DEVICES = []  # Define your devices here: [{"name": "router", "ip": "192.168.1.1", "type": "router"}]

def get_agent_id():
    if os.path.exists(AGENT_ID_FILE):
        with open(AGENT_ID_FILE, "r") as f:
            return f.read().strip()
    new_id = str(uuid.uuid4())
    with open(AGENT_ID_FILE, "w") as f:
        f.write(new_id)
    return new_id

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def check_service(name):
    try:
        if platform.system() == "Linux":
            rc = subprocess.call(["systemctl", "is-active", "--quiet", name])
        elif platform.system() == "Windows":
            rc = subprocess.call(["sc", "query", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return "unknown"
        return "running" if rc == 0 else "stopped"
    except Exception:
        return "unknown"

def ping_device(ip):
    param = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        subprocess.check_output(["ping", param, "1", ip], timeout=2, stderr=subprocess.STDOUT)
        return True
    except Exception:
        return False

def collect_metrics():
    hostname = socket.gethostname()
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    net = psutil.net_io_counters()

    services = {svc: check_service(svc) for svc in SERVICES_TO_CHECK}
    devices = []
    for dev in NETWORK_DEVICES:
        devices.append({
            "name": dev["name"], "ip": dev["ip"], "type": dev["type"],
            "reachable": ping_device(dev["ip"])
        })

    payload = {
        "hostname": hostname,
        "agent_id": get_agent_id(),
        "ip": get_ip(),
        "uptime": int(time.time() - psutil.boot_time()),
        "cpu": cpu, "memory": mem, "disk": disk,
        "network_sent": net.bytes_sent, "network_recv": net.bytes_recv,
        "services": services, "network_devices": devices,
    }

    group_id = os.getenv("GROUP_ID")
    if group_id and group_id.strip():
        try:
            payload["group_id"] = int(group_id)
        except ValueError:
            pass
    return payload

def main():
    while True:
        try:
            data = collect_metrics()
            resp = requests.post(SERVER_URL, json=data,
                                 headers={"X-API-Key": API_KEY}, timeout=10)
            if resp.status_code == 200:
                print("Metrics sent")
            else:
                print(f"Server error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
''',

    # ---------- TOP LEVEL FILES ----------
    "wsgi.py": '''# wsgi.py - Entry point for Gunicorn
from core.app import app

if __name__ == "__main__":
    app.run()
''',

    "requirements.txt": '''flask
flask-login
pymysql
python-dotenv
requests
psutil
gunicorn
apscheduler
pyOpenSSL
''',

    ".env.example": '''# SysWatch v1.0 Environment Variables (EXAMPLE - copy to .env and fill in)

# Server
SECRET_KEY=your-secret-key-here
DB_HOST=127.0.0.1
DB_USER=monitor
DB_PASSWORD=your-db-password
DB_NAME=monitoring
API_KEY=your-api-key-here
ADMIN_PASSWORD=admin123

# SSL (for development self-signed, optional if using Nginx)
#SSL_CERT=cert.pem
#SSL_KEY=key.pem

# Email (SMTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
ALERT_EMAIL_TO=recipient@example.com

# MS Teams Webhook (optional)
#TEAMS_WEBHOOK_URL=https://your.webhook.url

# Twilio WhatsApp (optional)
#TWILIO_ACCOUNT_SID=
#TWILIO_AUTH_TOKEN=
#TWILIO_FROM_WHATSAPP=
#TWILIO_TO_WHATSAPP=
''',

    "install.sh": '''#!/bin/bash
# SysWatch Linux Installer (Enhanced)
# Run with: sudo bash install.sh

set -e

# Colors
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m'

echo "========================================"
echo "  SysWatch v1.0 Installation (Linux)    "
echo "========================================"

# ---------- Root check ----------
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo).${NC}"
    exit 1
fi

# ---------- OS detection ----------
if [ -f /etc/debian_version ]; then
    OS="debian"
    PKG_MANAGER="apt"
    INSTALL_CMD="apt install -y"
    MYSQL_SERVICE="mysql"
    NGINX_SERVICE="nginx"
elif [ -f /etc/redhat-release ]; then
    OS="redhat"
    PKG_MANAGER="dnf"
    INSTALL_CMD="dnf install -y"
    MYSQL_SERVICE="mysqld"
    NGINX_SERVICE="nginx"
else
    echo -e "${RED}Unsupported OS. Install Python 3.8+, MySQL, Nginx, and Certbot manually.${NC}"
    exit 1
fi

# ---------- Install essential packages (if missing) ----------
echo -e "\\n${GREEN}Checking required packages...${NC}"
REQUIRED_PKGS="python3 python3-pip python3-venv mysql-server nginx certbot python3-certbot-nginx openssl"
if [ "$OS" = "debian" ]; then
    apt update
    for pkg in $REQUIRED_PKGS; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            echo -e "${YELLOW}Installing $pkg...${NC}"
            apt install -y "$pkg"
        else
            echo -e "${GREEN}✔ $pkg already installed.${NC}"
        fi
    done
    apt install -y libmysqlclient-dev build-essential
elif [ "$OS" = "redhat" ]; then
    dnf install -y epel-release
    for pkg in $REQUIRED_PKGS; do
        if ! rpm -q "$pkg" >/dev/null 2>&1; then
            echo -e "${YELLOW}Installing $pkg...${NC}"
            dnf install -y "$pkg"
        else
            echo -e "${GREEN}✔ $pkg already installed.${NC}"
        fi
    done
    dnf install -y mysql-devel gcc
fi

# ---------- Ensure MySQL is running ----------
echo -e "\\n${GREEN}Starting MySQL...${NC}"
if ! systemctl is-active --quiet "$MYSQL_SERVICE"; then
    systemctl start "$MYSQL_SERVICE"
    systemctl enable "$MYSQL_SERVICE"
fi

# ---------- Check existing MySQL DB and user ----------
echo -e "\\n${GREEN}Checking existing MySQL database and user...${NC}"
read -p "Enter database name [monitoring]: " DB_NAME
DB_NAME=${DB_NAME:-monitoring}
read -p "Enter database user [monitor]: " DB_USER
DB_USER=${DB_USER:-monitor}
read -s -p "Enter database password: " DB_PASSWORD
echo
read -s -p "Confirm database password: " DB_PASSWORD_CONFIRM
echo
if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
    echo -e "${RED}Passwords do not match. Exiting.${NC}"
    exit 1
fi

# Check if DB exists
DB_EXISTS=$(mysql -s -N -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='$DB_NAME';" 2>/dev/null || echo "0")
if [ "$DB_EXISTS" -gt 0 ]; then
    echo -e "${YELLOW}Database '$DB_NAME' already exists.${NC}"
    read -p "Do you want to drop and recreate it? (y/n) [n]: " DROP_DB
    DROP_DB=${DROP_DB:-n}
    if [[ "$DROP_DB" =~ ^[Yy]$ ]]; then
        mysql -e "DROP DATABASE $DB_NAME;"
        echo -e "${GREEN}Dropped existing database.${NC}"
    else
        echo -e "${YELLOW}Keeping existing database. Will not create new tables.${NC}"
        SKIP_DB_INIT=1
    fi
fi

# Check if user exists
USER_EXISTS=$(mysql -s -N -e "SELECT COUNT(*) FROM mysql.user WHERE User='$DB_USER' AND Host='localhost';" 2>/dev/null || echo "0")
if [ "$USER_EXISTS" -gt 0 ]; then
    echo -e "${YELLOW}User '$DB_USER' already exists.${NC}"
    read -p "Do you want to drop and recreate the user? (y/n) [n]: " DROP_USER
    DROP_USER=${DROP_USER:-n}
    if [[ "$DROP_USER" =~ ^[Yy]$ ]]; then
        mysql -e "DROP USER '$DB_USER'@'localhost';"
        echo -e "${GREEN}Dropped existing user.${NC}"
    else
        echo -e "${YELLOW}Using existing user. Will not change password.${NC}"
    fi
fi

# Create DB and user if needed
if [ "$DB_EXISTS" -eq 0 ] || [[ "$DROP_DB" =~ ^[Yy]$ ]]; then
    mysql -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;"
fi
if [ "$USER_EXISTS" -eq 0 ] || [[ "$DROP_USER" =~ ^[Yy]$ ]]; then
    mysql -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';"
    mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"
else
    # If user exists and we didn't drop, grant privileges just in case
    mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"
fi

# ---------- SysWatch Admin Password ----------
read -s -p "Enter SysWatch admin password [admin123]: " ADMIN_PASS
ADMIN_PASS=${ADMIN_PASS:-admin123}
echo

# ---------- SMTP (optional) ----------
read -p "Enter SMTP server [smtp.gmail.com]: " SMTP_SERVER
SMTP_SERVER=${SMTP_SERVER:-smtp.gmail.com}
read -p "Enter SMTP port [587]: " SMTP_PORT
SMTP_PORT=${SMTP_PORT:-587}
read -p "Enter SMTP username (email): " SMTP_USER
read -s -p "Enter SMTP password: " SMTP_PASSWORD
echo
read -p "Enter alert recipient email: " ALERT_EMAIL_TO
read -p "Enter Teams webhook URL (leave blank to skip): " TEAMS_WEBHOOK

# ---------- Domain for Nginx ----------
read -p "Enter domain for SysWatch (e.g., syswatch.example.com): " DOMAIN
if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Domain is required for Nginx configuration. Exiting.${NC}"
    exit 1
fi

# ---------- Check DNS resolution ----------
echo -e "\\n${GREEN}Checking DNS resolution for $DOMAIN...${NC}"
SERVER_IP=$(curl -s ifconfig.me || curl -s icanhazip.com || echo "")
if [ -z "$SERVER_IP" ]; then
    echo -e "${YELLOW}Could not determine public IP. Proceeding anyway.${NC}"
else
    DOMAIN_IP=$(dig +short "$DOMAIN" | head -1)
    if [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
        echo -e "${YELLOW}Warning: $DOMAIN does not resolve to this server's IP ($SERVER_IP).${NC}"
        read -p "Continue anyway? (y/n) [n]: " CONTINUE_DNS
        CONTINUE_DNS=${CONTINUE_DNS:-n}
        if [[ ! "$CONTINUE_DNS" =~ ^[Yy]$ ]]; then
            echo -e "${RED}Aborting. Please update DNS record first.${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✔ Domain resolves correctly.${NC}"
    fi
fi

# ---------- Nginx Configuration ----------
echo -e "\\n${GREEN}Setting up Nginx for $DOMAIN...${NC}"
NGINX_CONF="/etc/nginx/sites-available/$DOMAIN"
if [ -f "$NGINX_CONF" ]; then
    echo -e "${YELLOW}Nginx config for $DOMAIN already exists.${NC}"
    read -p "Overwrite? (y/n) [n]: " OVERWRITE_NGINX
    OVERWRITE_NGINX=${OVERWRITE_NGINX:-n}
    if [[ ! "$OVERWRITE_NGINX" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Keeping existing config. Skipping Nginx setup.${NC}"
        SKIP_NGINX=1
    fi
fi

if [ -z "$SKIP_NGINX" ]; then
    # Create initial HTTP config (certbot will modify for HTTPS)
    cat > "$NGINX_CONF" <<EOL
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\\$server_name\\$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name $DOMAIN;

    # SSL will be added by Certbot
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }
}
EOL

    # Enable site
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    # Remove default if it exists
    rm -f /etc/nginx/sites-enabled/default

    # Test and reload Nginx
    nginx -t && systemctl reload nginx
    echo -e "${GREEN}Nginx configured for HTTP.${NC}"

    # ---------- Let's Encrypt ----------
    read -p "Obtain SSL certificate with Let's Encrypt? (y/n) [y]: " DO_LETSENCRYPT
    DO_LETSENCRYPT=${DO_LETSENCRYPT:-y}
    if [[ "$DO_LETSENCRYPT" =~ ^[Yy]$ ]]; then
        read -p "Enter email for Let's Encrypt: " LETSENCRYPT_EMAIL
        if [ -z "$LETSENCRYPT_EMAIL" ]; then
            echo -e "${RED}Email is required for Let's Encrypt. Skipping SSL.${NC}"
        else
            echo -e "${GREEN}Obtaining certificate...${NC}"
            if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL"; then
                echo -e "${GREEN}SSL certificate installed successfully.${NC}"
                systemctl reload nginx
            else
                echo -e "${RED}Let's Encrypt failed. Falling back to HTTP.${NC}"
                # Remove HTTPS server block, keep HTTP only
                cat > "$NGINX_CONF" <<EOL
server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }
}
EOL
                nginx -t && systemctl reload nginx
            fi
        fi
    else
        echo -e "${YELLOW}Skipping SSL. Only HTTP will be available.${NC}"
    fi
fi

# ---------- SysWatch Application Installation ----------
PROJECT_DIR="/opt/syswatch"
echo -e "\\n${GREEN}Installing SysWatch to $PROJECT_DIR...${NC}"
# Backup if exists
if [ -d "$PROJECT_DIR" ]; then
    BACKUP_DIR="/opt/syswatch_backup_$(date +%s)"
    echo -e "${YELLOW}Existing directory found. Backing up to $BACKUP_DIR${NC}"
    mv "$PROJECT_DIR" "$BACKUP_DIR"
fi
mkdir -p "$PROJECT_DIR"
cp -r . "$PROJECT_DIR/"
chown -R $(whoami):$(whoami) "$PROJECT_DIR"
cd "$PROJECT_DIR"

# ---------- Python virtual environment ----------
echo -e "\\n${GREEN}Setting up Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ---------- .env file ----------
API_KEY=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -base64 32)

cat > .env <<EOL
# SysWatch v1.0 Environment Variables
SECRET_KEY=$SECRET_KEY
DB_HOST=127.0.0.1
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
API_KEY=$API_KEY
ADMIN_PASSWORD=$ADMIN_PASS

# SMTP
SMTP_SERVER=$SMTP_SERVER
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
ALERT_EMAIL_TO=$ALERT_EMAIL_TO

# Teams
TEAMS_WEBHOOK_URL=$TEAMS_WEBHOOK
EOL

# ---------- Database initialization ----------
if [ -z "$SKIP_DB_INIT" ]; then
    echo -e "\\n${GREEN}Initializing database...${NC}"
    python3 <<EOF
from core.app import app
from core.database import init_db
with app.app_context():
    init_db()
EOF
else
    echo -e "${YELLOW}Skipping DB initialization (keeping existing tables).${NC}"
fi

# ---------- Systemd service ----------
SERVICE_FILE="/etc/systemd/system/syswatch.service"
if [ -f "$SERVICE_FILE" ]; then
    echo -e "${YELLOW}Systemd service already exists. Stopping and removing old service.${NC}"
    systemctl stop syswatch || true
    systemctl disable syswatch || true
    rm -f "$SERVICE_FILE"
fi

cat > "$SERVICE_FILE" <<EOL
[Unit]
Description=SysWatch Monitoring Server
After=network.target $MYSQL_SERVICE.service
Wants=$MYSQL_SERVICE.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:5000 wsgi:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable syswatch
systemctl start syswatch

# ---------- Final output ----------
echo -e "\\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ SysWatch installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
if [[ "$DO_LETSENCRYPT" =~ ^[Yy]$ ]] && [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo -e "Access URL: https://$DOMAIN"
else
    echo -e "Access URL: http://$DOMAIN"
fi
echo -e "Username: admin"
echo -e "Password: $ADMIN_PASS"
echo -e "API Key: $API_KEY"
echo -e "\\nService status:"
systemctl status syswatch --no-pager
echo -e "\\nTo view logs: sudo journalctl -u syswatch -f"
''',

    "install.ps1": '''# SysWatch Windows Installer (PowerShell)
# Run as Administrator

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SysWatch v1.0 Installation (Windows)  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found. Please install Python 3.8+ from python.org and add it to PATH." -ForegroundColor Red
    Write-Host "After installation, re-run this script." -ForegroundColor Yellow
    exit 1
}
$pyVersion = python --version
Write-Host "Python version: $pyVersion" -ForegroundColor Green

# 2. Check MySQL
$mysql = Get-Command mysql -ErrorAction SilentlyContinue
if (-not $mysql) {
    Write-Host "MySQL not found. Installing via Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
    choco install mysql -y
    Start-Service MySQL
}

# 3. Collect config from user
$DB_NAME = Read-Host -Prompt "Enter database name [monitoring]"
if (-not $DB_NAME) { $DB_NAME = "monitoring" }

$DB_USER = Read-Host -Prompt "Enter database user [monitor]"
if (-not $DB_USER) { $DB_USER = "monitor" }

$DB_PASSWORD = Read-Host -Prompt "Enter database password" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($DB_PASSWORD)
$DB_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)

$ADMIN_PASS = Read-Host -Prompt "Enter SysWatch admin password [admin123]"
if (-not $ADMIN_PASS) { $ADMIN_PASS = "admin123" }

$SMTP_SERVER = Read-Host -Prompt "Enter SMTP server [smtp.gmail.com]"
if (-not $SMTP_SERVER) { $SMTP_SERVER = "smtp.gmail.com" }

$SMTP_PORT = Read-Host -Prompt "Enter SMTP port [587]"
if (-not $SMTP_PORT) { $SMTP_PORT = "587" }

$SMTP_USER = Read-Host -Prompt "Enter SMTP username (email)"
$SMTP_PASSWORD = Read-Host -Prompt "Enter SMTP password" -AsSecureString
$BSTR2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SMTP_PASSWORD)
$SMTP_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR2)

$ALERT_EMAIL_TO = Read-Host -Prompt "Enter alert recipient email"
$TEAMS_WEBHOOK = Read-Host -Prompt "Enter Teams webhook URL (leave blank to skip)"

# Generate keys
$API_KEY = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes([System.Guid]::NewGuid().ToString()))
$SECRET_KEY = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes([System.Guid]::NewGuid().ToString()))

# 4. Setup MySQL DB
Write-Host "Setting up MySQL database..." -ForegroundColor Green
$mysqlCmd = "CREATE DATABASE IF NOT EXISTS $DB_NAME;"
$mysqlCmd += "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';"
$mysqlCmd += "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
$mysqlCmd += "FLUSH PRIVILEGES;"
mysql -u root -e $mysqlCmd

# 5. Copy project files
$PROJECT_DIR = "C:\\\\SysWatch"
Write-Host "Installing SysWatch to $PROJECT_DIR..." -ForegroundColor Green
if (Test-Path $PROJECT_DIR) {
    $backup = "C:\\\\SysWatch_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Move-Item $PROJECT_DIR $backup
}
New-Item -ItemType Directory -Path $PROJECT_DIR -Force
Copy-Item -Path ".\\\\*" -Destination $PROJECT_DIR -Recurse
Set-Location $PROJECT_DIR

# 6. Setup Python venv
Write-Host "Setting up Python virtual environment..." -ForegroundColor Green
python -m venv venv
& .\\\\venv\\\\Scripts\\\\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

# 7. Create .env file
Write-Host "Creating .env configuration..." -ForegroundColor Green
@"
SECRET_KEY=$SECRET_KEY
DB_HOST=127.0.0.1
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
API_KEY=$API_KEY
ADMIN_PASSWORD=$ADMIN_PASS

SMTP_SERVER=$SMTP_SERVER
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
ALERT_EMAIL_TO=$ALERT_EMAIL_TO

TEAMS_WEBHOOK_URL=$TEAMS_WEBHOOK
"@ | Out-File -FilePath .\\.env -Encoding UTF8

# 8. Initialize database
Write-Host "Initializing database..." -ForegroundColor Green
python -c "from core.app import app; from core.database import init_db; with app.app_context(): init_db()"

# 9. Create Windows service using NSSM or scheduled task
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssm) {
    Write-Host "Creating Windows service with NSSM..." -ForegroundColor Green
    nssm install SysWatch "$PROJECT_DIR\\\\venv\\\\Scripts\\\\python.exe"
    nssm set SysWatch AppParameters "$PROJECT_DIR\\\\venv\\\\Scripts\\\\gunicorn --workers 2 --bind 127.0.0.1:5000 wsgi:app"
    nssm set SysWatch AppDirectory $PROJECT_DIR
    nssm set SysWatch Start SERVICE_AUTO_START
    nssm set SysWatch DisplayName "SysWatch Monitoring Server"
    Start-Service SysWatch
} else {
    Write-Host "NSSM not found. Creating scheduled task instead..." -ForegroundColor Yellow
    $action = New-ScheduledTaskAction -Execute "$PROJECT_DIR\\\\venv\\\\Scripts\\\\python.exe" -Argument "$PROJECT_DIR\\\\venv\\\\Scripts\\\\gunicorn --workers 2 --bind 127.0.0.1:5000 wsgi:app" -WorkingDirectory $PROJECT_DIR
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "SysWatch" -Action $action -Trigger $trigger -Settings $settings -User $env:USERNAME -RunLevel Highest
    Start-ScheduledTask -TaskName "SysWatch"
}

# 10. Final output
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "✅ SysWatch installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
$ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
Write-Host "Access URL: http://$($ip):5000 (or localhost:5000)"
Write-Host "Username: admin"
Write-Host "Password: $ADMIN_PASS"
Write-Host "API Key: $API_KEY"
Write-Host "To view logs: Check Event Viewer or service logs."
'''
}

# ============================================================
# SCRIPT EXECUTION
# ============================================================

def create_file(filepath, content):
    full_path = os.path.join(BASE_DIR, filepath)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return full_path

def make_executable(filepath):
    if filepath.endswith('.sh'):
        st = os.stat(filepath)
        os.chmod(filepath, st.st_mode | stat.S_IEXEC)

def main():
    print(f"🚀 Generating SysWatch project in: {BASE_DIR}")
    print("=" * 60)

    created = 0
    for filepath, content in FILES.items():
        full_path = create_file(filepath, content)
        make_executable(full_path)
        created += 1
        print(f"  ✅ {filepath}")

    print("=" * 60)
    print(f"✅ Project generation complete! {created} files created.")
    print("📁 Next steps:")
    print("   1. Review the .env.example file and copy it to .env with your settings")
    print("   2. For Linux: sudo bash install.sh")
    print("   3. For Windows: Run install.ps1 as Administrator")
    print("   4. The systemd service will start automatically after installation")

if __name__ == "__main__":
    main()