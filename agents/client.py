#!/usr/bin/env python3
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
