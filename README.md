Raspberry Pi 8-Relay Control SystemA production-ready web-based control system for managing an 8-channel relay module on a Raspberry Pi. Features a color-coded web interface, a web-based admin panel for configuration, robust error handling, logging, and systemd service integration.FeaturesWeb Interface: Responsive, color-coded control panel accessible from any device.Admin Panel: A web page to edit the config.json file and restart the service, protected by a simple password.Safety Features: Concurrent trigger limits, relay locking, and graceful shutdown.Robust Logging: Rotating file logs with configurable levels.Service Integration: Runs as a hardened systemd service with automatic startup.Configuration File: JSON-based configuration for easy customization.Security Options: Optional API key authentication and IP whitelisting.GPIO Test Utility: Built-in testing script for hardware verification.Hardware RequirementsRaspberry Pi (any model with GPIO pins, tested on Pi 4).8-channel relay module (5V, active-low recommended).Separate 5V power supply for the relay module to ensure reliable operation.Jumper wires for connections.GPIO Pin Mapping (Default)RelayGPIO PinPhysical Pin1GPIO 17Pin 112GPIO 18Pin 123GPIO 27Pin 134GPIO 22Pin 155GPIO 23Pin 166GPIO 24Pin 187GPIO 25Pin 228GPIO 4Pin 7Quick InstallationClone the project files to your Raspberry Pi's home directory.git clone <your-repo-url> /home/tech/relay_control
Edit the setup script to set your username.nano /home/tech/relay_control/setup.sh
Change the USERNAME="tech" line at the top if your username is different.Run the automated setup script. This will install dependencies, create directories, and set up the systemd service.cd /home/tech/relay_control
sudo bash setup.sh
Follow the prompts. The script will ask if you want to set up Nginx and start the service.Access the web interface:http://<your-pi-ip>:5000ConfigurationThe main configuration is done via the Admin Panel. For initial setup or manual changes, you can edit /home/tech/relay_control/config.json.{
    "relay_pins": {
        "1": 17,
        "2": 18,
        // ...
    },
    "relay_settings": {
        "active_low": true,
        "trigger_duration": 2,
        "max_concurrent_triggers": 3
    },
    "server": {
        "host": "0.0.0.0",
        "port": 5000
    },
    "logging": {
        "log_dir": "/var/log/relay_control",
        "log_level": "INFO"
    },
    "security": {
        "enable_auth": false,
        "api_key": "",
        "allowed_ips": []
    }
}
UsageWeb InterfaceClick any relay button to activate it for the configured duration.Click the Admin Panel button and enter the password (1313) to access the configuration page.On the Admin Panel, you can change settings and click "Save and Restart Service" to apply them.Command Line ManagementThe setup script creates helper scripts in /home/tech/relay_control:./start.sh - Start the service../stop.sh - Stop the service../logs.sh - View recent logs.You can also use systemctl directly:# Service control
sudo systemctl start relay-control
sudo systemctl stop relay-control
sudo systemctl restart relay-control
sudo systemctl status relay-control

# View logs
sudo journalctl -u relay-control -f
Test GPIO PinsA test script is included to verify your hardware wiring.cd /home/tech/relay_control
sudo python3 test_gpio.py
API EndpointsGET /: Main control panel webpage.GET /admin: Admin configuration webpage.POST /relay/<relay_number>: Trigger a specific relay.GET /status: Get system and relay status.GET /admin/config: Returns the current editable configuration.POST /admin/config: Saves a new configuration and restarts the service.TroubleshootingRelays don't "click" but LEDs light upThis is a power issue. The Raspberry Pi's 5V pin cannot supply enough current for multiple relay coils. You must use a separate 5V power supply for the relay module.Remove the VCC-JDVCC jumper on the relay module.Connect the external 5V supply to the JD-VCC and GND pins.Connect the Raspberry Pi's 5V pin to the VCC pin on the module."Endpoint not found" for Admin PageThe correct URL is /admin, not /admin.html. The application will automatically redirect you."Failed to save configuration file"This is a permissions issue.Read-only file system: The systemd service file uses ProtectHome=read-only for security. Ensure the service file includes ReadWritePaths=/home/tech/relay_control/ to grant write access to the application directory.Incorrect file ownership: Ensure all files in the project directory are owned by your user by running sudo chown -R tech:tech /home/tech/relay_control.Service won't start# Check the service status for errors
sudo systemctl status relay-control

# View detailed logs for tracebacks
sudo journalctl -u relay-control -n 100 --no-pager

# Test running the app manually to see live errors
cd /home/tech/relay_control
sudo -u tech /home/tech/relay_control/venv/bin/python3 app.py

