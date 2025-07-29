### `setup.sh`
This script is updated to be more robust. It now uses `requirements.txt` and creates a hardened systemd service that runs the application with **Gunicorn**.

```bash
#!/bin/bash
# Setup script for Relay Control Service
# Run with: sudo bash setup.sh

set -e

# --- CONFIGURATION ---
# Set your username here
USERNAME="tech"
# --- END CONFIGURATION ---


# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="/home/${USERNAME}/relay_control"
SERVICE_NAME="relay-control"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR="/var/log/relay_control"
NGINX_AVAILABLE="/etc/nginx/sites-available/relay-control"
NGINX_ENABLED="/etc/nginx/sites-enabled/relay-control"

echo -e "${GREEN}Relay Control Service Setup Script for user '${USERNAME}'${NC}"
echo "==========================================================="

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "${YELLOW}Warning: This doesn't appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get the directory where setup.sh is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo -e "${GREEN}1. Installing system dependencies...${NC}"
apt-get update
# FIX: python3-rpi.gpio is often outdated, install via pip instead.
#      gunicorn is now a primary dependency.
apt-get install -y python3-pip python3-venv python3-dev nginx

echo -e "${GREEN}2. Creating application directory and logs...${NC}"
mkdir -p $APP_DIR/templates
mkdir -p $LOG_DIR
chown ${USERNAME}:${USERNAME} $LOG_DIR

echo -e "${GREEN}3. Copying application files...${NC}"
# FIX: Added requirements.txt to the copy list.
cp -v "${SCRIPT_DIR}/app.py" "${APP_DIR}/" || { echo -e "${RED}Failed to copy app.py${NC}"; exit 1; }
cp -v "${SCRIPT_DIR}/config.json" "${APP_DIR}/" || { echo -e "${RED}Failed to copy config.json${NC}"; exit 1; }
cp -v "${SCRIPT_DIR}/requirements.txt" "${APP_DIR}/" || { echo -e "${RED}Failed to copy requirements.txt${NC}"; exit 1; }
cp -v "${SCRIPT_DIR}/index.html" "${APP_DIR}/templates/" || { echo -e "${RED}Failed to copy index.html${NC}"; exit 1; }
cp -v "${SCRIPT_DIR}/admin.html" "${APP_DIR}/templates/" || { echo -e "${RED}Failed to copy admin.html${NC}"; exit 1; }

# Change ownership of the app directory to the correct user
chown -R ${USERNAME}:${USERNAME} $APP_DIR

echo -e "${GREEN}4. Creating Python virtual environment...${NC}"
cd $APP_DIR
sudo -u ${USERNAME} python3 -m venv venv

echo -e "${GREEN}5. Installing Python dependencies from requirements.txt...${NC}"
# FIX: Install dependencies from requirements.txt for reproducible builds.
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo -e "${GREEN}6. Setting up GPIO permissions...${NC}"
# Add user to gpio group if not already added
if ! groups ${USERNAME} | grep -q gpio; then
    usermod -a -G gpio ${USERNAME}
    echo -e "${YELLOW}Added user '${USERNAME}' to 'gpio' group${NC}"
fi

echo -e "${GREEN}7. Creating systemd service...${NC}"
# FIX: This service file is now hardened for production use.
# - It uses Gunicorn instead of the Flask development server.
# - It includes security and resource-limiting options.
# - It ensures the service has write access only where needed.
cat > $SERVICE_FILE <<EOF
[Unit]
Description=8-Relay Control Web Service
After=network.target

[Service]
Type=simple
User=${USERNAME}
Group=gpio
WorkingDirectory=${APP_DIR}

# FIX: Use Gunicorn to run the app in production. This is more stable and performant.
# It binds to the local host, expecting Nginx to act as a reverse proxy.
ExecStart=${APP_DIR}/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 app:app

Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=relay-control

# FIX: Added service hardening for better security and stability.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
# Make home directories read-only, but grant write access to our app and log directories.
ProtectHome=read-only
ReadWritePaths=${APP_DIR} ${LOG_DIR}

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME

echo -e "${GREEN}8. Setting up Nginx reverse proxy (optional)...${NC}"
read -p "Do you want to set up Nginx reverse proxy? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cat > $NGINX_AVAILABLE <<EOF
server {
    listen 80;
    server_name _;

    location / {
        # Proxy to the gunicorn service running on localhost
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}
EOF

    ln -sf $NGINX_AVAILABLE $NGINX_ENABLED
    # Check nginx config and restart
    if nginx -t; then
        systemctl restart nginx
        echo -e "${GREEN}Nginx configured successfully${NC}"
    else
        echo -e "${RED}Nginx configuration test failed. Please check your Nginx setup.${NC}"
    fi
fi

echo -e "${GREEN}9. Creating convenience scripts...${NC}"
# These scripts help the user manage the service easily.

# Create start script
cat > $APP_DIR/start.sh <<'EOF'
#!/bin/bash
sudo systemctl start relay-control
echo "Relay Control service started"
EOF
chmod +x $APP_DIR/start.sh

# Create stop script
cat > $APP_DIR/stop.sh <<'EOF'
#!/bin/bash
sudo systemctl stop relay-control
echo "Relay Control service stopped"
EOF
chmod +x $APP_DIR/stop.sh

# Create restart script
cat > $APP_DIR/restart.sh <<'EOF'
#!/bin/bash
sudo systemctl restart relay-control
echo "Relay Control service restarted"
EOF
chmod +x $APP_DIR/restart.sh

# Create logs script
cat > $APP_DIR/logs.sh <<'EOF'
#!/bin/bash
echo "=== Viewing real-time service logs (journalctl) ==="
sudo journalctl -u relay-control -f --no-pager
EOF
chmod +x $APP_DIR/logs.sh

echo -e "${GREEN}10. Finalizing permissions...${NC}"
chown -R ${USERNAME}:${USERNAME} $APP_DIR
chmod -R 755 $APP_DIR
chown -R ${USERNAME}:${USERNAME} $LOG_DIR
chmod -R 755 $LOG_DIR

echo -e "${GREEN}11. Setup complete!${NC}"
echo ""
echo "Important information:"
echo "====================="
echo "- Application directory: $APP_DIR"
echo "- Service name: $SERVICE_NAME"
echo "- Log directory: $LOG_DIR"
echo ""
echo "Useful commands (from inside $APP_DIR):"
echo "- ./start.sh    - Start the service"
echo "- ./stop.sh     - Stop the service"
echo "- ./restart.sh  - Restart the service"
echo "- ./logs.sh     - View live service logs"
echo ""

PRIMARY_IP=$(hostname -I | awk '{print $1}')

read -p "Do you want to start the service now? (Y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    systemctl start $SERVICE_NAME
    echo -e "${GREEN}Service started!${NC}"
    echo ""
    echo "Access the web interface at:"
    if [[ -f $NGINX_ENABLED ]]; then
        echo "-> http://${PRIMARY_IP}"
    else
        echo "-> http://${PRIMARY_IP}:5000"
    fi
else
    echo "You can start the service later with: sudo systemctl start $SERVICE_NAME"
fi

echo ""
echo -e "${YELLOW}Note: If user '${USERNAME}' was just added to the 'gpio' group, a REBOOT is recommended for the change to fully apply to the service.${NC}"
