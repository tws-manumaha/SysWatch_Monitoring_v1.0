#!/bin/bash
# SysWatch Linux Installer (Enhanced)
# Run with: sudo bash install.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  SysWatch v1.0 Installation (Linux)    "
echo "========================================"

# ---------- Root check ----------
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo).${NC}"
    exit 1
fi

# ---------- OS detection ----------
if [ -f /etc/debian_version ]; then
    OS="debian"
    PKG_MANAGER="apt"
    INSTALL_CMD="apt install -y"
    MYSQL_SERVICE="mysql"
    NGINX_SERVICE="nginx"
elif [ -f /etc/redhat-release ]; then
    OS="redhat"
    PKG_MANAGER="dnf"
    INSTALL_CMD="dnf install -y"
    MYSQL_SERVICE="mysqld"
    NGINX_SERVICE="nginx"
else
    echo -e "${RED}Unsupported OS. Install Python 3.8+, MySQL, Nginx, and Certbot manually.${NC}"
    exit 1
fi

# ---------- Install essential packages (if missing) ----------
echo -e "\n${GREEN}Checking required packages...${NC}"
REQUIRED_PKGS="python3 python3-pip python3-venv mysql-server nginx certbot python3-certbot-nginx openssl"
if [ "$OS" = "debian" ]; then
    apt update
    for pkg in $REQUIRED_PKGS; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            echo -e "${YELLOW}Installing $pkg...${NC}"
            apt install -y "$pkg"
        else
            echo -e "${GREEN}✔ $pkg already installed.${NC}"
        fi
    done
    apt install -y libmysqlclient-dev build-essential
elif [ "$OS" = "redhat" ]; then
    dnf install -y epel-release
    for pkg in $REQUIRED_PKGS; do
        if ! rpm -q "$pkg" >/dev/null 2>&1; then
            echo -e "${YELLOW}Installing $pkg...${NC}"
            dnf install -y "$pkg"
        else
            echo -e "${GREEN}✔ $pkg already installed.${NC}"
        fi
    done
    dnf install -y mysql-devel gcc
fi

# ---------- Ensure MySQL is running ----------
echo -e "\n${GREEN}Starting MySQL...${NC}"
if ! systemctl is-active --quiet "$MYSQL_SERVICE"; then
    systemctl start "$MYSQL_SERVICE"
    systemctl enable "$MYSQL_SERVICE"
fi

# ---------- Check existing MySQL DB and user ----------
echo -e "\n${GREEN}Checking existing MySQL database and user...${NC}"
read -p "Enter database name [monitoring]: " DB_NAME
DB_NAME=${DB_NAME:-monitoring}
read -p "Enter database user [monitor]: " DB_USER
DB_USER=${DB_USER:-monitor}
read -s -p "Enter database password: " DB_PASSWORD
echo
read -s -p "Confirm database password: " DB_PASSWORD_CONFIRM
echo
if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
    echo -e "${RED}Passwords do not match. Exiting.${NC}"
    exit 1
fi

# Check if DB exists
DB_EXISTS=$(mysql -s -N -e "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='$DB_NAME';" 2>/dev/null || echo "0")
if [ "$DB_EXISTS" -gt 0 ]; then
    echo -e "${YELLOW}Database '$DB_NAME' already exists.${NC}"
    read -p "Do you want to drop and recreate it? (y/n) [n]: " DROP_DB
    DROP_DB=${DROP_DB:-n}
    if [[ "$DROP_DB" =~ ^[Yy]$ ]]; then
        mysql -e "DROP DATABASE $DB_NAME;"
        echo -e "${GREEN}Dropped existing database.${NC}"
    else
        echo -e "${YELLOW}Keeping existing database. Will not create new tables.${NC}"
        SKIP_DB_INIT=1
    fi
fi

# Check if user exists
USER_EXISTS=$(mysql -s -N -e "SELECT COUNT(*) FROM mysql.user WHERE User='$DB_USER' AND Host='localhost';" 2>/dev/null || echo "0")
if [ "$USER_EXISTS" -gt 0 ]; then
    echo -e "${YELLOW}User '$DB_USER' already exists.${NC}"
    read -p "Do you want to drop and recreate the user? (y/n) [n]: " DROP_USER
    DROP_USER=${DROP_USER:-n}
    if [[ "$DROP_USER" =~ ^[Yy]$ ]]; then
        mysql -e "DROP USER '$DB_USER'@'localhost';"
        echo -e "${GREEN}Dropped existing user.${NC}"
    else
        echo -e "${YELLOW}Using existing user. Will not change password.${NC}"
    fi
