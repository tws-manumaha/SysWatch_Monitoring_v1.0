# modules/alert_engine/lifecycle.py
import datetime
import logging
from core.database import get_db
from modules.alert_engine.notifiers import dispatch_alert

logger = logging.getLogger(__name__)

def evaluate_alerts(hostname, data):
    try:
        db = get_db()
        cur = db.cursor()
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        # FIXED: use placeholder for '%' to avoid pymysql parsing issues
        cur.execute("SELECT * FROM alert_rules WHERE hostname = %s OR hostname = %s OR hostname IS NULL", (hostname, '%'))
        rules = cur.fetchall()

        if not rules:
            logger.info(f"No alert rules found for host {hostname}")
            return

        for rule in rules:
            metric = rule[2]
            if metric not in data:
                continue
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

            logger.info(f"Host {hostname}, metric {metric}, value {value}, threshold {threshold}, violated {violated}")

            if violated:
                # Check for existing OPEN or ACKNOWLEDGED alert for this metric
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
                        logger.info(f"Cooldown active for {hostname} {metric} – not firing")
                if fire:
                    cur.execute(
                        "INSERT INTO alerts (hostname, metric, value, threshold, severity, cause, action, status) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN')",
                        (hostname, metric, value, threshold, severity, cause, action)
                    )
                    db.commit()
                    logger.info(f"Alert fired for {hostname} {metric} = {value} (threshold {threshold})")
                    dispatch_alert(hostname, metric, value, threshold, severity, cause, action)
            else:
                # If condition no longer violates, resolve any OPEN/ACKNOWLEDGED alerts
                cur.execute(
                    "UPDATE alerts SET status = 'RESOLVED', resolved = 1, resolved_at = %s "
                    "WHERE hostname = %s AND metric = %s AND status IN ('OPEN','ACKNOWLEDGED')",
                    (now, hostname, metric)
                )
                db.commit()
                if cur.rowcount > 0:
                    logger.info(f"Resolved alerts for {hostname} {metric}")
        cur.close()
    except Exception as e:
        logger.error(f"Error in evaluate_alerts: {e}", exc_info=True)