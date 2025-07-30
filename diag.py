#!/usr/bin/env python3
"""Diagnostic script to test button functionality"""
import RPi.GPIO as GPIO
import json
import time

print("Button Diagnostic Script")
print("========================\n")

# Load config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
    print("✓ Config loaded successfully")
    
    button_settings = config.get('button_settings', {})
    print(f"  - Button enabled: {button_settings.get('enabled', False)}")
    print(f"  - Button pin: {button_settings.get('button_pin', 26)}")
    print(f"  - Relay number: {button_settings.get('relay_number', 1)}")
    print(f"  - Pull-up: {button_settings.get('pull_up', True)}")
    print(f"  - Debounce: {button_settings.get('debounce_time', 0.3)}s")
except Exception as e:
    print(f"✗ Failed to load config: {e}")
    exit(1)

if not button_settings.get('enabled', False):
    print("\n⚠️  Button is DISABLED in config!")
    print("Enable it in the admin panel or edit config.json")
    exit(1)

# Test GPIO
BUTTON_PIN = button_settings.get('button_pin', 26)
PULL_UP = button_settings.get('pull_up', True)

print(f"\nTesting GPIO {BUTTON_PIN}...")

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    if PULL_UP:
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        print(f"✓ GPIO {BUTTON_PIN} configured with pull-up resistor")
    else:
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        print(f"✓ GPIO {BUTTON_PIN} configured with pull-down resistor")
    
    # Test reading the pin
    state = GPIO.input(BUTTON_PIN)
    print(f"✓ Current pin state: {state} ({'HIGH' if state else 'LOW'})")
    
    if PULL_UP:
        print("\nExpected behavior:")
        print("- Pin should read HIGH (1) when button is NOT pressed")
        print("- Pin should read LOW (0) when button IS pressed")
    else:
        print("\nExpected behavior:")
        print("- Pin should read LOW (0) when button is NOT pressed")
        print("- Pin should read HIGH (1) when button IS pressed")
    
    print("\nPress the button now to test (Ctrl+C to exit)...")
    print("Waiting for button press...\n")
    
    last_state = state
    press_count = 0
    
    # Test with event detection like the real app
    def button_callback(channel):
        nonlocal press_count
        press_count += 1
        state = GPIO.input(channel)
        print(f"EVENT DETECTED! Press #{press_count}, Pin state: {state}")
    
    edge = GPIO.FALLING if PULL_UP else GPIO.RISING
    GPIO.add_event_detect(BUTTON_PIN, edge, callback=button_callback, bouncetime=300)
    
    # Also poll to show continuous state
    while True:
        current_state = GPIO.input(BUTTON_PIN)
        if current_state != last_state:
            print(f"State changed: {last_state} -> {current_state}")
            last_state = current_state
        time.sleep(0.05)
        
except KeyboardInterrupt:
    print(f"\n\nTest stopped. Total button presses detected: {press_count}")
except Exception as e:
    print(f"\n✗ GPIO Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    GPIO.cleanup()
    print("GPIO cleaned up")