fi

# Create DB and user if needed
if [ "$DB_EXISTS" -eq 0 ] || [[ "$DROP_DB" =~ ^[Yy]$ ]]; then
    mysql -e "CREATE DATABASE IF NOT EXISTS $DB_NAME;"
fi
if [ "$USER_EXISTS" -eq 0 ] || [[ "$DROP_USER" =~ ^[Yy]$ ]]; then
    mysql -e "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';"
    mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"
else
    # If user exists and we didn't drop, grant privileges just in case
    mysql -e "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
    mysql -e "FLUSH PRIVILEGES;"
fi

# ---------- SysWatch Admin Password ----------
read -s -p "Enter SysWatch admin password [admin123]: " ADMIN_PASS
ADMIN_PASS=${ADMIN_PASS:-admin123}
echo

# ---------- SMTP (optional) ----------
read -p "Enter SMTP server [smtp.gmail.com]: " SMTP_SERVER
SMTP_SERVER=${SMTP_SERVER:-smtp.gmail.com}
read -p "Enter SMTP port [587]: " SMTP_PORT
SMTP_PORT=${SMTP_PORT:-587}
read -p "Enter SMTP username (email): " SMTP_USER
read -s -p "Enter SMTP password: " SMTP_PASSWORD
echo
read -p "Enter alert recipient email: " ALERT_EMAIL_TO
read -p "Enter Teams webhook URL (leave blank to skip): " TEAMS_WEBHOOK

# ---------- Domain for Nginx ----------
read -p "Enter domain for SysWatch (e.g., syswatch.example.com): " DOMAIN
if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Domain is required for Nginx configuration. Exiting.${NC}"
    exit 1
fi

# ---------- Check DNS resolution ----------
echo -e "\n${GREEN}Checking DNS resolution for $DOMAIN...${NC}"
SERVER_IP=$(curl -s ifconfig.me || curl -s icanhazip.com || echo "")
if [ -z "$SERVER_IP" ]; then
    echo -e "${YELLOW}Could not determine public IP. Proceeding anyway.${NC}"
