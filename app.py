#!/usr/bin/env python3
"""
Production-ready Flask application for controlling an 8-relay module on Raspberry Pi
Each relay can be triggered for a configurable duration via web interface
Now includes physical button support for hardware control
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
        "relay_names": {
            "1": "Relay 1", "2": "Relay 2", "3": "Relay 3", "4": "Relay 4",
            "5": "Relay 5", "6": "Relay 6", "7": "Relay 7", "8": "Relay 8"
        },
        "relay_settings": {
            "active_low": True,
            "trigger_durations": {
                "1": 0.5, "2": 0.5, "3": 0.5, "4": 0.5,
                "5": 0.5, "6": 0.5, "7": 0.5, "8": 0.5
            },
            "max_concurrent_triggers": 3
        },
        "button_settings": {
            "enabled": True,
            "button_pin": 26,
            "relay_number": 1,
            "pull_up": True,
            "debounce_time": 0.3
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
        """Load configuration from file or use defaults"""
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self):
        """Load configuration from JSON file"""
        try:
            config_path = Path(self.config_file)
            if config_path.exists():
                with open(self.config_file, 'r') as f:
                    user_config = json.load(f)
                config = self._defaults.copy()
                self._deep_update(config, user_config)
                print(f"Configuration loaded from {self.config_file}")
                return config
            else:
                print(f"No config file found, using defaults")
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

    def save_config(self):
        """Save current configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def update_config(self, section, updates):
        """Update a configuration section"""
        if section in self.config:
            if isinstance(self.config[section], dict):
                self._deep_update(self.config[section], updates)
            else:
                self.config[section].update(updates)
            return self.save_config()
        return False

    @property
    def RELAY_PINS(self):
        return {int(k): v for k, v in self.config["relay_pins"].items()}

    @property
    def RELAY_NAMES(self):
        return {int(k): v for k, v in self.config.get("relay_names", {}).items()}

    @property
    def RELAY_ACTIVE_LOW(self):
        return self.config["relay_settings"]["active_low"]

    @property
    def RELAY_TRIGGER_DURATIONS(self):
        return {int(k): float(v) for k, v in self.config["relay_settings"]["trigger_durations"].items()}

    @property
    def MAX_CONCURRENT_TRIGGERS(self):
        return self.config["relay_settings"]["max_concurrent_triggers"]

    @property
    def BUTTON_ENABLED(self):
        return self.config.get("button_settings", {}).get("enabled", False)

    @property
    def BUTTON_PIN(self):
        return self.config.get("button_settings", {}).get("button_pin", 26)

    @property
    def BUTTON_RELAY(self):
        return self.config.get("button_settings", {}).get("relay_number", 1)

    @property
    def BUTTON_PULL_UP(self):
        return self.config.get("button_settings", {}).get("pull_up", True)

    @property
    def BUTTON_DEBOUNCE(self):
        # Always cast to float
        return float(self.config.get("button_settings", {}).get("debounce_time", 0.3))

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


