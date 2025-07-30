#!/bin/bash
# Setup script for 8-Relay Control Service
# Run with: sudo bash setup.sh

set -e

# --- CONFIGURATION ---
# Set your username here
USERNAME="tech"
PROJECT_NAME="8-relay"
# --- END CONFIGURATION ---

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_DIR="/home/${USERNAME}/${PROJECT_NAME}"
SERVICE_NAME="relay-control"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR="/var/log/relay_control"
NGINX_AVAILABLE="/etc/nginx/sites-available/relay-control"
NGINX_ENABLED="/etc/nginx/sites-enabled/relay-control"

echo -e "${GREEN}8-Relay Control Service Setup Script for user '${USERNAME}'${NC}"
echo "==========================================================="

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Check if project directory exists
if [ ! -d "$APP_DIR" ]; then
    echo -e "${RED}Project directory $APP_DIR does not exist!${NC}"
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

echo -e "${GREEN}1. Installing system dependencies...${NC}"
apt-get update
apt-get install -y python3-pip python3-venv python3-dev python3-rpi.gpio nginx

echo -e "${GREEN}2. Creating required directories...${NC}"
mkdir -p $APP_DIR/templates
mkdir -p $LOG_DIR
chown ${USERNAME}:${USERNAME} $LOG_DIR

# Copy HTML file to templates directory
if [ -f "$APP_DIR/index.html" ]; then
    cp "$APP_DIR/index.html" "$APP_DIR/templates/"
    echo -e "${GREEN}Copied index.html to templates directory${NC}"
fi

# If v2-index.html exists and user wants dark theme
if [ -f "$APP_DIR/v2-index.html" ]; then
    echo -e "${YELLOW}Found v2-index.html (dark theme version)${NC}"
    read -p "Do you want to use the dark theme version? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp "$APP_DIR/v2-index.html" "$APP_DIR/templates/index.html"
        echo -e "${GREEN}Using dark theme version${NC}"
    fi
fi

echo -e "${GREEN}3. Creating Python virtual environment...${NC}"
cd $APP_DIR
if [ ! -d "venv" ]; then
    sudo -u ${USERNAME} python3 -m venv venv
else
    echo -e "${YELLOW}Virtual environment already exists${NC}"
fi

echo -e "${GREEN}4. Installing Python dependencies...${NC}"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install flask gunicorn RPi.GPIO

echo -e "${GREEN}5. Setting up GPIO permissions...${NC}"
# Add user to gpio group if not already added
if ! groups ${USERNAME} | grep -q gpio; then
    usermod -a -G gpio ${USERNAME}
    echo -e "${YELLOW}Added user '${USERNAME}' to 'gpio' group${NC}"
fi

echo -e "${GREEN}6. Creating systemd service...${NC}"
cat > $SERVICE_FILE <<EOF
[Unit]
Description=8-Relay Control Service
After=network.target

[Service]
Type=simple
User=${USERNAME}
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/app.py
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable $SERVICE_NAME

echo -e "${GREEN}7. Setting up Nginx reverse proxy (optional)...${NC}"
read -p "Do you want to set up Nginx reverse proxy? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cat > $NGINX_AVAILABLE <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket support (if needed in future)
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Security headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
}
EOF

    # Remove default nginx site if it exists
    if [ -f "/etc/nginx/sites-enabled/default" ]; then
        rm /etc/nginx/sites-enabled/default
    fi

    ln -sf $NGINX_AVAILABLE $NGINX_ENABLED
    nginx -t && systemctl restart nginx
    echo -e "${GREEN}Nginx configured successfully${NC}"
fi

echo -e "${GREEN}8. Creating convenience scripts...${NC}"

# Create start script
cat > $APP_DIR/start.sh <<'EOF'
#!/bin/bash
sudo systemctl start relay-control
echo "Relay Control service started"
sudo systemctl status relay-control --no-pager
EOF
chmod +x $APP_DIR/start.sh

# Create stop script
cat > $APP_DIR/stop.sh <<'EOF'
#!/bin/bash
sudo systemctl stop relay-control
echo "Relay Control service stopped"
EOF
chmod +x $APP_DIR/stop.sh

# Create logs script
cat > $APP_DIR/logs.sh <<'EOF'
#!/bin/bash
echo "=== Recent Relay Control Logs ==="
sudo journalctl -u relay-control -n 50 --no-pager
echo ""
echo "=== Application Log ==="
if [ -f /var/log/relay_control/relay_control.log ]; then
    sudo tail -n 50 /var/log/relay_control/relay_control.log
else
    echo "No application log file found yet"
fi
EOF
chmod +x $APP_DIR/logs.sh

# Create test script
cat > $APP_DIR/test_gpio.py <<'EOF'
#!/usr/bin/env python3
"""Test GPIO pins for relay module"""
import RPi.GPIO as GPIO
import time

RELAY_PINS = [17, 18, 27, 22, 23, 24, 25, 4]

print("GPIO Pin Test for Relay Module")
print("==============================")
print("This will turn each relay ON for 1 second")
print("Press Ctrl+C to stop")

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Setup pins
    for pin in RELAY_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)  # Start with relays OFF (active-low)

    # Test each relay
    for i, pin in enumerate(RELAY_PINS):
        print(f"\nTesting Relay {i+1} (GPIO {pin})...")
        GPIO.output(pin, GPIO.LOW)   # Turn ON
        time.sleep(1)
        GPIO.output(pin, GPIO.HIGH)  # Turn OFF
        print(f"Relay {i+1} test complete")

    print("\nAll relays tested successfully!")

except KeyboardInterrupt:
    print("\nTest interrupted")
except Exception as e:
    print(f"Error: {e}")
finally:
    GPIO.cleanup()
    print("GPIO cleaned up")
EOF
chmod +x $APP_DIR/test_gpio.py

echo -e "${GREEN}9. Setting permissions...${NC}"
chown -R ${USERNAME}:${USERNAME} $APP_DIR
chmod -R 755 $APP_DIR

echo -e "${GREEN}10. Setup complete!${NC}"
echo ""
echo "Important information:"
echo "====================="
echo "1. Application directory: $APP_DIR"
echo "2. Service name: $SERVICE_NAME"
echo "3. Log directory: $LOG_DIR"
echo ""
echo "Useful commands:"
echo "- Start service:  sudo systemctl start $SERVICE_NAME"
echo "- Stop service:   sudo systemctl stop $SERVICE_NAME"
echo "- View status:    sudo systemctl status $SERVICE_NAME"
echo "- View logs:      sudo journalctl -u $SERVICE_NAME -f"
echo "- Test GPIO:      cd $APP_DIR && sudo python3 test_gpio.py"
echo ""
echo "Or use the convenience scripts in $APP_DIR:"
echo "- ./start.sh    - Start the service"
echo "- ./stop.sh     - Stop the service"
echo "- ./logs.sh     - View recent logs"
echo ""

read -p "Do you want to start the service now? (Y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    systemctl start $SERVICE_NAME
    sleep 2
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo -e "${GREEN}Service started successfully!${NC}"
        echo ""
        echo "Access the web interface at:"
        echo "- http://$(hostname -I | cut -d' ' -f1):5000"
        if [[ -f $NGINX_ENABLED ]]; then
            echo "- http://$(hostname -I | cut -d' ' -f1)"
        fi
    else
        echo -e "${RED}Service failed to start. Check logs with: sudo journalctl -u $SERVICE_NAME -n 50${NC}"
    fi
else
    echo "You can start the service later with: sudo systemctl start $SERVICE_NAME"
fi

echo ""
echo -e "${GREEN}Setup completed successfully!${NC}"
