# core/scheduler.py - APScheduler integration
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
