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
