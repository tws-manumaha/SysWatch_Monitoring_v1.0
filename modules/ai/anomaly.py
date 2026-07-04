# modules/ai/anomaly.py
import statistics
import logging
from core.database import get_db
from modules.alert_engine.notifiers import dispatch_alert

logger = logging.getLogger(__name__)

def run_anomaly_detection():
    from core.app import app  # Import inside to avoid circular import

    with app.app_context():
        db = get_db()
        cur = db.cursor()

        # Get all active hosts (status != DOWN)
        cur.execute("SELECT DISTINCT hostname FROM hosts WHERE status != 'DOWN'")
        hosts = cur.fetchall()

        if not hosts:
            logger.info("No active hosts found for anomaly detection.")
            cur.close()
            return

        logger.info(f"Running anomaly detection for {len(hosts)} host(s)")

        for (hostname,) in hosts:
            for metric in ['cpu', 'memory', 'disk']:
                # Get last 7 days of data (up to 100 points)
                cur.execute(
                    f"SELECT {metric} FROM metrics WHERE hostname = %s AND timestamp >= NOW() - INTERVAL 7 DAY "
                    f"AND {metric} IS NOT NULL ORDER BY timestamp DESC LIMIT 100",
                    (hostname,)
                )
                rows = cur.fetchall()
                if len(rows) < 10:
                    # Not enough data for a reliable baseline
                    continue

                values = [r[0] for r in rows]
                mean = statistics.mean(values)
                std = statistics.stdev(values) if len(values) > 1 else 0

                if std == 0:
                    # No variation – skip
                    continue

                # Get the latest value
                cur.execute(
                    f"SELECT {metric} FROM metrics WHERE hostname = %s AND {metric} IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                    (hostname,)
                )
                current_row = cur.fetchone()
                if not current_row:
                    continue
                current_value = current_row[0]

                # Check if current value exceeds mean + 2*std
                if current_value > mean + (2 * std):
                    deviation = (current_value - mean) / std
                    severity = "WARNING" if deviation < 3 else "CRITICAL"

                    # Insert insight into ai_insights table
                    cur.execute(
                        "INSERT INTO ai_insights (hostname, metric, current_value, baseline_mean, baseline_std, deviation, severity) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (hostname, metric, current_value, mean, std, deviation, severity)
                    )
                    db.commit()
                    logger.info(f"Anomaly detected on {hostname} - {metric}: {current_value:.1f}% (baseline: {mean:.1f}±{std:.1f})")

                    # ✅ NEW: Send alert for BOTH WARNING and CRITICAL
                    dispatch_alert(
                        hostname=hostname,
                        metric=f"ai_{metric}",
                        value=current_value,
                        threshold=round(mean + (2 * std), 2),
                        severity=severity,   # Now sends WARNING and CRITICAL
                        cause=f"AI detected anomaly: {metric} at {current_value:.1f}% (baseline mean: {mean:.1f}%, std: {std:.1f})",
                        action="Investigate this anomaly. Check for recent changes or processes."
                    )

            # Clean old insights (keep only last 7 days)
            cur.execute("DELETE FROM ai_insights WHERE timestamp < NOW() - INTERVAL 7 DAY")
            db.commit()

        cur.close()
        logger.info("Anomaly detection completed.")