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

# --- Configuration Class (updated with individual relay timers) ---
class Config:
    """Configuration management with JSON file support"""
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
                    
                    # Migration: Convert old trigger_duration to individual timers
                    if "trigger_duration" in config.get("relay_settings", {}):
                        old_duration = config["relay_settings"]["trigger_duration"]
                        if "relay_timers" not in config:
                            config["relay_timers"] = {}
                        for i in range(1, 9):
                            if str(i) not in config["relay_timers"]:
                                config["relay_timers"][str(i)] = old_duration
                        # Remove old setting
                        del config["relay_settings"]["trigger_duration"]
                        print(f"Migrated old trigger_duration ({old_duration}s) to individual relay timers")
                    
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
            self._deep_update(self.config, new_config)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception as e:
            app.logger.error(f"Failed to save configuration to {self.config_file}: {e}", exc_info=True)
            return False
            
    # --- Properties ---
    @property
    def RELAY_PINS(self): return {int(k): v for k, v in self.config["relay_pins"].items()}
    @property
    def RELAY_ACTIVE_LOW(self): return self.config["relay_settings"]["active_low"]
    @property
    def MAX_CONCURRENT_TRIGGERS(self): return self.config["relay_settings"]["max_concurrent_triggers"]
    
    # Individual relay timer properties
    @property
    def RELAY_TIMERS(self): return {int(k): float(v) for k, v in self.config["relay_timers"].items()}
    
    def get_relay_timer(self, relay_num):
        """Get timer duration for specific relay"""
        return self.RELAY_TIMERS.get(relay_num, 2.0)
    
    # Physical button properties
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


# --- Global variables ---
app = Flask(__name__)
config_path = Path(__file__).parent / "config.json"
config = Config(config_path)
relay_locks = {}
active_triggers = 0
active_triggers_lock = threading.Lock()
cleanup_done = False
button_last_pressed = 0

# --- Logging Setup (unchanged) ---
def setup_logging():
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

# --- GPIO Setup (unchanged) ---
def setup_gpio():
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Setup relay pins
        for relay_num, pin in config.RELAY_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            initial_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            GPIO.output(pin, initial_state)
            relay_locks[relay_num] = threading.Lock()
        
        # Setup physical button if enabled
        if config.BUTTON_ENABLED:
            try:
                pull_mode = GPIO.PUD_UP if config.BUTTON_PULL_UP else GPIO.PUD_DOWN
                GPIO.setup(config.BUTTON_PIN, GPIO.IN, pull_up_down=pull_mode)
                edge = GPIO.FALLING if config.BUTTON_PULL_UP else GPIO.RISING
                GPIO.add_event_detect(config.BUTTON_PIN, edge, callback=button_pressed_callback, bouncetime=int(config.BUTTON_DEBOUNCE_TIME * 1000))
                app.logger.info(f"Physical button setup on GPIO {config.BUTTON_PIN} (pull-up: {config.BUTTON_PULL_UP})")
            except Exception as e:
                app.logger.error(f"Failed to setup physical button: {e}")
        
        app.logger.info("GPIO initialization successful")
        return True
    except Exception as e:
        app.logger.error(f"GPIO initialization failed: {e}")
        return False

# --- Physical Button Handler ---
def button_pressed_callback(channel):
    """Callback function for physical button press"""
    global button_last_pressed
    current_time = time.time()
    
    if current_time - button_last_pressed < config.BUTTON_DEBOUNCE_TIME:
        return
    
    button_last_pressed = current_time
    app.logger.info(f"Physical button pressed on GPIO {channel}")
    
    target_relay = config.BUTTON_TARGET_RELAY
    if 1 <= target_relay <= len(config.RELAY_PINS):
        thread = threading.Thread(target=trigger_relay, args=(target_relay, "physical_button"))
        thread.daemon = True
        thread.start()
    else:
        app.logger.error(f"Invalid target relay {target_relay} for physical button")

