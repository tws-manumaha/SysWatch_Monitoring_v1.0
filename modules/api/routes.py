# modules/api/routes.py - All REST API endpoints
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
