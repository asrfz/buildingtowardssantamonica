import json
import queue
import threading
import logging
import time
from datetime import datetime, timezone
from app.config import settings

_reading_queue: queue.Queue = queue.Queue(maxsize=10)
_started = False
_serial_stopped_access: bool = False  # True if we gave up on COM (port busy); no retries
# Latest normalized payload (serial or POST /sensor/simulate inject) for caregiver UI.
_last_ingested_payload: dict | None = None
_last_ingested_monotonic: float = 0.0

logger = logging.getLogger(__name__)


def _is_port_access_denied(exc: BaseException) -> bool:
    """Windows / pyserial: another process holds the COM port or we lack rights."""
    if isinstance(exc, PermissionError):
        return True
    errno = getattr(exc, "errno", None)
    if errno in (13, 5):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror == 5:
        return True
    text = str(exc).lower()
    if "access is denied" in text or "permissionerror" in text:
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _is_port_access_denied(cause)
    return False


def serial_reader_gave_up() -> bool:
    """True if hardware serial was abandoned due to access denied (use simulate or free COM)."""
    return _serial_stopped_access


def _optional_float(raw: dict, key: str) -> float | None:
    if key not in raw:
        return None
    v = raw[key]
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_payload(raw: dict) -> dict:
    """
    Normalize Arduino JSON variants into backend SensorPayload shape.
    Missing / JSON null → None for temperature, pressure, light (no invented defaults).
    """
    accel_mag = float(raw.get("accel", 0.0))
    gyro_mag = float(raw.get("gyro", raw.get("gyro_magnitude", 0.0)))
    magnetic_mag = float(raw.get("magnetic", 0.0))
    # PDM / Nicla: average abs of int16 samples — often >1023; keep int for baselines
    sound_raw = float(raw.get("sound_level", raw.get("sound", 0.0)))
    sound_level = max(0, min(65535, int(round(sound_raw))))

    light_level: int | None = None
    if "light" in raw or "light_level" in raw:
        light_raw = raw.get("light_level", raw.get("light"))
        if light_raw is not None:
            try:
                light_level = max(0, min(1023, int(round(float(light_raw)))))
            except (TypeError, ValueError):
                light_level = None

    temperature_c = _optional_float(raw, "temperature_c")
    pressure = _optional_float(raw, "pressure")

    return {
        "sound_level": sound_level,
        "temperature_c": temperature_c,
        "magnetic_state": int(raw.get("magnetic_state", 1 if magnetic_mag > 60 else 0)),
        # inputs.ino: accel/gyro are vector magnitudes; put mag on z so embedding sees motion.
        "accel_x": float(raw.get("accel_x", 0.0)),
        "accel_y": float(raw.get("accel_y", 0.0)),
        "accel_z": float(raw.get("accel_z", accel_mag)),
        "gyro_magnitude": max(0.0, gyro_mag),
        "pressure": pressure,
        "timestamp": raw.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "drop_detected": int(raw.get("drop_detected", 0)),
        "light_change_detected": int(raw.get("light_change_detected", raw.get("light_triggered", 0))),
        "motion_triggered": int(raw.get("motion_triggered", 0)),
        "gyro_triggered": int(raw.get("gyro_triggered", 0)),
        "sound_triggered": int(raw.get("sound_triggered", 0)),
        "magnetic_triggered": int(raw.get("magnetic_triggered", 0)),
        "light_level": light_level,
    }


def get_latest_reading() -> dict | None:
    try:
        return _reading_queue.get_nowait()
    except queue.Empty:
        return None


def _touch_last_ingested(payload: dict) -> None:
    global _last_ingested_payload, _last_ingested_monotonic
    _last_ingested_payload = dict(payload)
    _last_ingested_monotonic = time.monotonic()


def get_last_ingested_reading() -> dict | None:
    """Most recent normalized SensorPayload-shaped dict (any source)."""
    if _last_ingested_payload is None:
        return None
    return {"payload": _last_ingested_payload, "monotonic_ts": _last_ingested_monotonic}


def inject_reading(payload: dict) -> None:
    """Push a reading directly into the queue (for demo/simulation without Arduino)."""
    payload = _normalize_payload(payload)
    _touch_last_ingested(payload)
    if _reading_queue.full():
        try:
            _reading_queue.get_nowait()
        except queue.Empty:
            pass
    _reading_queue.put_nowait(payload)


def _serial_loop() -> None:
    global _serial_stopped_access
    import serial
    from serial.serialutil import SerialException

    port = settings.ARDUINO_SERIAL_PORT
    baud = settings.ARDUINO_BAUD_RATE
    delay = float(settings.ARDUINO_SERIAL_CONNECT_DELAY_SEC or 0.0)
    if delay > 0:
        logger.info(
            "Waiting %.1fs before opening %s (set ARDUINO_SERIAL_CONNECT_DELAY_SEC=0 to skip)",
            delay,
            port,
        )
        time.sleep(delay)

    while True:
        retry_s = 5
        try:
            with serial.Serial(port, baud, timeout=2) as ser:
                logger.info("Serial connected on %s @ %s baud", port, baud)
                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        payload = _normalize_payload(json.loads(line))
                        _touch_last_ingested(payload)
                        if _reading_queue.full():
                            try:
                                _reading_queue.get_nowait()
                            except queue.Empty:
                                pass
                        _reading_queue.put_nowait(payload)
                    except json.JSONDecodeError:
                        logger.warning("Bad serial JSON: %r", line)
        except (SerialException, PermissionError, OSError) as e:
            # Cannot share COM on Windows — retrying forever just spams logs.
            if _is_port_access_denied(e):
                _serial_stopped_access = True
                logger.warning(
                    "Serial %s: access denied — stopping serial reader permanently for this run. "
                    "Agents keep running; use POST /sensor/simulate or free the port and restart "
                    "run_agents.py. (%s)",
                    port,
                    e,
                )
                return
            if isinstance(e, SerialException):
                logger.exception(
                    "Serial device error on %s: %s — retrying in %ss", port, e, retry_s
                )
            else:
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