# --- Relay Control (updated with individual timers) ---
def trigger_relay(relay_num, source="web"):
    """Trigger a relay with individual timer duration"""
    global active_triggers
    if relay_num not in config.RELAY_PINS:
        app.logger.error(f"Invalid relay number: {relay_num}")
        return False
    
    # Get individual timer for this relay
    timer_duration = config.get_relay_timer(relay_num)
    
    with active_triggers_lock:
        if active_triggers >= config.MAX_CONCURRENT_TRIGGERS:
            app.logger.warning(f"Max concurrent triggers reached, rejecting relay {relay_num} from {source}")
            return False
        active_triggers += 1
    
    try:
        if not relay_locks[relay_num].acquire(blocking=False):
            app.logger.warning(f"Relay {relay_num} is already active (requested from {source})")
            with active_triggers_lock:
                active_triggers -= 1
            return False
        
        pin = config.RELAY_PINS[relay_num]
        on_state = GPIO.LOW if config.RELAY_ACTIVE_LOW else GPIO.HIGH
        GPIO.output(pin, on_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned ON by {source} for {timer_duration}s")
        
        time.sleep(timer_duration)
        
        off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
        GPIO.output(pin, off_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned OFF")
        return True
    except Exception as e:
        app.logger.error(f"Error triggering relay {relay_num} from {source}: {e}")
        return False
    finally:
        relay_locks[relay_num].release()
        with active_triggers_lock:
            active_triggers -= 1

# --- Security Check (unchanged) ---
@app.before_request
def check_auth():
    if request.endpoint == 'health_check':
        return

    if config.ENABLE_AUTH:
        if request.path.startswith('/admin'):
            provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            if not config.API_KEY or provided_key != config.API_KEY:
                return jsonify({'status': 'error', 'message': 'Authentication required for admin panel'}), 401
        
        if config.ALLOWED_IPS:
            client_ip = request.remote_addr
            if client_ip not in config.ALLOWED_IPS:
                app.logger.warning(f"Unauthorized access attempt from {client_ip}")
                return jsonify({'status': 'error', 'message': 'Unauthorized IP'}), 403

# --- Main Routes (updated with individual timer info) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/relay/<int:relay_num>', methods=['POST'])
def control_relay(relay_num):
    if relay_num < 1 or relay_num > len(config.RELAY_PINS):
        return jsonify({'status': 'error', 'message': 'Invalid relay number'}), 400
    
    client_ip = request.remote_addr
    timer_duration = config.get_relay_timer(relay_num)
    app.logger.info(f"Relay {relay_num} trigger requested from {client_ip} (duration: {timer_duration}s)")
    
    if relay_locks[relay_num].locked():
        return jsonify({'status': 'error', 'message': 'Relay is already active'}), 429
    
    thread = threading.Thread(target=trigger_relay, args=(relay_num, f"web_{client_ip}"))
    thread.daemon = True
    thread.start()
    return jsonify({'status': 'success', 'relay': relay_num, 'duration': timer_duration})

@app.route('/relay/timers', methods=['GET'])
def get_relay_timers():
    """Get all relay timer durations"""
    return jsonify({'relay_timers': config.RELAY_TIMERS})

@app.route('/status')
def get_status():
    try:
        status = {
            'relays': {},
            'system': {
                'active_triggers': active_triggers,
                'max_concurrent': config.MAX_CONCURRENT_TRIGGERS,
                'timestamp': datetime.now().isoformat()
            },
            'physical_button': {
                'enabled': config.BUTTON_ENABLED,
                'pin': config.BUTTON_PIN if config.BUTTON_ENABLED else None,
                'target_relay': config.BUTTON_TARGET_RELAY if config.BUTTON_ENABLED else None
            },
            'relay_timers': config.RELAY_TIMERS
        }
        
        for relay_num, pin in config.RELAY_PINS.items():
            current_state = GPIO.input(pin)
            is_on = (current_state == GPIO.LOW) if config.RELAY_ACTIVE_LOW else (current_state == GPIO.HIGH)
            status['relays'][relay_num] = {
                'state': 'ON' if is_on else 'OFF',
                'locked': relay_locks[relay_num].locked(),
                'gpio_pin': pin,
                'timer_duration': config.get_relay_timer(relay_num)
            }
        return jsonify(status)
    except Exception as e:
        app.logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

# --- Admin Panel Routes (updated for individual timers) ---
@app.route('/admin.html')
def admin_html_redirect():
    return redirect(url_for('admin_panel'))

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/admin/config', methods=['GET'])
def get_config():
    """Returns the current configuration as JSON."""
    editable_config = {
        "relay_pins": config.config["relay_pins"],
        "relay_settings": config.config["relay_settings"],
        "relay_timers": config.config["relay_timers"],
        "physical_button": config.config["physical_button"]
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
        
        def restart_service():
            time.sleep(1)
            try:
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
    global cleanup_done
    if not cleanup_done:
        cleanup_done = True
        try:
            off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            for pin in config.RELAY_PINS.values():
                GPIO.output(pin, off_state)
            
            if config.BUTTON_ENABLED:
                try:
                    GPIO.remove_event_detect(config.BUTTON_PIN)
                    app.logger.info("Physical button event detection removed")
                except Exception as e:
                    app.logger.error(f"Error removing button event detection: {e}")
            
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
