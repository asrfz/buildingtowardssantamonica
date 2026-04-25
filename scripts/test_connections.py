"""
HomePulse AI — Connection Test Suite

Verifies every external dependency independently so you know exactly what is
configured before starting agents or the FastAPI server.

Usage:
    python scripts/test_connections.py              # run all tests
    python scripts/test_connections.py mongo        # MongoDB only
    python scripts/test_connections.py claude       # Claude/Anthropic API only
    python scripts/test_connections.py gmail        # Gmail SMTP only
    python scripts/test_connections.py cloudinary   # Cloudinary only
    python scripts/test_connections.py serial       # Arduino serial port only
    python scripts/test_connections.py api          # FastAPI server (must be running)
"""
import asyncio
import sys
import os
import smtplib
import socket
import json
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

# ── ANSI colours (work in modern Windows Terminal / bash) ────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

_results: list[tuple[str, bool, str]] = []


def _ok(name: str, detail: str = "") -> None:
    msg = f"  {GREEN}✔{RESET}  {BOLD}{name}{RESET}"
    if detail:
        msg += f"  {CYAN}({detail}){RESET}"
    print(msg)
    _results.append((name, True, detail))


def _fail(name: str, detail: str = "") -> None:
    msg = f"  {RED}✘{RESET}  {BOLD}{name}{RESET}"
    if detail:
        msg += f"  {RED}{detail}{RESET}"
    print(msg)
    _results.append((name, False, detail))


def _skip(name: str, reason: str) -> None:
    msg = f"  {YELLOW}–{RESET}  {BOLD}{name}{RESET}  {YELLOW}SKIPPED: {reason}{RESET}"
    print(msg)
    _results.append((name, None, reason))


def _header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 56}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 56}{RESET}")


# ── 1. MongoDB ───────────────────────────────────────────────────────────────

async def test_mongo() -> None:
    _header("MongoDB")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
        info = await client.admin.command("ping")
        ok = info.get("ok") == 1.0
        if ok:
            # Verify the homepulse database is accessible
            db = client[settings.MONGODB_DB_NAME]
            collections = await db.list_collection_names()
            _ok("MongoDB ping", settings.MONGODB_URI)
            _ok("Database accessible", f"{settings.MONGODB_DB_NAME} — {len(collections)} collection(s)")
        else:
            _fail("MongoDB ping", "ping returned non-OK")
        client.close()
    except Exception as e:
        _fail("MongoDB", str(e))
        print(f"     {YELLOW}Hint: is mongod running? Try: mongod --dbpath /data/db{RESET}")


# ── 2. Claude / Anthropic API ────────────────────────────────────────────────

def test_claude() -> None:
    _header("Claude API (Anthropic)")
    if not settings.ANTHROPIC_API_KEY:
        _skip("Claude API", "ANTHROPIC_API_KEY not set in .env")
        return
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the word CONNECTED and nothing else."}],
        )
        text = response.content[0].text.strip()
        if "CONNECTED" in text.upper():
            _ok("Claude API", f"model=claude-haiku-4-5-20251001  reply={text!r}")
        else:
            _ok("Claude API reachable", f"unexpected reply: {text!r}")
    except Exception as e:
        _fail("Claude API", str(e))
        print(f"     {YELLOW}Hint: check ANTHROPIC_API_KEY in .env{RESET}")


# ── 3. Gmail SMTP ────────────────────────────────────────────────────────────

def test_gmail() -> None:
    _header("Gmail SMTP")
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        _skip("Gmail SMTP", "GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set in .env")
        return
    try:
        # Just connect + auth — don't send any mail
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            _ok("Gmail SMTP login", settings.GMAIL_ADDRESS)
    except smtplib.SMTPAuthenticationError as e:
        _fail("Gmail SMTP auth", str(e))
        print(f"     {YELLOW}Hint: use a Gmail App Password (not your account password){RESET}")
        print(f"     {YELLOW}      myaccount.google.com → Security → App passwords{RESET}")
    except socket.timeout:
        _fail("Gmail SMTP", "connection timed out (port 465)")
    except Exception as e:
        _fail("Gmail SMTP", str(e))


# ── 4. Cloudinary ────────────────────────────────────────────────────────────

def test_cloudinary() -> None:
    _header("Cloudinary")
    if not settings.CLOUDINARY_CLOUD_NAME:
        _skip("Cloudinary", "CLOUDINARY_CLOUD_NAME not set in .env")
        return
    try:
        import cloudinary
        import cloudinary.api
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )
        result = cloudinary.api.ping()
        if result.get("status") == "ok":
            _ok("Cloudinary ping", f"cloud_name={settings.CLOUDINARY_CLOUD_NAME}")
        else:
            _fail("Cloudinary ping", f"unexpected response: {result}")
    except ImportError:
        _fail("Cloudinary", "cloudinary package not installed — pip install cloudinary")
    except Exception as e:
        _fail("Cloudinary", str(e))
        print(f"     {YELLOW}Hint: check CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET{RESET}")


