# SysWatch Windows Installer (PowerShell)
# Run as Administrator

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SysWatch v1.0 Installation (Windows)  " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Check Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python not found. Please install Python 3.8+ from python.org and add it to PATH." -ForegroundColor Red
    Write-Host "After installation, re-run this script." -ForegroundColor Yellow
    exit 1
}
$pyVersion = python --version
Write-Host "Python version: $pyVersion" -ForegroundColor Green

# 2. Check MySQL
$mysql = Get-Command mysql -ErrorAction SilentlyContinue
if (-not $mysql) {
    Write-Host "MySQL not found. Installing via Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
    choco install mysql -y
    Start-Service MySQL
}

# 3. Collect config from user
$DB_NAME = Read-Host -Prompt "Enter database name [monitoring]"
if (-not $DB_NAME) { $DB_NAME = "monitoring" }

$DB_USER = Read-Host -Prompt "Enter database user [monitor]"
if (-not $DB_USER) { $DB_USER = "monitor" }

$DB_PASSWORD = Read-Host -Prompt "Enter database password" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($DB_PASSWORD)
$DB_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)

$ADMIN_PASS = Read-Host -Prompt "Enter SysWatch admin password [admin123]"
if (-not $ADMIN_PASS) { $ADMIN_PASS = "admin123" }

$SMTP_SERVER = Read-Host -Prompt "Enter SMTP server [smtp.gmail.com]"
if (-not $SMTP_SERVER) { $SMTP_SERVER = "smtp.gmail.com" }

$SMTP_PORT = Read-Host -Prompt "Enter SMTP port [587]"
if (-not $SMTP_PORT) { $SMTP_PORT = "587" }

$SMTP_USER = Read-Host -Prompt "Enter SMTP username (email)"
$SMTP_PASSWORD = Read-Host -Prompt "Enter SMTP password" -AsSecureString
$BSTR2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SMTP_PASSWORD)
$SMTP_PASSWORD = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR2)

$ALERT_EMAIL_TO = Read-Host -Prompt "Enter alert recipient email"
$TEAMS_WEBHOOK = Read-Host -Prompt "Enter Teams webhook URL (leave blank to skip)"

# Generate keys
$API_KEY = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes([System.Guid]::NewGuid().ToString()))
$SECRET_KEY = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes([System.Guid]::NewGuid().ToString()))

# 4. Setup MySQL DB
Write-Host "Setting up MySQL database..." -ForegroundColor Green
$mysqlCmd = "CREATE DATABASE IF NOT EXISTS $DB_NAME;"
$mysqlCmd += "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';"
$mysqlCmd += "GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';"
$mysqlCmd += "FLUSH PRIVILEGES;"
mysql -u root -e $mysqlCmd

# 5. Copy project files
$PROJECT_DIR = "C:\\SysWatch"
Write-Host "Installing SysWatch to $PROJECT_DIR..." -ForegroundColor Green
if (Test-Path $PROJECT_DIR) {
    $backup = "C:\\SysWatch_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Move-Item $PROJECT_DIR $backup
}
New-Item -ItemType Directory -Path $PROJECT_DIR -Force
Copy-Item -Path ".\\*" -Destination $PROJECT_DIR -Recurse
Set-Location $PROJECT_DIR

# 6. Setup Python venv
Write-Host "Setting up Python virtual environment..." -ForegroundColor Green
python -m venv venv
& .\\venv\\Scripts\\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

# 7. Create .env file
Write-Host "Creating .env configuration..." -ForegroundColor Green
@"
SECRET_KEY=$SECRET_KEY
DB_HOST=127.0.0.1
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
API_KEY=$API_KEY
ADMIN_PASSWORD=$ADMIN_PASS

SMTP_SERVER=$SMTP_SERVER
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
ALERT_EMAIL_TO=$ALERT_EMAIL_TO

TEAMS_WEBHOOK_URL=$TEAMS_WEBHOOK
"@ | Out-File -FilePath .\.env -Encoding UTF8

# 8. Initialize database
Write-Host "Initializing database..." -ForegroundColor Green
python -c "from core.app import app; from core.database import init_db; with app.app_context(): init_db()"

# 9. Create Windows service using NSSM or scheduled task
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssm) {
    Write-Host "Creating Windows service with NSSM..." -ForegroundColor Green
    nssm install SysWatch "$PROJECT_DIR\\venv\\Scripts\\python.exe"
    nssm set SysWatch AppParameters "$PROJECT_DIR\\venv\\Scripts\\gunicorn --workers 2 --bind 127.0.0.1:5000 wsgi:app"
    nssm set SysWatch AppDirectory $PROJECT_DIR
    nssm set SysWatch Start SERVICE_AUTO_START
    nssm set SysWatch DisplayName "SysWatch Monitoring Server"
    Start-Service SysWatch
} else {
    Write-Host "NSSM not found. Creating scheduled task instead..." -ForegroundColor Yellow
    $action = New-ScheduledTaskAction -Execute "$PROJECT_DIR\\venv\\Scripts\\python.exe" -Argument "$PROJECT_DIR\\venv\\Scripts\\gunicorn --workers 2 --bind 127.0.0.1:5000 wsgi:app" -WorkingDirectory $PROJECT_DIR
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "SysWatch" -Action $action -Trigger $trigger -Settings $settings -User $env:USERNAME -RunLevel Highest
    Start-ScheduledTask -TaskName "SysWatch"
}

# 10. Final output
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "✅ SysWatch installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
$ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
Write-Host "Access URL: http://$($ip):5000 (or localhost:5000)"
Write-Host "Username: admin"
Write-Host "Password: $ADMIN_PASS"
Write-Host "API Key: $API_KEY"
Write-Host "To view logs: Check Event Viewer or service logs."