# Button Handler Class using polling instead of interrupts
class ButtonHandler:
    """Handle physical button input for relay control using polling"""

    def __init__(self, button_pin, relay_trigger_function, relay_number=1,
                 debounce_time=0.3, pull_up=True):
        self.button_pin = button_pin
        self.trigger_relay = relay_trigger_function
        self.relay_number = relay_number
        self.debounce_time = float(debounce_time)
        self.pull_up = pull_up
        self.last_press_time = 0
        self.last_state = None
        self.polling_thread = None
        self.stop_polling = threading.Event()

    def setup(self):
        """Setup GPIO for button input using polling method"""
        try:
            # Setup the pin
            if self.pull_up:
                GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            else:
                GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            
            # Get initial state
            self.last_state = GPIO.input(self.button_pin)
            
            # Start polling thread
            self.stop_polling.clear()
            self.polling_thread = threading.Thread(target=self._poll_button, daemon=True)
            self.polling_thread.start()
            
            app.logger.info(f"Button polling started on GPIO {self.button_pin} (polling mode)")
            
        except Exception as e:
            app.logger.error(f"Button setup failed: {e}")
            raise

    def _poll_button(self):
        """Poll the button state continuously"""
        while not self.stop_polling.is_set():
            try:
                current_state = GPIO.input(self.button_pin)
                
                # Detect button press (transition from HIGH to LOW for pull-up)
                if self.pull_up:
                    button_pressed = (self.last_state == 1 and current_state == 0)
                else:
                    button_pressed = (self.last_state == 0 and current_state == 1)
                
                if button_pressed:
                    current_time = time.time()
                    if current_time - self.last_press_time >= self.debounce_time:
                        self.last_press_time = current_time
                        app.logger.info(f"Physical button pressed for Relay {self.relay_number}")
                        
                        # Trigger relay in a separate thread
                        t = threading.Thread(
                            target=self.trigger_relay,
                            args=(self.relay_number,),
                            name=f"button-relay-{self.relay_number}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        )
                        t.daemon = True
                        t.start()
                
                self.last_state = current_state
                
            except Exception as e:
                app.logger.error(f"Error in button polling: {e}")
            
            # Small delay to prevent excessive CPU usage
            time.sleep(0.01)  # 10ms polling rate

    def cleanup(self):
        """Stop polling thread"""
        self.stop_polling.set()
        if self.polling_thread and self.polling_thread.is_alive():
            self.polling_thread.join(timeout=1)
        app.logger.info("Button polling stopped")


# Global variables
app = Flask(__name__)
config = Config()
relay_locks = {}
active_triggers = 0
active_triggers_lock = threading.Lock()
cleanup_done = False
button_handler = None

# Statistics tracking
stats = {
    'start_time': datetime.now(),
    'total_triggers': 0,
    'relay_triggers': {i: 0 for i in range(1, 9)},
    'last_trigger_time': None,
    'errors': 0
}


def setup_logging():
    """Configure logging with rotation"""
    try:
        Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)
        level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh = RotatingFileHandler(
            os.path.join(config.LOG_DIR, config.LOG_FILE),
            maxBytes=config.LOG_MAX_SIZE,
            backupCount=config.LOG_BACKUP_COUNT
        )
        fh.setFormatter(fmt)
        fh.setLevel(level)

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(level)

        app.logger.setLevel(level)
        app.logger.addHandler(fh)
        app.logger.addHandler(ch)

        werk = logging.getLogger('werkzeug')
        werk.setLevel(logging.WARNING)
        werk.addHandler(fh)
        werk.addHandler(ch)

    except Exception as e:
        print(f"Failed to setup logging: {e}")
        logging.basicConfig(level=logging.INFO)


def setup_gpio():
    """Initialize GPIO pins for relay control"""
    global button_handler
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Setup relays
        for relay_num, pin in config.RELAY_PINS.items():
            GPIO.setup(pin, GPIO.OUT)
            # OFF state
            off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
            GPIO.output(pin, off_state)
            relay_locks[relay_num] = threading.Lock()

        # Setup physical button
        if config.BUTTON_ENABLED:
            try:
                button_handler = ButtonHandler(
                    button_pin=config.BUTTON_PIN,
                    relay_trigger_function=trigger_relay,
                    relay_number=config.BUTTON_RELAY,
                    debounce_time=config.BUTTON_DEBOUNCE,
                    pull_up=config.BUTTON_PULL_UP
                )
                button_handler.setup()
                app.logger.info(
                    f"Physical button initialized on GPIO {config.BUTTON_PIN} for Relay {config.BUTTON_RELAY}"
                )
            except Exception:
                app.logger.error("Failed to setup physical button", exc_info=True)

        app.logger.info("GPIO initialization successful")
        return True

    except Exception as e:
        app.logger.error(f"GPIO initialization failed: {e}")
        return False


