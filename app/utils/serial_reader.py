import json
import queue
import threading
import logging
import time
from app.config import settings

_reading_queue: queue.Queue = queue.Queue(maxsize=10)
_started = False

logger = logging.getLogger(__name__)


def get_latest_reading() -> dict | None:
    try:
        return _reading_queue.get_nowait()
    except queue.Empty:
        return None


def inject_reading(payload: dict) -> None:
    """Push a reading directly into the queue (for demo/simulation without Arduino)."""
    if _reading_queue.full():
        try:
            _reading_queue.get_nowait()
        except queue.Empty:
            pass
    _reading_queue.put_nowait(payload)


def _serial_loop() -> None:
    import serial
    port = settings.ARDUINO_SERIAL_PORT
    baud = settings.ARDUINO_BAUD_RATE
    while True:
        try:
            with serial.Serial(port, baud, timeout=2) as ser:
                logger.info(f"Serial connected on {port}")
                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                        if _reading_queue.full():
                            try:
                                _reading_queue.get_nowait()
                            except queue.Empty:
                                pass
                        _reading_queue.put_nowait(payload)
                    except json.JSONDecodeError:
                        logger.warning(f"Bad serial JSON: {line!r}")
        except Exception as e:
            logger.error(f"Serial error ({port}): {e} — retrying in 5s")
            time.sleep(5)


def start_serial_reader() -> None:
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_serial_loop, daemon=True)
    t.start()
    logger.info("Serial reader thread started")
