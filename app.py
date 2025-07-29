#!/usr/bin/env python3
"""
Production-ready Flask application for controlling an 8-relay module on Raspberry Pi
Each relay can have individual trigger durations via web interface or physical button.
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
import subprocess

# --- Configuration Class ---
# This class handles loading, saving, and providing access to all settings
# from the config.json file. It uses defaults if the file is missing.
class Config:
    """Configuration management with JSON file support"""
    # Default settings, used if config.json is missing or invalid.
    _defaults = {
        "relay_pins": {
            "1": 17, "2": 18, "3": 27, "4": 22,
            "5": 23, "6": 24, "7": 25, "8": 4
        },
        "relay_settings": {
            "active_low": True,
            "max_concurrent_triggers": 3
        },
        "relay_timers": {
            "1": 2.0, "2": 2.0, "3": 2.0, "4": 2.0,
            "5": 2.0, "6": 2.0, "7": 2.0, "8": 2.0
        },
        "physical_button": {
            "enabled": True,
            "pin": 2,
            "pull_up": True,
            "debounce_time": 0.3,
            "target_relay": 1
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
        }
    }

    def __init__(self, config_file="config.json"):
        self.config_file = Path(config_file).resolve()
        self.config = self._load_config()

    def _load_config(self):
        """Loads configuration from the JSON file, or creates it from defaults."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    user_config = json.load(f)
                    # Deep update allows merging user settings with defaults
                    config = self._defaults.copy()
                    self._deep_update(config, user_config)
                    app.logger.info(f"Configuration loaded from {self.config_file}")
                    return config
            else:
                app.logger.warning(f"No config file found. Creating default config at {self.config_file}")
                with open(self.config_file, 'w') as f:
                    json.dump(self._defaults, f, indent=4)
                return self._defaults.copy()
        except Exception as e:
            app.logger.error(f"Error loading config: {e}, using defaults")
            return self._defaults.copy()

    def _deep_update(self, base, update):
        """Recursively updates a dictionary."""
        for key, value in update.items():
            if isinstance(base.get(key), dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    def save_config(self, new_config):
        """Saves new configuration to the file after validation."""
        try:
            # Server-side validation to ensure data from the admin panel is safe.
            if "relay_pins" in new_config:
                pins = list(new_config["relay_pins"].values())
                if len(pins) != len(set(pins)):
                    raise ValueError("Duplicate GPIO pins are not allowed.")
            
            self._deep_update(self.config, new_config)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception as e:
            app.logger.error(f"Failed to save configuration: {e}", exc_info=True)
            raise e
            
    # Properties provide easy, direct access to config values.
    @property
    def RELAY_PINS(self): return {int(k): v for k, v in self.config["relay_pins"].items()}
    @property
    def RELAY_TIMERS(self): return {int(k): float(v) for k, v in self.config["relay_timers"].items()}
    @property
    def RELAY_ACTIVE_LOW(self): return self.config["relay_settings"]["active_low"]
    @property
    def MAX_CONCURRENT_TRIGGERS(self): return self.config["relay_settings"]["max_concurrent_triggers"]
    @property
    def BUTTON_ENABLED(self): return self.config["physical_button"]["enabled"]
    @property
    def BUTTON_PIN(self): return self.config["physical_button"]["pin"]
    @property
    def BUTTON_PULL_UP(self): return self.config["physical_button"]["pull_up"]
    @property
    def BUTTON_DEBOUNCE_TIME(self): return self.config["physical_button"]["debounce_time"]
    @property
    def BUTTON_TARGET_RELAY(self): return self.config["physical_button"]["target_relay"]
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


# --- Global Variables ---
app = Flask(__name__)
config = Config(Path(__file__).parent / "config.json")
# Threading locks to prevent race conditions when multiple triggers occur.
relay_locks = {i: threading.Lock() for i in range(1, 9)}
active_triggers = 0
active_triggers_lock = threading.Lock()
# Tracks which relays were triggered by the physical button for the UI.
physical_button_triggers = {}

# --- Logging Setup ---
def setup_logging():
    """Configures rotating file logs and console logs."""
    try:
        Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
        log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        file_handler = RotatingFileHandler(
            os.path.join(config.LOG_DIR, config.LOG_FILE), 
            maxBytes=config.LOG_MAX_SIZE, 
            backupCount=config.LOG_BACKUP_COUNT
        )
        file_handler.setFormatter(formatter)
        
        # This makes the app log to both the file and the systemd journal
        app.logger.addHandler(file_handler)
        app.logger.setLevel(log_level)
        # Suppress noisy Werkzeug logs in production
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

    except Exception as e:
        print(f"Failed to setup logging: {e}")
        logging.basicConfig(level=logging.INFO)

# --- GPIO Setup & Cleanup ---
def setup_gpio():
    """Initializes GPIO pins for relays and the physical button."""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Setup relay pins to their initial 'OFF' state.
        for pin in config.RELAY_PINS.values():
            GPIO.setup(pin, GPIO.OUT)
            initial_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            GPIO.output(pin, initial_state)
        
        if config.BUTTON_ENABLED:
            pull_mode = GPIO.PUD_UP if config.BUTTON_PULL_UP else GPIO.PUD_DOWN
            GPIO.setup(config.BUTTON_PIN, GPIO.IN, pull_up_down=pull_mode)
            edge = GPIO.FALLING if config.BUTTON_PULL_UP else GPIO.RISING
            debounce_ms = int(config.BUTTON_DEBOUNCE_TIME * 1000)
            GPIO.add_event_detect(config.BUTTON_PIN, edge, callback=button_pressed_callback, bouncetime=debounce_ms)
            app.logger.info(f"Physical button enabled on GPIO {config.BUTTON_PIN}")
        
        app.logger.info("GPIO initialization successful.")
        return True
    except Exception as e:
        app.logger.error(f"GPIO initialization failed: {e}. Is this running on a Raspberry Pi?")
        return False

def cleanup_gpio():
    """Resets all GPIO pins to a safe state on application exit."""
    app.logger.info("Cleaning up GPIO...")
    GPIO.cleanup()

# --- Core Logic ---
def button_pressed_callback(channel):
    """Callback for the physical button, runs in a separate thread."""
    app.logger.info(f"Physical button pressed on GPIO {channel}")
    target_relay = config.BUTTON_TARGET_RELAY
    
    # Trigger the relay in a new thread to avoid blocking the GPIO event.
    thread = threading.Thread(target=trigger_relay, args=(target_relay, "physical_button"))
    thread.daemon = True
    thread.start()

def trigger_relay(relay_num, source="web"):
    """
    Activates a specific relay for its configured duration.
    This function is thread-safe.
    """
    global active_triggers
    if relay_num not in config.RELAY_PINS:
        return

    # Check against max concurrent triggers.
    with active_triggers_lock:
        if active_triggers >= config.MAX_CONCURRENT_TRIGGERS:
            app.logger.warning(f"Max concurrent triggers reached. Relay {relay_num} request rejected.")
            return
        active_triggers += 1
    
    # Use a non-blocking lock to ensure a relay isn't triggered twice.
    if not relay_locks[relay_num].acquire(blocking=False):
        app.logger.warning(f"Relay {relay_num} is already active.")
        with active_triggers_lock:
            active_triggers -= 1
        return

    try:
        if source == "physical_button":
            physical_button_triggers[relay_num] = True

        pin = config.RELAY_PINS[relay_num]
        duration = config.RELAY_TIMERS.get(relay_num, 2.0)
        on_state = GPIO.LOW if config.RELAY_ACTIVE_LOW else GPIO.HIGH
        off_state = not on_state

        app.logger.info(f"Relay {relay_num} (GPIO {pin}) ON for {duration}s (source: {source})")
        GPIO.output(pin, on_state)
        
        time.sleep(duration)
        
        GPIO.output(pin, off_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) OFF")
        
    finally:
        # Release the lock and decrement the active trigger count.
        relay_locks[relay_num].release()
        with active_triggers_lock:
            active_triggers -= 1
        if relay_num in physical_button_triggers:
            del physical_button_triggers[relay_num]

# --- Flask Routes ---
@app.route('/')
def index():
    """Serves the main control panel UI."""
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    """Serves the admin configuration UI."""
    return render_template('admin.html')

@app.route('/relay/<int:relay_num>', methods=['POST'])
def control_relay(relay_num):
    """API endpoint to trigger a relay from the web UI."""
    if relay_num not in config.RELAY_PINS:
        return jsonify({'status': 'error', 'message': 'Invalid relay number'}), 400
    
    if relay_locks[relay_num].locked():
        return jsonify({'status': 'error', 'message': 'Relay is already active'}), 429
    
    # Start the relay trigger in a background thread so the API can return immediately.
    thread = threading.Thread(target=trigger_relay, args=(relay_num, "web"))
    thread.daemon = True
    thread.start()
    
    duration = config.RELAY_TIMERS.get(relay_num, 2.0)
    return jsonify({'status': 'success', 'relay': relay_num, 'duration': duration})

@app.route('/status')
def get_status():
    """API endpoint for the UI to poll for the real-time state of all relays."""
    try:
        status = {'relays': {}}
        for num, lock in relay_locks.items():
            status['relays'][num] = {
                'locked': lock.locked(),
                'timer_duration': config.RELAY_TIMERS.get(num, 2.0),
                'triggered_by_button': num in physical_button_triggers
            }
        return jsonify(status)
    except Exception as e:
        app.logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
        
@app.route('/admin/config', methods=['GET'])
def get_config():
    """API endpoint to provide the current configuration to the admin panel."""
    # Only return editable fields.
    editable_config = {
        "relay_pins": config.config["relay_pins"],
        "relay_settings": config.config["relay_settings"],
        "relay_timers": config.config["relay_timers"],
        "physical_button": config.config["physical_button"]
    }
    return jsonify(editable_config)

@app.route('/admin/config', methods=['POST'])
def set_config():
    """API endpoint to receive new configuration and restart the service."""
    new_config = request.get_json()
    try:
        config.save_config(new_config)
        app.logger.info("Configuration saved. Triggering service restart.")
        
        # This function runs the systemctl command in a separate thread.
        def restart_service():
            time.sleep(1) # Give the API response time to be sent.
            try:
                # Use subprocess to restart the service itself.
                subprocess.run(["sudo", "systemctl", "restart", "relay-control.service"], check=True)
            except Exception as e:
                app.logger.error(f"Failed to restart service: {e}")

        threading.Thread(target=restart_service).start()
        
        return jsonify({'status': 'success', 'message': 'Configuration saved. Restarting service.'})
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Failed to save configuration: {str(e)}'}), 500

# --- App Initialization ---
# This block runs only when the application starts.
setup_logging()
if not setup_gpio():
    app.logger.critical("Could not initialize GPIO. The application cannot function.")
    # In a real scenario, you might want to exit, but for web debugging,
    # we'll let it run so the admin panel is accessible.
    
atexit.register(cleanup_gpio) # Ensure GPIO is cleaned up on exit.

# The 'if __name__ == '__main__':' block is NOT used when running with Gunicorn.
# It's only for direct execution (e.g., 'python3 app.py') for local testing.
if __name__ == '__main__':
    app.logger.info("Starting Flask development server. This is NOT for production.")
    app.run(host='0.0.0.0', port=5000, debug=True)
