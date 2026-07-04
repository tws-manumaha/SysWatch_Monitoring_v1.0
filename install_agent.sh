#!/bin/bash
# SysWatch Agent Installer (Linux) - with virtual environment
# Run with: sudo bash install_agent.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  SysWatch Agent Installer (Linux)      "
echo "========================================"

# ---------- Root check ----------
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo).${NC}"
    exit 1
fi

# ---------- OS detection ----------
echo -e "\n${GREEN}Detecting OS...${NC}"
if [ -f /etc/debian_version ]; then
    OS="debian"
    INSTALL_CMD="apt install -y"
    PKG_UPDATE="apt update"
elif [ -f /etc/redhat-release ]; then
    OS="redhat"
    INSTALL_CMD="dnf install -y"
    PKG_UPDATE="dnf check-update || true"
else
    echo -e "${RED}Unsupported OS. Please install Python 3.8+ manually.${NC}"
    exit 1
fi

# ---------- Install Python and venv if missing ----------
echo -e "\n${GREEN}Checking Python and virtual environment support...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python3 not found. Installing...${NC}"
    $PKG_UPDATE
    $INSTALL_CMD python3 python3-venv python3-pip
else
    echo -e "${GREEN}✔ Python3 already installed.${NC}"
fi

# Ensure python3-venv is installed (Debian/Ubuntu)
if [ "$OS" = "debian" ]; then
    if ! dpkg -l | grep -q "^ii  python3-venv "; then
        echo -e "${YELLOW}Installing python3-venv...${NC}"
        $INSTALL_CMD python3-venv
    fi
fi

# ---------- Collect configuration ----------
echo -e "\n${GREEN}Configuration:${NC}"
read -p "Enter SysWatch Server URL (e.g., https://syswatch.fluidthoughts.co.in): " SERVER_URL
SERVER_URL=$(echo "$SERVER_URL" | sed 's:/*$::')
if [ -z "$SERVER_URL" ]; then
    echo -e "${RED}Server URL is required. Exiting.${NC}"
    exit 1
fi

read -p "Enter your SysWatch API Key: " API_KEY
if [ -z "$API_KEY" ]; then
    echo -e "${RED}API Key is required. Exiting.${NC}"
    exit 1
fi

read -p "Enter host group ID (optional, press Enter to skip): " GROUP_ID

# ---------- Create agent directory ----------
AGENT_DIR="/opt/syswatch-agent"
echo -e "\n${GREEN}Creating agent directory at $AGENT_DIR...${NC}"
mkdir -p "$AGENT_DIR"
cd "$AGENT_DIR"

# ---------- Create virtual environment ----------
echo -e "${GREEN}Creating Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install psutil requests python-dotenv
deactivate

# ---------- Write the .env file ----------
echo -e "${GREEN}Creating .env configuration...${NC}"
cat > .env <<EOL
SERVER_URL=${SERVER_URL}/api/report
API_KEY=${API_KEY}
GROUP_ID=${GROUP_ID}
EOL

# ---------- Write the client.py script ----------
echo -e "${GREEN}Creating client.py...${NC}"
cat > client.py <<'EOF'
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
EOF

# Make client.py executable
chmod +x client.py

# ---------- Test the agent (dependencies) ----------
echo -e "\n${GREEN}Testing agent dependencies...${NC}"
if $AGENT_DIR/venv/bin/python -c "import requests, psutil, dotenv; print('✅ Dependencies OK')" 2>/dev/null; then
    echo -e "${GREEN}✅ Dependencies OK.${NC}"
else
    echo -e "${RED}❌ Dependencies failed. Check venv installation.${NC}"
    exit 1
fi

# ---------- Set up systemd service ----------
echo -e "\n${GREEN}Setting up systemd service...${NC}"
SERVICE_FILE="/etc/systemd/system/syswatch-agent.service"

cat > "$SERVICE_FILE" <<EOL
[Unit]
Description=SysWatch Agent
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$AGENT_DIR
ExecStart=$AGENT_DIR/venv/bin/python $AGENT_DIR/client.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable syswatch-agent
systemctl start syswatch-agent

# ---------- Final output ----------
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ SysWatch Agent installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Agent directory: $AGENT_DIR"
echo -e "Virtual environment: $AGENT_DIR/venv"
echo -e "Service status:"
systemctl status syswatch-agent --no-pager
echo -e "\nTo view logs: sudo journalctl -u syswatch-agent -f"
echo -e "\n💡 To add network devices (routers, printers), edit: $AGENT_DIR/client.py"
echo -e "   and modify the 'NETWORK_DEVICES' list, then restart the agent:"
echo -e "   sudo systemctl restart syswatch-agent"