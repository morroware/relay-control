#!/usr/bin/env python3
"""Test GPIO pins for relay module"""
import RPi.GPIO as GPIO
import time

RELAY_PINS = [17, 18, 27, 22, 23, 24, 25, 4]

print("GPIO Pin Test for Relay Module")
print("==============================")
print("This will turn each relay ON for 1 second")
print("Press Ctrl+C to stop")

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Setup pins
    for pin in RELAY_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)  # Start with relays OFF (active-low)

    # Test each relay
    for i, pin in enumerate(RELAY_PINS):
        print(f"\nTesting Relay {i+1} (GPIO {pin})...")
        GPIO.output(pin, GPIO.LOW)   # Turn ON
        time.sleep(1)
        GPIO.output(pin, GPIO.HIGH)  # Turn OFF
        print(f"Relay {i+1} test complete")

    print("\nAll relays tested successfully!")

except KeyboardInterrupt:
    print("\nTest interrupted")
except Exception as e:
    print(f"Error: {e}")
finally:
    GPIO.cleanup()
    print("GPIO cleaned up")
