# modules/alert_engine/lifecycle.py
import datetime
from core.database import get_db
from modules.alert_engine.notifiers import dispatch_alert

def evaluate_alerts(hostname, data):
    db = get_db()
    cur = db.cursor()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # Query: match exact hostname, or '%' (global), or NULL (also global)
    cur.execute("SELECT * FROM alert_rules WHERE hostname = %s OR hostname = '%' OR hostname IS NULL", (hostname,))
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
                # Check if there's already an OPEN or ACKNOWLEDGED alert for this metric
                cur.execute(
                    "SELECT id, timestamp, status FROM alerts WHERE hostname=%s AND metric=%s "
                    "AND status IN ('OPEN','ACKNOWLEDGED') ORDER BY timestamp DESC LIMIT 1",
                    (hostname, metric)
                )
                existing = cur.fetchone()
                fire = True
                if existing:
                    last_time = existing[1]
                    # Cooldown check: don't fire if last alert is within cooldown seconds
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
                # If condition no longer violates, resolve any OPEN/ACKNOWLEDGED alerts
                cur.execute(
                    "UPDATE alerts SET status = 'RESOLVED', resolved = 1, resolved_at = %s "
                    "WHERE hostname = %s AND metric = %s AND status IN ('OPEN','ACKNOWLEDGED')",
                    (now, hostname, metric)
                )
                db.commit()
    cur.close()