else
    DOMAIN_IP=$(dig +short "$DOMAIN" | head -1)
    if [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
        echo -e "${YELLOW}Warning: $DOMAIN does not resolve to this server's IP ($SERVER_IP).${NC}"
        read -p "Continue anyway? (y/n) [n]: " CONTINUE_DNS
        CONTINUE_DNS=${CONTINUE_DNS:-n}
        if [[ ! "$CONTINUE_DNS" =~ ^[Yy]$ ]]; then
            echo -e "${RED}Aborting. Please update DNS record first.${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✔ Domain resolves correctly.${NC}"
    fi
fi

# ---------- Nginx Configuration ----------
echo -e "\n${GREEN}Setting up Nginx for $DOMAIN...${NC}"
NGINX_CONF="/etc/nginx/sites-available/$DOMAIN"
if [ -f "$NGINX_CONF" ]; then
    echo -e "${YELLOW}Nginx config for $DOMAIN already exists.${NC}"
    read -p "Overwrite? (y/n) [n]: " OVERWRITE_NGINX
    OVERWRITE_NGINX=${OVERWRITE_NGINX:-n}
    if [[ ! "$OVERWRITE_NGINX" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Keeping existing config. Skipping Nginx setup.${NC}"
        SKIP_NGINX=1
    fi
fi

if [ -z "$SKIP_NGINX" ]; then
    # Create initial HTTP config (certbot will modify for HTTPS)
    cat > "$NGINX_CONF" <<EOL
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name $DOMAIN;

    # SSL will be added by Certbot
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOL

    # Enable site
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    # Remove default if it exists
    rm -f /etc/nginx/sites-enabled/default

    # Test and reload Nginx
    nginx -t && systemctl reload nginx
    echo -e "${GREEN}Nginx configured for HTTP.${NC}"

    # ---------- Let's Encrypt ----------
    read -p "Obtain SSL certificate with Let's Encrypt? (y/n) [y]: " DO_LETSENCRYPT
    DO_LETSENCRYPT=${DO_LETSENCRYPT:-y}
    if [[ "$DO_LETSENCRYPT" =~ ^[Yy]$ ]]; then
        read -p "Enter email for Let's Encrypt: " LETSENCRYPT_EMAIL
        if [ -z "$LETSENCRYPT_EMAIL" ]; then
            echo -e "${RED}Email is required for Let's Encrypt. Skipping SSL.${NC}"
        else
            echo -e "${GREEN}Obtaining certificate...${NC}"
            if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$LETSENCRYPT_EMAIL"; then
                echo -e "${GREEN}SSL certificate installed successfully.${NC}"
                systemctl reload nginx
            else
                echo -e "${RED}Let's Encrypt failed. Falling back to HTTP.${NC}"
                # Remove HTTPS server block, keep HTTP only
                cat > "$NGINX_CONF" <<EOL
server {
    listen 80;
    server_name $DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOL
                nginx -t && systemctl reload nginx
            fi
        fi
    else
        echo -e "${YELLOW}Skipping SSL. Only HTTP will be available.${NC}"
    fi
fi

# ---------- SysWatch Application Installation ----------
PROJECT_DIR="/opt/syswatch"
echo -e "\n${GREEN}Installing SysWatch to $PROJECT_DIR...${NC}"
# Backup if exists
if [ -d "$PROJECT_DIR" ]; then
    BACKUP_DIR="/opt/syswatch_backup_$(date +%s)"
    echo -e "${YELLOW}Existing directory found. Backing up to $BACKUP_DIR${NC}"
    mv "$PROJECT_DIR" "$BACKUP_DIR"
fi
mkdir -p "$PROJECT_DIR"
cp -r . "$PROJECT_DIR/"
chown -R $(whoami):$(whoami) "$PROJECT_DIR"
cd "$PROJECT_DIR"

# ---------- Python virtual environment ----------
echo -e "\n${GREEN}Setting up Python virtual environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ---------- .env file ----------
API_KEY=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -base64 32)

cat > .env <<EOL
# SysWatch v1.0 Environment Variables
SECRET_KEY=$SECRET_KEY
DB_HOST=127.0.0.1
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
API_KEY=$API_KEY
ADMIN_PASSWORD=$ADMIN_PASS

# SMTP
SMTP_SERVER=$SMTP_SERVER
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
ALERT_EMAIL_TO=$ALERT_EMAIL_TO

# Teams
TEAMS_WEBHOOK_URL=$TEAMS_WEBHOOK
EOL

# ---------- Database initialization ----------
if [ -z "$SKIP_DB_INIT" ]; then
    echo -e "\n${GREEN}Initializing database...${NC}"
    python3 <<EOF
from core.app import app
from core.database import init_db
with app.app_context():
    init_db()
EOF
else
    echo -e "${YELLOW}Skipping DB initialization (keeping existing tables).${NC}"
fi

# ---------- Systemd service ----------
SERVICE_FILE="/etc/systemd/system/syswatch.service"
if [ -f "$SERVICE_FILE" ]; then
    echo -e "${YELLOW}Systemd service already exists. Stopping and removing old service.${NC}"
    systemctl stop syswatch || true
    systemctl disable syswatch || true
    rm -f "$SERVICE_FILE"
fi

cat > "$SERVICE_FILE" <<EOL
[Unit]
Description=SysWatch Monitoring Server
After=network.target $MYSQL_SERVICE.service
Wants=$MYSQL_SERVICE.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:5000 wsgi:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

systemctl daemon-reload
systemctl enable syswatch
systemctl start syswatch

# ---------- Final output ----------
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✅ SysWatch installation complete!${NC}"
echo -e "${GREEN}========================================${NC}"
if [[ "$DO_LETSENCRYPT" =~ ^[Yy]$ ]] && [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo -e "Access URL: https://$DOMAIN"
else
    echo -e "Access URL: http://$DOMAIN"
fi
echo -e "Username: admin"
echo -e "Password: $ADMIN_PASS"
echo -e "API Key: $API_KEY"
echo -e "\nService status:"
systemctl status syswatch --no-pager
echo -e "\nTo view logs: sudo journalctl -u syswatch -f"
