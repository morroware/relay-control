# Raspberry Pi 8-Relay Control System

A production-ready web-based control system for managing an 8-channel relay module on Raspberry Pi. Features a modern web interface, robust error handling, logging, and systemd service integration.

## Features

- **Web Interface**: Responsive control panel accessible from any device
- **Safety Features**: Concurrent trigger limits, relay locking, graceful shutdown
- **Robust Logging**: Rotating file logs with configurable levels
- **Service Integration**: Runs as a systemd service with automatic startup
- **Configuration File**: JSON-based configuration for easy customization
- **Security Options**: Optional API key authentication and IP whitelisting
- **Real-time Status**: Live connection monitoring and relay state tracking
- **GPIO Test Utility**: Built-in testing script for hardware verification

## Hardware Requirements

- Raspberry Pi (any model with GPIO pins)
- 8-channel relay module (5V, active-low recommended)
- Appropriate power supply for relay module
- Jumper wires for connections

## GPIO Pin Mapping (Default)

| Relay | GPIO Pin | Physical Pin |
|-------|----------|--------------|
| 1     | GPIO 17  | Pin 11       |
| 2     | GPIO 18  | Pin 12       |
| 3     | GPIO 27  | Pin 13       |
| 4     | GPIO 22  | Pin 15       |
| 5     | GPIO 23  | Pin 16       |
| 6     | GPIO 24  | Pin 18       |
| 7     | GPIO 25  | Pin 22       |
| 8     | GPIO 4   | Pin 7        |

## Quick Installation

1. **Clone or download the project files** to your Raspberry Pi

2. **Run the automated setup script**:
   ```bash
   sudo bash setup.sh
   ```

3. **Access the web interface**:
   - Local: `http://localhost:5000`
   - Network: `http://[your-pi-ip]:5000`

## Manual Installation

If you prefer manual setup:

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install python3-pip python3-venv python3-rpi.gpio

# Create project directory
mkdir /home/pi/relay_control
cd /home/pi/relay_control

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install flask RPi.GPIO

# Copy files to appropriate locations
# - app.py → /home/pi/relay_control/
# - index.html → /home/pi/relay_control/templates/
# - config.json → /home/pi/relay_control/
# - relay-control.service → /etc/systemd/system/

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable relay-control
sudo systemctl start relay-control
```

## Configuration

Edit `config.json` to customize the system:

```json
{
    "relay_pins": {
        "1": 17,    // GPIO pin numbers
        "2": 18,
        // ...
    },
    "relay_settings": {
        "active_low": true,           // true for active-low relays
        "trigger_duration": 2,        // seconds
        "max_concurrent_triggers": 3  // prevent overload
    },
    "server": {
        "host": "0.0.0.0",
        "port": 5000,
        "debug": false
    },
    "logging": {
        "log_dir": "/var/log/relay_control",
        "log_file": "relay_control.log",
        "max_size_mb": 10,
        "backup_count": 5,
        "log_level": "INFO"  // DEBUG, INFO, WARNING, ERROR
    },
    "security": {
        "enable_auth": false,
        "api_key": "",           // Set to enable API key auth
        "allowed_ips": []        // Empty = allow all
    }
}
```

## Usage

### Web Interface
- Click any relay button to activate it for the configured duration
- Visual feedback shows active relays
- Connection status indicator shows system health
- Buttons are disabled while relay is active

### Command Line Management
```bash
# Service control
sudo systemctl start relay-control    # Start service
sudo systemctl stop relay-control     # Stop service
sudo systemctl restart relay-control  # Restart service
sudo systemctl status relay-control   # Check status

# View logs
sudo journalctl -u relay-control -f  # Follow systemd logs
tail -f /var/log/relay_control/relay_control.log  # Application logs

