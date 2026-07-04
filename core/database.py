# core/database.py - Database connection and initialization
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
    """Initialize database tables if they don't exist, and insert default alert rules."""
    db = pymysql.connect(**db_config)
    cur = db.cursor()

    # ----- Create tables -----
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
    # SSL Certificates
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
    # AI Insights
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

    # ----- Apply migrations for older installations -----
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

    # ----- Bootstrap admin user -----
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        admin_user = Config.ADMIN_USER
        admin_pass = Config.ADMIN_PASSWORD
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin')",
            (admin_user, generate_password_hash(admin_pass))
        )
        db.commit()

    # ----- Insert default alert rules if none exist -----
    cur.execute("SELECT COUNT(*) FROM alert_rules")
    if cur.fetchone()[0] == 0:
        default_rules = [
            ('%', 'cpu', 90, '>', 'CRITICAL', 300,
             'CPU usage exceeded 90%', 'Check top processes and reduce load.'),
            ('%', 'cpu', 75, '>', 'WARNING', 300,
             'CPU usage exceeded 75%', 'Monitor trends; consider scaling.'),
            ('%', 'memory', 90, '>', 'CRITICAL', 300,
             'Memory usage exceeded 90%', 'Check for memory leaks; add swap or RAM.'),
            ('%', 'memory', 75, '>', 'WARNING', 300,
             'Memory usage exceeded 75%', 'Monitor growth; plan capacity.'),
            ('%', 'disk', 95, '>', 'CRITICAL', 300,
             'Disk usage exceeded 95%', 'Clean up logs; extend volume.'),
            ('%', 'disk', 80, '>', 'WARNING', 300,
             'Disk usage exceeded 80%', 'Review retention; archive old data.'),
        ]
        for rule in default_rules:
            cur.execute(
                "INSERT INTO alert_rules (hostname, metric, threshold, operator, severity, cooldown, cause, action) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                rule
            )
        db.commit()

    cur.close()
    db.close()