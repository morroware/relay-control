#!/usr/bin/env python3
"""
Production-ready Flask application for controlling an 8-relay module on Raspberry Pi
Each relay can be triggered for 2 seconds via web interface.
Includes an admin panel for configuration.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, jsonify, request, redirect, url_for
import RPi.GPIO as GPIO
import time
import threading
import signal
import atexit
from datetime import datetime
import json
from pathlib import Path
import subprocess # New import for running shell commands

# --- Configuration Class (largely unchanged) ---
class Config:
    """Configuration management with JSON file support"""
    _defaults = {
        "relay_pins": {
            "1": 17, "2": 18, "3": 27, "4": 22,
            "5": 23, "6": 24, "7": 25, "8": 4
        },
        "relay_settings": {
            "active_low": True,
            "trigger_duration": 2,
            "max_concurrent_triggers": 3
        },
        "server": {
            "host": "0.0.0.0",
            "port": 5000,
            "debug": False
        },
        "logging": {
            "log_dir": "/var/log/relay_control",
            "log_file": "relay_control.log",
            "max_size_mb": 10,
            "backup_count": 5,
            "log_level": "INFO"
        },
        "security": {
            "enable_auth": False,
            "api_key": "",
            "allowed_ips": []
        }
    }

    def __init__(self, config_file="config.json"):
        self.config_file = Path(config_file).resolve()
        self.config = self._load_config()

    def _load_config(self):
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    user_config = json.load(f)
                    config = self._defaults.copy()
                    self._deep_update(config, user_config)
                    print(f"Configuration loaded from {self.config_file}")
                    return config
            else:
                print(f"No config file found at {self.config_file}, using defaults")
                with open(self.config_file, 'w') as f:
                    json.dump(self._defaults, f, indent=4)
                return self._defaults.copy()
        except Exception as e:
            print(f"Error loading config: {e}, using defaults")
            return self._defaults.copy()

    def _deep_update(self, base, update):
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def save_config(self, new_config):
        """Saves the provided configuration dictionary to the file."""
        try:
            # Merge the new settings into the current full config
            # to preserve sections not edited by the form (e.g., server, logging)
            self._deep_update(self.config, new_config)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception as e:
            # Use the app's logger for better traceability and a full traceback
            app.logger.error(f"Failed to save configuration to {self.config_file}: {e}", exc_info=True)
            return False
            
    # --- Properties (unchanged) ---
    @property
    def RELAY_PINS(self): return {int(k): v for k, v in self.config["relay_pins"].items()}
    @property
    def RELAY_ACTIVE_LOW(self): return self.config["relay_settings"]["active_low"]
    @property
    def RELAY_TRIGGER_DURATION(self): return self.config["relay_settings"]["trigger_duration"]
    @property
    def MAX_CONCURRENT_TRIGGERS(self): return self.config["relay_settings"]["max_concurrent_triggers"]
    @property
    def HOST(self): return self.config["server"]["host"]
    @property
    def PORT(self): return self.config["server"]["port"]
    @property
    def DEBUG(self): return self.config["server"]["debug"]
    @property
    def LOG_DIR(self): return self.config["logging"]["log_dir"]
    @property
    def LOG_FILE(self): return self.config["logging"]["log_file"]
    @property
    def LOG_MAX_SIZE(self): return self.config["logging"]["max_size_mb"] * 1024 * 1024
    @property
    def LOG_BACKUP_COUNT(self): return self.config["logging"]["backup_count"]
    @property
    def LOG_LEVEL(self): return self.config["logging"]["log_level"]
    @property
    def ENABLE_AUTH(self): return self.config["security"]["enable_auth"]
    @property
    def API_KEY(self): return self.config["security"]["api_key"]
    @property
    def ALLOWED_IPS(self): return self.config["security"]["allowed_ips"]


# --- Global variables, Logging, GPIO Setup (unchanged) ---
app = Flask(__name__)
# Make sure the config file path is absolute or relative to the app's location
config_path = Path(__file__).parent / "config.json"
config = Config(config_path)
relay_locks = {}
active_triggers = 0
active_triggers_lock = threading.Lock()
cleanup_done = False

def setup_logging():
    # (Function content is unchanged)
    try:
        Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
        log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler = RotatingFileHandler(os.path.join(config.LOG_DIR, config.LOG_FILE), maxBytes=config.LOG_MAX_SIZE, backupCount=config.LOG_BACKUP_COUNT)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)
        app.logger.setLevel(log_level)
        app.logger.addHandler(file_handler)
        app.logger.addHandler(console_handler)
        werkzeug_logger = logging.getLogger('werkzeug')
        werkzeug_logger.setLevel(logging.WARNING)
        werkzeug_logger.addHandler(file_handler)
        werkzeug_logger.addHandler(console_handler)
    except Exception as e:
        print(f"Failed to setup logging: {e}")
        logging.basicConfig(level=logging.INFO)

def setup_gpio():
    # (Function content is unchanged)
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for relay_num, pin in config.RELAY_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            initial_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            GPIO.output(pin, initial_state)
            relay_locks[relay_num] = threading.Lock()
        app.logger.info("GPIO initialization successful")
        return True
    except Exception as e:
        app.logger.error(f"GPIO initialization failed: {e}")
        return False

def trigger_relay(relay_num):
    # (Function content is unchanged)
    global active_triggers
    if relay_num not in config.RELAY_PINS:
        app.logger.error(f"Invalid relay number: {relay_num}")
        return False
    with active_triggers_lock:
        if active_triggers >= config.MAX_CONCURRENT_TRIGGERS:
            app.logger.warning(f"Max concurrent triggers reached, rejecting relay {relay_num}")
            return False
        active_triggers += 1
    try:
        if not relay_locks[relay_num].acquire(blocking=False):
            app.logger.warning(f"Relay {relay_num} is already active")
            with active_triggers_lock:
                active_triggers -= 1
            return False
        pin = config.RELAY_PINS[relay_num]
        on_state = GPIO.LOW if config.RELAY_ACTIVE_LOW else GPIO.HIGH
        GPIO.output(pin, on_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned ON")
        time.sleep(config.RELAY_TRIGGER_DURATION)
        off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
        GPIO.output(pin, off_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned OFF")
        return True
    except Exception as e:
        app.logger.error(f"Error triggering relay {relay_num}: {e}")
        return False
    finally:
        relay_locks[relay_num].release()
        with active_triggers_lock:
            active_triggers -= 1

# --- Security Check (modified to protect admin routes) ---
@app.before_request
def check_auth():
    """Check authentication if enabled. Protects all routes except health_check."""
    # Allow health check to always pass
    if request.endpoint == 'health_check':
        return

    # Check if auth is enabled in config
    if config.ENABLE_AUTH:
        # Check for admin routes specifically
        if request.path.startswith('/admin'):
            # Simple API key check for admin access
            provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            if not config.API_KEY or provided_key != config.API_KEY:
                return jsonify({'status': 'error', 'message': 'Authentication required for admin panel'}), 401
        
        # IP whitelist check for all routes
        if config.ALLOWED_IPS:
            client_ip = request.remote_addr
            if client_ip not in config.ALLOWED_IPS:
                app.logger.warning(f"Unauthorized access attempt from {client_ip}")
                return jsonify({'status': 'error', 'message': 'Unauthorized IP'}), 403


# --- Main Routes (unchanged) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/relay/<int:relay_num>', methods=['POST'])
def control_relay(relay_num):
    if relay_num < 1 or relay_num > len(config.RELAY_PINS):
        return jsonify({'status': 'error', 'message': 'Invalid relay number'}), 400
    client_ip = request.remote_addr
    app.logger.info(f"Relay {relay_num} trigger requested from {client_ip}")
    if relay_locks[relay_num].locked():
        return jsonify({'status': 'error', 'message': 'Relay is already active'}), 429
    thread = threading.Thread(target=trigger_relay, args=(relay_num,))
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'success', 'relay': relay_num, 'duration': config.RELAY_TRIGGER_DURATION})

@app.route('/status')
def get_status():
    # (Function content is unchanged)
    try:
        status = {'relays': {}, 'system': {'active_triggers': active_triggers, 'max_concurrent': config.MAX_CONCURRENT_TRIGGERS, 'timestamp': datetime.now().isoformat()}}
        for relay_num, pin in config.RELAY_PINS.items():
            current_state = GPIO.input(pin)
            is_on = (current_state == GPIO.LOW) if config.RELAY_ACTIVE_LOW else (current_state == GPIO.HIGH)
            status['relays'][relay_num] = {'state': 'ON' if is_on else 'OFF', 'locked': relay_locks[relay_num].locked(), 'gpio_pin': pin}
        return jsonify(status)
    except Exception as e:
        app.logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})


# --- NEW: Admin Panel Routes ---
@app.route('/admin.html')
def admin_html_redirect():
    """Redirects /admin.html to /admin for user convenience."""
    return redirect(url_for('admin_panel'))

@app.route('/admin')
def admin_panel():
    """Serves the admin configuration page."""
    return render_template('admin.html')

@app.route('/admin/config', methods=['GET'])
def get_config():
    """Returns the current configuration as JSON."""
    # Return only the sections that are editable in the admin panel
    editable_config = {
        "relay_pins": config.config["relay_pins"],
        "relay_settings": config.config["relay_settings"]
    }
    return jsonify(editable_config)

@app.route('/admin/config', methods=['POST'])
def set_config():
    """Receives new configuration, saves it, and restarts the service."""
    new_config = request.get_json()
    if not new_config:
        return jsonify({'status': 'error', 'message': 'Invalid data received'}), 400

    app.logger.info("Received new configuration. Saving...")
    if config.save_config(new_config):
        app.logger.info("Configuration saved. Triggering service restart.")
        
        # Use a separate thread to restart the service to allow the response to be sent
        def restart_service():
            time.sleep(1) # Give a moment for the response to send
            try:
                # IMPORTANT: This command requires the user running the app ('tech')
                # to have passwordless sudo permissions for systemctl.
                subprocess.run(["sudo", "systemctl", "restart", "relay-control.service"], check=True)
                app.logger.info("Service restart command issued.")
            except subprocess.CalledProcessError as e:
                app.logger.error(f"Failed to restart service: {e}")
            except FileNotFoundError:
                app.logger.error("Could not find 'sudo' command. Ensure it's in the system's PATH.")

        threading.Thread(target=restart_service).start()
        
        return jsonify({'status': 'success', 'message': 'Configuration saved. Restarting service.'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to save configuration file.'}), 500


# --- Error Handlers & Cleanup (unchanged) ---
@app.errorhandler(404)
def not_found(error):
    return jsonify({'status': 'error', 'message': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal error: {error}")
    return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

def cleanup_gpio():
    # (Function content is unchanged)
    global cleanup_done
    if not cleanup_done:
        cleanup_done = True
        try:
            off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            for pin in config.RELAY_PINS.values():
                GPIO.output(pin, off_state)
            GPIO.cleanup()
            app.logger.info("GPIO cleanup completed")
        except Exception as e:
            app.logger.error(f"Error during GPIO cleanup: {e}")

def signal_handler(signum, frame):
    app.logger.info(f"Received signal {signum}, shutting down...")
    cleanup_gpio()
    sys.exit(0)

atexit.register(cleanup_gpio)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def main():
    setup_logging()
    app.logger.info("Starting Relay Control Application")
    if not setup_gpio():
        app.logger.error("Failed to initialize GPIO, exiting")
        sys.exit(1)
    try:
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False)
    except Exception as e:
        app.logger.error(f"Application error: {e}")
        cleanup_gpio()
        sys.exit(1)

if __name__ == '__main__':
    main()

