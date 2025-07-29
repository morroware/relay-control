#!/usr/bin/env python3
"""
Production-ready Flask application for controlling an 8-relay module on Raspberry Pi
Each relay can be triggered for 2 seconds via web interface
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, jsonify, request
import RPi.GPIO as GPIO
import time
import threading
import signal
import atexit
from datetime import datetime
import json
from pathlib import Path

# Configuration
class Config:
    """Configuration management with JSON file support"""

    # Default configuration
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
        """Load configuration from file or use defaults"""
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self):
        """Load configuration from JSON file"""
        try:
            config_path = Path(self.config_file)
            if config_path.exists():
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                    # Merge with defaults
                    config = self._defaults.copy()
                    self._deep_update(config, user_config)
                    print(f"Configuration loaded from {self.config_file}")
                    return config
            else:
                print(f"No config file found, using defaults")
                # Create default config file
                with open(self.config_file, 'w') as f:
                    json.dump(self._defaults, f, indent=4)
                return self._defaults.copy()
        except Exception as e:
            print(f"Error loading config: {e}, using defaults")
            return self._defaults.copy()

    def _deep_update(self, base, update):
        """Recursively update nested dictionaries"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value

    @property
    def RELAY_PINS(self):
        return {int(k): v for k, v in self.config["relay_pins"].items()}

    @property
    def RELAY_ACTIVE_LOW(self):
        return self.config["relay_settings"]["active_low"]

    @property
    def RELAY_TRIGGER_DURATION(self):
        return self.config["relay_settings"]["trigger_duration"]

    @property
    def MAX_CONCURRENT_TRIGGERS(self):
        return self.config["relay_settings"]["max_concurrent_triggers"]

    @property
    def HOST(self):
        return self.config["server"]["host"]

    @property
    def PORT(self):
        return self.config["server"]["port"]

    @property
    def DEBUG(self):
        return self.config["server"]["debug"]

    @property
    def LOG_DIR(self):
        return self.config["logging"]["log_dir"]

    @property
    def LOG_FILE(self):
        return self.config["logging"]["log_file"]

    @property
    def LOG_MAX_SIZE(self):
        return self.config["logging"]["max_size_mb"] * 1024 * 1024

    @property
    def LOG_BACKUP_COUNT(self):
        return self.config["logging"]["backup_count"]

    @property
    def LOG_LEVEL(self):
        return self.config["logging"]["log_level"]

    @property
    def ENABLE_AUTH(self):
        return self.config["security"]["enable_auth"]

    @property
    def API_KEY(self):
        return self.config["security"]["api_key"]

    @property
    def ALLOWED_IPS(self):
        return self.config["security"]["allowed_ips"]

# Global variables
app = Flask(__name__)
config = Config()  # Load configuration
relay_locks = {}
active_triggers = 0
active_triggers_lock = threading.Lock()
cleanup_done = False

