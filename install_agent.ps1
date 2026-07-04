# SysWatch Agent Installer (Windows)
# Run as Administrator in PowerShell

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SysWatch Agent Installer (Windows)    " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ---------- Check Admin rights ----------
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "❌ Please run this script as Administrator." -ForegroundColor Red
    exit 1
}

# ---------- Check/Install Python ----------
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "🐍 Python not found. Downloading and installing Python..." -ForegroundColor Yellow
    $pythonUrl = "https://www.python.org/ftp/python/3.11.5/python-3.11.5-amd64.exe"
    $installerPath = "$env:TEMP\python-installer.exe"
    Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath
    Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1" -Wait
    Remove-Item $installerPath -Force
    Write-Host "✅ Python installed. Please restart PowerShell and re-run this script." -ForegroundColor Green
    exit 0
} else {
    Write-Host "✅ Python found: $(python --version)" -ForegroundColor Green
}

# ---------- Create agent directory ----------
$AGENT_DIR = "C:\SysWatchAgent"
Write-Host "`n📁 Creating agent directory at $AGENT_DIR..." -ForegroundColor Green
New-Item -ItemType Directory -Path $AGENT_DIR -Force | Out-Null
Set-Location $AGENT_DIR

# ---------- Create virtual environment ----------
Write-Host "🐍 Creating Python virtual environment..." -ForegroundColor Green
python -m venv venv
$venvPython = "$AGENT_DIR\venv\Scripts\python.exe"
$venvPip = "$AGENT_DIR\venv\Scripts\pip.exe"

Write-Host "📦 Installing required packages in venv..." -ForegroundColor Green
& $venvPip install --upgrade pip
& $venvPip install psutil requests python-dotenv

# ---------- Collect configuration ----------
Write-Host "`n⚙️  Configuration:" -ForegroundColor Green
$SERVER_URL = Read-Host -Prompt "Enter SysWatch Server URL (e.g., https://syswatch.fluidthoughts.co.in)"
$SERVER_URL = $SERVER_URL.TrimEnd('/')
if ([string]::IsNullOrEmpty($SERVER_URL)) {
    Write-Host "❌ Server URL is required. Exiting." -ForegroundColor Red
    exit 1
}

$API_KEY = Read-Host -Prompt "Enter your SysWatch API Key"
if ([string]::IsNullOrEmpty($API_KEY)) {
    Write-Host "❌ API Key is required. Exiting." -ForegroundColor Red
    exit 1
}

$GROUP_ID = Read-Host -Prompt "Enter host group ID (optional, press Enter to skip)"

# ---------- Write .env file ----------
Write-Host "📝 Creating .env configuration..." -ForegroundColor Green
@"
SERVER_URL=${SERVER_URL}/api/report
API_KEY=${API_KEY}
GROUP_ID=${GROUP_ID}
"@ | Out-File -FilePath .\.env -Encoding UTF8

# ---------- Write client.py ----------
Write-Host "📝 Creating client.py..." -ForegroundColor Green
@'
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
    print(f"🚀 SysWatch Agent starting...")
    print(f"📡 Target: {SERVER_URL}")
    while True:
        try:
            data = collect_metrics()
            resp = requests.post(SERVER_URL, json=data,
                                 headers={"X-API-Key": API_KEY}, timeout=10)
            if resp.status_code == 200:
                print("✅ Metrics sent")
            else:
                print(f"❌ Server error {resp.status_code}: {resp.text}")
        except requests.exceptions.ConnectionError:
            print("❌ Connection error: Cannot reach SysWatch server. Check URL and network.")
        except Exception as e:
            print(f"❌ Error: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
'@ | Out-File -FilePath .\client.py -Encoding UTF8

# ---------- Test the agent (dependencies) ----------
Write-Host "`n🔍 Testing agent dependencies..." -ForegroundColor Green
try {
    & $venvPython -c "import requests, psutil, dotenv; print('✅ Dependencies OK')"
} catch {
    Write-Host "❌ Dependencies missing. Please check installation." -ForegroundColor Red
    exit 1
}

# ---------- Set up Scheduled Task ----------
Write-Host "`n⏰ Setting up Scheduled Task..." -ForegroundColor Green
$action = New-ScheduledTaskAction -Execute "$venvPython" -Argument "$AGENT_DIR\client.py" -WorkingDirectory $AGENT_DIR
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "SysWatchAgent" -Action $action -Trigger $trigger -Settings $settings -User $env:USERNAME -RunLevel Highest -Force
Start-ScheduledTask -TaskName "SysWatchAgent"

# ---------- Final output ----------
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "✅ SysWatch Agent installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Agent directory: $AGENT_DIR"
Write-Host "Virtual environment: $AGENT_DIR\venv"
Write-Host "Scheduled Task: SysWatchAgent"
Write-Host "`nTo view logs, check the console output or run the agent manually."
Write-Host "`n💡 To add network devices (routers, printers), edit: $AGENT_DIR\client.py"
Write-Host "   and modify the 'NETWORK_DEVICES' list, then restart the Scheduled Task."