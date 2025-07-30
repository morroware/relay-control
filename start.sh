#!/bin/bash
sudo systemctl start relay-control
echo "Relay Control service started"
sudo systemctl status relay-control --no-pager
