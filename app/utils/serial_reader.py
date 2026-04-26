import json
import queue
import threading
import logging
import time
from datetime import datetime, timezone
from app.config import settings

_reading_queue: queue.Queue = queue.Queue(maxsize=10)
_started = False

logger = logging.getLogger(__name__)


def _normalize_payload(raw: dict) -> dict:
    """
    Normalize Arduino JSON variants into backend SensorPayload shape.
    """
    accel_mag = float(raw.get("accel", 0.0))
    magnetic_mag = float(raw.get("magnetic", 0.0))

    return {
        "sound_level": int(float(raw.get("sound_level", raw.get("sound", 0.0)))),
        "temperature_c": float(raw.get("temperature_c", 22.0)),
        "magnetic_state": int(raw.get("magnetic_state", 1 if magnetic_mag > 60 else 0)),
        "accel_x": float(raw.get("accel_x", 0.0)),
        "accel_y": float(raw.get("accel_y", 0.0)),
        "accel_z": float(raw.get("accel_z", accel_mag)),
        "pressure": float(raw.get("pressure", 1013.0)),
        "timestamp": raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "drop_detected": int(raw.get("drop_detected", 0)),
        "light_change_detected": int(raw.get("light_change_detected", raw.get("light_triggered", 0))),
        "motion_triggered": int(raw.get("motion_triggered", 0)),
        "gyro_triggered": int(raw.get("gyro_triggered", 0)),
        "sound_triggered": int(raw.get("sound_triggered", 0)),
        "magnetic_triggered": int(raw.get("magnetic_triggered", 0)),
    }


def get_latest_reading() -> dict | None:
    try:
        return _reading_queue.get_nowait()
    except queue.Empty:
        return None


def inject_reading(payload: dict) -> None:
    """Push a reading directly into the queue (for demo/simulation without Arduino)."""
    payload = _normalize_payload(payload)
    if _reading_queue.full():
        try:
            _reading_queue.get_nowait()
        except queue.Empty:
            pass
    _reading_queue.put_nowait(payload)


def _serial_loop() -> None:
    import serial
    from serial.serialutil import SerialException

    port = settings.ARDUINO_SERIAL_PORT
    baud = settings.ARDUINO_BAUD_RATE
    permission_logged = False

    while True:
        retry_s = 5
        try:
            with serial.Serial(port, baud, timeout=2) as ser:
                permission_logged = False
                logger.info("Serial connected on %s @ %s baud", port, baud)
                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        payload = _normalize_payload(json.loads(line))
                        if _reading_queue.full():
                            try:
                                _reading_queue.get_nowait()
                            except queue.Empty:
                                pass
                        _reading_queue.put_nowait(payload)
                    except json.JSONDecodeError:
                        logger.warning("Bad serial JSON: %r", line)
        except PermissionError as e:
            retry_s = 12
            if not permission_logged:
                logger.error(
                    "Serial port %s: access denied. Another program has the port open "
                    "(often Arduino IDE Serial Monitor, a second HomePulse process, or a serial "
                    "terminal). Close it so only one reader uses %s. Error: %s",
                    port,
                    port,
                    e,
                )
                permission_logged = True
            else:
                logger.error(
                    "Serial port %s still unavailable (PermissionError) — retrying in %ss",
                    port,
                    retry_s,
                )
        except SerialException as e:
            logger.exception("Serial device error on %s: %s — retrying in %ss", port, e, retry_s)
        except OSError as e:
            logger.exception(
                "Serial OS error on %s (errno=%s): %s — retrying in %ss",
                port,
                getattr(e, "errno", None),
                e,
                retry_s,
            )
        except Exception:
            logger.exception("Unexpected serial reader error on %s — retrying in %ss", port, retry_s)

        time.sleep(retry_s)


def start_serial_reader() -> None:
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_serial_loop, daemon=True)
    t.start()
    logger.info("Serial reader thread started")