# Setup logging
def setup_logging():
    """Configure logging with rotation"""
    try:
        # Create log directory if it doesn't exist
        Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)

        # Set log level
        log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

        # Configure formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # File handler with rotation
        file_handler = RotatingFileHandler(
            os.path.join(config.LOG_DIR, config.LOG_FILE),
            maxBytes=config.LOG_MAX_SIZE,
            backupCount=config.LOG_BACKUP_COUNT
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(log_level)

        # Configure app logger
        app.logger.setLevel(log_level)
        app.logger.addHandler(file_handler)
        app.logger.addHandler(console_handler)

        # Configure werkzeug logger
        werkzeug_logger = logging.getLogger('werkzeug')
        werkzeug_logger.setLevel(logging.WARNING)
        werkzeug_logger.addHandler(file_handler)
        werkzeug_logger.addHandler(console_handler)

    except Exception as e:
        print(f"Failed to setup logging: {e}")
        # Continue without file logging
        logging.basicConfig(level=logging.INFO)

# Initialize GPIO
def setup_gpio():
    """Initialize GPIO pins for relay control"""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Setup all relay pins as outputs
        for relay_num, pin in config.RELAY_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            # Set initial state (OFF)
            initial_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            GPIO.output(pin, initial_state)
            # Create a lock for each relay
            relay_locks[relay_num] = threading.Lock()

        app.logger.info("GPIO initialization successful")
        return True

    except Exception as e:
        app.logger.error(f"GPIO initialization failed: {e}")
        return False

# Relay control function
def trigger_relay(relay_num):
    """Trigger a relay for the configured duration"""
    global active_triggers

    if relay_num not in config.RELAY_PINS:
        app.logger.error(f"Invalid relay number: {relay_num}")
        return False

    # Check if we've hit the concurrent trigger limit
    with active_triggers_lock:
        if active_triggers >= config.MAX_CONCURRENT_TRIGGERS:
            app.logger.warning(f"Max concurrent triggers reached, rejecting relay {relay_num}")
            return False
        active_triggers += 1

    try:
        # Acquire lock for this specific relay
        if not relay_locks[relay_num].acquire(blocking=False):
            app.logger.warning(f"Relay {relay_num} is already active")
            with active_triggers_lock:
                active_triggers -= 1
            return False

        pin = config.RELAY_PINS[relay_num]

        # Turn relay ON
        on_state = GPIO.LOW if config.RELAY_ACTIVE_LOW else GPIO.HIGH
        GPIO.output(pin, on_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned ON")

        # Wait for configured duration
        time.sleep(config.RELAY_TRIGGER_DURATION)

        # Turn relay OFF
        off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
        GPIO.output(pin, off_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned OFF")

        return True

    except Exception as e:
        app.logger.error(f"Error triggering relay {relay_num}: {e}")
        return False

    finally:
        # Always release the lock and decrement counter
        relay_locks[relay_num].release()
        with active_triggers_lock:
            active_triggers -= 1

# Routes
@app.before_request
def check_auth():
    """Check authentication if enabled"""
    if config.ENABLE_AUTH and request.endpoint != 'health_check':
        # Check API key
        if config.API_KEY:
            provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
            if provided_key != config.API_KEY:
                return jsonify({'status': 'error', 'message': 'Invalid API key'}), 401

        # Check IP whitelist
        if config.ALLOWED_IPS:
            client_ip = request.remote_addr
            if client_ip not in config.ALLOWED_IPS:
                app.logger.warning(f"Unauthorized access attempt from {client_ip}")
                return jsonify({'status': 'error', 'message': 'Unauthorized IP'}), 403

@app.route('/')
def index():
    """Serve the main control panel"""
    return render_template('index.html',
                         relay_count=len(config.RELAY_PINS),
                         trigger_duration=config.RELAY_TRIGGER_DURATION)

@app.route('/relay/<int:relay_num>', methods=['POST'])
def control_relay(relay_num):
    """Handle relay control requests"""
    if relay_num < 1 or relay_num > len(config.RELAY_PINS):
        app.logger.warning(f"Invalid relay number requested: {relay_num}")
        return jsonify({
            'status': 'error',
            'message': 'Invalid relay number'
        }), 400

    # Get client IP for logging
    client_ip = request.remote_addr
    app.logger.info(f"Relay {relay_num} trigger requested from {client_ip}")

    # Check if relay is already active
    if relay_locks[relay_num].locked():
        return jsonify({
            'status': 'error',
            'message': 'Relay is already active'
        }), 429

    # Trigger relay in separate thread
    thread = threading.Thread(
        target=trigger_relay,
        args=(relay_num,),
        name=f"relay-{relay_num}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        'status': 'success',
        'relay': relay_num,
        'duration': config.RELAY_TRIGGER_DURATION
    })

@app.route('/status')
def get_status():
    """Get current status of all relays"""
    try:
        status = {
            'relays': {},
            'system': {
                'active_triggers': active_triggers,
                'max_concurrent': config.MAX_CONCURRENT_TRIGGERS,
                'timestamp': datetime.now().isoformat()
            }
        }

        for relay_num, pin in config.RELAY_PINS.items():
            current_state = GPIO.input(pin)
            is_on = (current_state == GPIO.LOW) if config.RELAY_ACTIVE_LOW else (current_state == GPIO.HIGH)
            status['relays'][relay_num] = {
                'state': 'ON' if is_on else 'OFF',
                'locked': relay_locks[relay_num].locked(),
                'gpio_pin': pin
            }

        return jsonify(status)

    except Exception as e:
        app.logger.error(f"Error getting status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'uptime': time.process_time()
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'status': 'error', 'message': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal error: {error}")
    return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

# Cleanup functions
def cleanup_gpio():
    """Clean up GPIO resources"""
    global cleanup_done
    if not cleanup_done:
        cleanup_done = True
        try:
            # Turn off all relays
            off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            for pin in config.RELAY_PINS.values():
                GPIO.output(pin, off_state)

            GPIO.cleanup()
            app.logger.info("GPIO cleanup completed")
        except Exception as e:
            app.logger.error(f"Error during GPIO cleanup: {e}")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    app.logger.info(f"Received signal {signum}, shutting down...")
    cleanup_gpio()
    sys.exit(0)

# Register cleanup handlers
atexit.register(cleanup_gpio)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Main entry point
def main():
    """Main application entry point"""
    setup_logging()
    app.logger.info("Starting Relay Control Application")

    if not setup_gpio():
        app.logger.error("Failed to initialize GPIO, exiting")
        sys.exit(1)

    try:
        app.run(
            host=config.HOST,
            port=config.PORT,
            debug=config.DEBUG,
            use_reloader=False  # Disable reloader to prevent GPIO issues
        )
    except Exception as e:
        app.logger.error(f"Application error: {e}")
        cleanup_gpio()
        sys.exit(1)

if __name__ == '__main__':
    main()