# ── 5. Arduino serial port ───────────────────────────────────────────────────

def test_serial() -> None:
    _header("Arduino Serial")
    port = settings.ARDUINO_SERIAL_PORT
    baud = settings.ARDUINO_BAUD_RATE
    try:
        import serial
        import serial.tools.list_ports

        available = [p.device for p in serial.tools.list_ports.comports()]
        if available:
            print(f"  Available ports: {', '.join(available)}")
        else:
            print(f"  No serial ports detected on this machine.")

        if port not in available:
            _fail("Serial port", f"{port} not found. Available: {available or 'none'}")
            return

        with serial.Serial(port, baud, timeout=2) as ser:
            _ok("Serial port opened", f"{port} @ {baud} baud")
            # Try to read one line to confirm data is flowing
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                try:
                    data = json.loads(line)
                    _ok("Arduino data received", f"keys={list(data.keys())}")
                except json.JSONDecodeError:
                    _ok("Serial readable", f"raw line (non-JSON): {line[:60]!r}")
            else:
                _skip("Arduino data", "no data received within 2s (Arduino may not be transmitting)")
    except ImportError:
        _fail("Serial (pyserial)", "not installed — pip install pyserial")
    except Exception as e:
        _fail("Serial port", str(e))


# ── 6. FastAPI server health ─────────────────────────────────────────────────

def test_api() -> None:
    _header("FastAPI Server")
    base = "http://127.0.0.1:8000"
    try:
        # Hit /docs (always available in FastAPI) as a cheap health check
        req = urllib.request.Request(f"{base}/docs", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                _ok("FastAPI /docs", base)
    except urllib.error.URLError as e:
        _fail("FastAPI server", f"not reachable at {base} — {e.reason}")
        print(f"     {YELLOW}Hint: start the server with: uvicorn app.main:app --reload{RESET}")
        return

    # Also verify the /sensor/simulate endpoint exists
    try:
        payload = json.dumps({
            "sound_level": 200, "temperature_c": 22.0, "magnetic_state": 0,
            "accel_x": 0.0, "accel_y": 0.0, "accel_z": 9.81, "pressure": 1013.0,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }).encode()
        req = urllib.request.Request(
            f"{base}/sensor/simulate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            _ok("/sensor/simulate", f"status={body.get('status')!r}")
    except urllib.error.HTTPError as e:
        _fail("/sensor/simulate", f"HTTP {e.code}: {e.reason}")
    except Exception as e:
        _fail("/sensor/simulate", str(e))


# ── Summary ──────────────────────────────────────────────────────────────────

def _print_summary() -> None:
    passed  = [r for r in _results if r[1] is True]
    failed  = [r for r in _results if r[1] is False]
    skipped = [r for r in _results if r[1] is None]

    print(f"\n{BOLD}{'═' * 56}{RESET}")
    print(f"{BOLD}  Summary{RESET}")
    print(f"{BOLD}{'═' * 56}{RESET}")
    print(f"  {GREEN}{len(passed)} passed{RESET}  "
          f"{RED}{len(failed)} failed{RESET}  "
          f"{YELLOW}{len(skipped)} skipped{RESET}")

    if failed:
        print(f"\n  {RED}Failed:{RESET}")
        for name, _, detail in failed:
            print(f"    • {name}: {detail}")

    if skipped:
        print(f"\n  {YELLOW}Skipped (add to .env to enable):{RESET}")
        for name, _, reason in skipped:
            print(f"    • {name}: {reason}")

    print()
    return len(failed)


# ── Entry point ──────────────────────────────────────────────────────────────

ALL_TESTS = {
    "mongo":      test_mongo,        # async
    "claude":     test_claude,       # sync
    "gmail":      test_gmail,        # sync
    "cloudinary": test_cloudinary,   # sync
    "serial":     test_serial,       # sync
    "api":        test_api,          # sync
}

ASYNC_TESTS = {"mongo"}


async def _run_all(selected: list[str]) -> int:
    print(f"\n{BOLD}HomePulse AI — Connection Test Suite{RESET}")
    print(f"Running: {', '.join(selected)}\n")

    for name in selected:
        fn = ALL_TESTS[name]
        if name in ASYNC_TESTS:
            await fn()
        else:
            fn()

    return _print_summary()


if __name__ == "__main__":
    args = sys.argv[1:]
    unknown = [a for a in args if a not in ALL_TESTS]
    if unknown:
        print(f"Unknown test(s): {unknown}")
        print(f"Available: {list(ALL_TESTS.keys())}")
        sys.exit(1)

    selected = args if args else list(ALL_TESTS.keys())
    failures = asyncio.run(_run_all(selected))
    sys.exit(0 if failures == 0 else 1)
