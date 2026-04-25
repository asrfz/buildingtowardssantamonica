"""
Test Arduino serial connection by printing raw JSON lines.

Usage:
    python scripts/test_serial.py
    python scripts/test_serial.py COM4        # override port
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

port = sys.argv[1] if len(sys.argv) > 1 else settings.ARDUINO_SERIAL_PORT
baud = settings.ARDUINO_BAUD_RATE

print(f"Listening on {port} at {baud} baud. Ctrl+C to stop.\n")

try:
    import serial
    with serial.Serial(port, baud, timeout=3) as ser:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print(f"[raw] {line}")
except ImportError:
    print("pyserial not installed — run: pip install pyserial")
except KeyboardInterrupt:
    print("\nStopped.")
except Exception as e:
    print(f"Error: {e}")
