# modules/ai/anomaly.py
import statistics
from core.database import get_db
from modules.alert_engine.notifiers import dispatch_alert

def run_anomaly_detection():
    """Scheduled job: detect anomalies in metrics and create AI insights."""
    from core.app import app  # Imported inside function to avoid circular import
    with app.app_context():
        db = get_db()
        cur = db.cursor()

        # Get all active hosts (not DOWN)
        cur.execute("SELECT DISTINCT hostname FROM hosts WHERE status != 'DOWN'")
        hosts = cur.fetchall()

        for (hostname,) in hosts:
            for metric in ['cpu', 'memory', 'disk']:
                # Fetch last 7 days of data for this metric (up to 100 points)
                cur.execute(
                    f"SELECT {metric} FROM metrics WHERE hostname = %s AND timestamp >= NOW() - INTERVAL 7 DAY "
                    f"AND {metric} IS NOT NULL ORDER BY timestamp DESC LIMIT 100",
                    (hostname,)
                )
                rows = cur.fetchall()
                if len(rows) < 10:
                    continue  # Not enough data to establish a baseline

                values = [r[0] for r in rows]
                mean = statistics.mean(values)
                std = statistics.stdev(values) if len(values) > 1 else 0

                if std == 0:
                    continue  # No variation, skip

                # Get the latest value for this metric
                cur.execute(
                    f"SELECT {metric} FROM metrics WHERE hostname = %s AND {metric} IS NOT NULL ORDER BY timestamp DESC LIMIT 1",
                    (hostname,)
                )
                current_row = cur.fetchone()
                if not current_row:
                    continue
                current_value = current_row[0]

                # If current value exceeds mean + 2*std, flag as anomaly
                if current_value > mean + (2 * std):
                    deviation = (current_value - mean) / std
                    severity = "WARNING" if deviation < 3 else "CRITICAL"

                    # Store insight in the database
                    cur.execute(
                        "INSERT INTO ai_insights (hostname, metric, current_value, baseline_mean, baseline_std, deviation, severity) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (hostname, metric, current_value, mean, std, deviation, severity)
                    )
                    db.commit()

                    # If CRITICAL, dispatch an alert
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

                # Clean up old insights (keep only last 7 days)
                cur.execute("DELETE FROM ai_insights WHERE timestamp < NOW() - INTERVAL 7 DAY")
                db.commit()

        cur.close()