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

echo -e "${GREEN}1. Installing system dependencies...${NC}"
apt-get update
apt-get install -y python3-pip python3-venv python3-dev python3-rpi.gpio nginx

echo -e "${GREEN}2. Creating application directory...${NC}"
mkdir -p $APP_DIR
mkdir -p $APP_DIR/templates
mkdir -p $LOG_DIR
chown ${USERNAME}:${USERNAME} $LOG_DIR

# <<< FIX: Change ownership of the app directory to the correct user >>>
chown -R ${USERNAME}:${USERNAME} $APP_DIR

echo -e "${GREEN}3. Creating Python virtual environment...${NC}"
cd $APP_DIR
# Use the USERNAME variable to run the command
sudo -u ${USERNAME} python3 -m venv venv

echo -e "${GREEN}4. Installing Python dependencies...${NC}"
# It's more reliable to call pip from the venv directly
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install flask gunicorn RPi.GPIO

echo -e "${GREEN}5. Setting up GPIO permissions...${NC}"
# Add user to gpio group if not already added
if ! groups ${USERNAME} | grep -q gpio; then
    usermod -a -G gpio ${USERNAME}
    echo -e "${YELLOW}Added user '${USERNAME}' to 'gpio' group${NC}"
fi

echo -e "${GREEN}6. Creating systemd service...${NC}"
# IMPORTANT: This script assumes you have a 'relay-control.service' file
# in the same directory. You must edit that file as well!
cp relay-control.service $SERVICE_FILE
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
sudo tail -n 50 /var/log/relay_control/relay_control.log
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
finally:
    GPIO.cleanup()
    print("GPIO cleaned up")
EOF
chmod +x $APP_DIR/test_gpio.py

echo -e "${GREEN}9. Setting permissions...${NC}"
# Use the USERNAME variable for final ownership
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
    echo -e "${GREEN}Service started!${NC}"
    echo ""
    echo "Access the web interface at:"
    echo "- http://$(hostname -I | cut -d' ' -f1):5000"
    if [[ -f $NGINX_ENABLED ]]; then
        echo "- http://$(hostname -I | cut -d' ' -f1)"
    fi
else
    echo "You can start the service later with: sudo systemctl start $SERVICE_NAME"
fi

echo ""
echo -e "${GREEN}Setup completed successfully!${NC}"