def trigger_relay(relay_num):
    """Trigger a relay for its configured duration"""
    global active_triggers, stats

    if relay_num not in config.RELAY_PINS:
        app.logger.error(f"Invalid relay number: {relay_num}")
        stats['errors'] += 1
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
        duration = config.RELAY_TRIGGER_DURATIONS.get(relay_num, 0.5)

        # Turn ON
        on_state = GPIO.LOW if config.RELAY_ACTIVE_LOW else GPIO.HIGH
        GPIO.output(pin, on_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned ON for {duration}s")

        stats['total_triggers'] += 1
        stats['relay_triggers'][relay_num] += 1
        stats['last_trigger_time'] = datetime.now()

        time.sleep(duration)

        # Turn OFF
        off_state = GPIO.HIGH if config.RELAY_ACTIVE_LOW else GPIO.LOW
        GPIO.output(pin, off_state)
        app.logger.info(f"Relay {relay_num} (GPIO {pin}) turned OFF")

        return True

    except Exception as e:
        app.logger.error(f"Error triggering relay {relay_num}: {e}")
        stats['errors'] += 1
        return False

    finally:
        relay_locks[relay_num].release()
        with active_triggers_lock:
            active_triggers -= 1


@app.route('/')
def index():
    """Serve the main control panel"""
    relay_info = {}
    for relay_num in config.RELAY_PINS.keys():
        relay_info[relay_num] = {
            'name': config.RELAY_NAMES.get(relay_num, f'Relay {relay_num}'),
            'pin': config.RELAY_PINS[relay_num]
        }
    return render_template('index.html', relay_info=relay_info, relay_count=len(config.RELAY_PINS))


@app.route('/relay/<int:relay_num>', methods=['POST'])
def control_relay(relay_num):
    """Handle relay control requests"""
    if relay_num < 1 or relay_num > len(config.RELAY_PINS):
        app.logger.warning(f"Invalid relay number requested: {relay_num}")
        return jsonify({'status': 'error', 'message': 'Invalid relay number'}), 400

    client_ip = request.remote_addr
    app.logger.info(f"Relay {relay_num} trigger requested from {client_ip}")

    if relay_locks[relay_num].locked():
        return jsonify({'status': 'error', 'message': 'Relay is already active'}), 429

    t = threading.Thread(
        target=trigger_relay,
        args=(relay_num,),
        name=f"relay-{relay_num}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    )
    t.daemon = True
    t.start()

    duration = config.RELAY_TRIGGER_DURATIONS.get(relay_num, 0.5)
    return jsonify({'status': 'success', 'relay': relay_num, 'duration': duration})


@app.route('/status')
def get_status():
    """Get current status of all relays"""
    try:
        status = {
            'relays': {},
            'system': {
                'active_triggers': active_triggers,
                'max_concurrent': config.MAX_CONCURRENT_TRIGGERS,
                'timestamp': datetime.now().isoformat(),
                'button_enabled': config.BUTTON_ENABLED,
                'button_pin': config.BUTTON_PIN if config.BUTTON_ENABLED else None,
                'button_relay': config.BUTTON_RELAY if config.BUTTON_ENABLED else None
            }
        }
        for relay_num, pin in config.RELAY_PINS.items():
            curr = GPIO.input(pin)
            is_on = (curr == GPIO.LOW) if config.RELAY_ACTIVE_LOW else (curr == GPIO.HIGH)
            status['relays'][relay_num] = {
                'name': config.RELAY_NAMES.get(relay_num, f'Relay {relay_num}'),
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
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat(), 'uptime': time.process_time()})


@app.route('/admin')
def admin_dashboard():
    """Admin dashboard"""
    uptime = datetime.now() - stats['start_time']
    uptime_str = str(uptime).split('.')[0]
    log_file = os.path.join(config.LOG_DIR, config.LOG_FILE)
    recent_logs = []
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                recent_logs = f.readlines()[-50:]
    except Exception as e:
        app.logger.error(f"Error reading logs: {e}")
    return render_template('admin.html', config=config.config, stats=stats, uptime=uptime_str, recent_logs=recent_logs)


@app.route('/admin/stats')
def admin_stats():
    """Get system statistics"""
    uptime = datetime.now() - stats['start_time']
    return jsonify({
        'uptime': str(uptime).split('.')[0],
        'total_triggers': stats['total_triggers'],
        'relay_triggers': stats['relay_triggers'],
        'last_trigger': stats['last_trigger_time'].isoformat() if stats['last_trigger_time'] else None,
        'errors': stats['errors'],
        'active_triggers': active_triggers
    })


@app.route('/admin/logs')
def admin_logs():
    """Get recent log entries"""
    log_file = os.path.join(config.LOG_DIR, config.LOG_FILE)
    logs = []
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                for line in f.readlines()[-100:]:
                    logs.append(line.strip())
    except Exception as e:
        app.logger.error(f"Error reading logs: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify({'logs': logs})


@app.route('/admin/config', methods=['GET', 'POST'])
def admin_config():
    """Update configuration"""
    if request.method == 'POST':
        try:
            data = request.json or {}
            section = data.get('section')
            settings = data.get('settings')
            if section and settings and config.update_config(section, settings):
                app.logger.info(f"Configuration updated: {section}")
                return jsonify({'status': 'success', 'message': 'Configuration updated. Restart service to apply changes.'})
            return jsonify({'status': 'error', 'message': 'Invalid request'}), 400
        except Exception as e:
            app.logger.error(f"Error updating config: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    return jsonify(config.config)


@app.route('/admin/test/<int:relay_num>', methods=['POST'])
def admin_test_relay(relay_num):
    """Test a specific relay from admin panel"""
    return control_relay(relay_num)


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'status': 'error', 'message': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal error: {error}")
    return jsonify({'status': 'error', 'message': 'Internal server error'}), 500


def cleanup_gpio():
    """Clean up GPIO resources"""
    global cleanup_done, button_handler
    if not cleanup_done:
        cleanup_done = True
        try:
            if button_handler:
                button_handler.cleanup()
                app.logger.info("Button handler cleanup completed")
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
        app.run(
            host=config.HOST,
            port=config.PORT,
            debug=config.DEBUG,
            use_reloader=False
        )
    except Exception as e:
        app.logger.error(f"Application error: {e}")
        cleanup_gpio()
        sys.exit(1)


if __name__ == '__main__':
    main()