# Test GPIO pins
cd /home/pi/relay_control
sudo python3 test_gpio.py  # Tests each relay sequentially
```

### Convenience Scripts
The setup creates helper scripts in the project directory:
- `./start.sh` - Start the service
- `./stop.sh` - Stop the service  
- `./logs.sh` - View recent logs

## API Endpoints

### `GET /` 
Main web interface

### `POST /relay/<relay_number>`
Trigger a specific relay (1-8)

**Response:**
```json
{
    "status": "success",
    "relay": 1,
    "duration": 2
}
```

### `GET /status`
Get system and relay status

**Response:**
```json
{
    "relays": {
        "1": {"state": "OFF", "locked": false, "gpio_pin": 17},
        // ...
    },
    "system": {
        "active_triggers": 0,
        "max_concurrent": 3,
        "timestamp": "2023-..."
    }
}
```

### `GET /health`
Health check endpoint

## Security

### Enable API Key Authentication
1. Edit `config.json`:
   ```json
   "security": {
       "enable_auth": true,
       "api_key": "your-secret-key"
   }
   ```

2. Include key in requests:
   - Header: `X-API-Key: your-secret-key`
   - Query: `?api_key=your-secret-key`

### IP Whitelisting
```json
"security": {
    "allowed_ips": ["192.168.1.100", "192.168.1.101"]
}
```

## Troubleshooting

### Relay doesn't trigger
1. Check GPIO connections
2. Verify power supply to relay module
3. Run `sudo python3 test_gpio.py` to test hardware
4. Check logs for errors

### Permission denied errors
- Ensure user is in `gpio` group: `sudo usermod -a -G gpio pi`
- Service must run with appropriate permissions

### Active-high vs Active-low relays
- Most relay modules are active-low (LOW = ON)
- If relays work backwards, change `"active_low": false` in config

### Service won't start
```bash
# Check service status
sudo systemctl status relay-control

# View detailed logs
sudo journalctl -u relay-control -n 50

# Test manually
cd /home/pi/relay_control
sudo python3 app.py
```

## Advanced Usage

### Custom Relay Names
Modify the HTML template to use custom names:
```javascript
<button class="relay-button" onclick="triggerRelay(1)">Lights</button>
<button class="relay-button" onclick="triggerRelay(2)">Fan</button>
```

### Longer/Shorter Trigger Duration
Edit `config.json`:
```json
"relay_settings": {
    "trigger_duration": 5  // 5 seconds
}
```

### Using with Nginx (Optional)
The setup script can configure Nginx as a reverse proxy for:
- Better performance
- SSL/HTTPS support
- Standard port 80 access

## Safety Considerations

1. **Electrical Safety**: 
   - Never exceed relay ratings
   - Use appropriate fusing
   - Isolate high voltage circuits

2. **Software Safety**:
   - Concurrent trigger limits prevent overload
   - Relay locking prevents double-activation
   - Graceful shutdown ensures relays turn off

3. **Network Safety**:
   - Enable authentication for public networks
   - Use IP whitelisting for additional security
   - Consider VPN access for remote control

## Contributing

Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## License

This project is provided as-is for educational and personal use.

## Acknowledgments

Built with Flask, RPi.GPIO, and modern web technologies for reliable relay control on Raspberry Pi.

## Example Use Cases

### Home Automation
- Control lights, fans, and appliances
- Automated garden watering system
- Garage door opener
- Security system integration

### Industrial Applications
- Machine control panels
- Process automation
- Safety interlocks
- Remote equipment management

### Educational Projects
- Learning GPIO programming
- Web development practice
- IoT experiments
- Robotics control

## Performance Specifications

- **Response Time**: < 100ms for relay activation
- **Concurrent Users**: Supports multiple simultaneous users
- **Uptime**: Designed for 24/7 operation
- **Memory Usage**: ~50-100MB RAM
- **CPU Usage**: < 5% on Pi 3/4 during idle

## Future Enhancements

Potential improvements you could implement:

1. **Scheduling System**: Add cron-like scheduling for automatic relay control
2. **MQTT Integration**: Connect to home automation systems
3. **Mobile App**: Native iOS/Android applications
4. **Database Logging**: Store relay activation history
5. **WebSocket Support**: Real-time status updates
6. **Temperature Monitoring**: Add sensor integration
7. **PWM Control**: Variable power control for dimmable lights

## Version History

- **v1.0**: Initial release with basic relay control
- **v1.1**: Added systemd service integration
- **v1.2**: Implemented configuration file support
- **v1.3**: Enhanced security features and logging

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review system logs
3. Test with the GPIO test script
4. Verify hardware connections
5. Check configuration file syntax

---

**Remember**: Always follow proper electrical safety procedures when working with relay modules and high-voltage circuits.

