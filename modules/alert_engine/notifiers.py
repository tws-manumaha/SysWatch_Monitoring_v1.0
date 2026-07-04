# modules/alert_engine/notifiers.py
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
