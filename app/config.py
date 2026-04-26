from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # MongoDB
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "homepulse"

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # Gmail SMTP
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # Arduino Serial (set ARDUINO_SERIAL_ENABLED=false to run agents without COM / use POST /sensor/simulate only)
    ARDUINO_SERIAL_ENABLED: bool = True
    ARDUINO_SERIAL_PORT: str = "COM3"
    ARDUINO_BAUD_RATE: int = 9600
    # Seconds to wait before first COM open (e.g. 2–3 after closing Arduino IDE / Serial Monitor).
    ARDUINO_SERIAL_CONNECT_DELAY_SEC: float = 0.0
    WEBCAM_INDEX: int = 0

    # FetchAI
    FETCHAI_AGENT_SEED: str = "homepulse_default_seed"
    AGENTVERSE_KEY: str = ""
    # uAgents Bureau HTTP port (default 8002). If busy, run_agents scans a small range.
    UAGENTS_BUREAU_PORT: int = 8002
    # When True, skip Fetch.ai Almanac batch registration on bureau startup (stops timeout spam;
    # agents in the same process still message each other via the local dispatcher).
    UAGENTS_SKIP_ALMANAC_REGISTRATION: bool = True
    # When True, dashboard_agent uses Agentverse mailbox (ASI:One / standalone dashboard script).
    # When False (default), it shares the bureau HTTP endpoint — required for reliable voice → dashboard in run_agents.
    HOMEPULSE_DASHBOARD_MAILBOX: bool = False

    # Anthropic Claude API
    ANTHROPIC_API_KEY: str = ""

    # ElevenLabs TTS
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"   # Rachel — default, override in .env

    # Internal HTTP base for agents → FastAPI (browser capture, /voice/push).
    # Default 127.0.0.1 avoids Windows localhost→IPv6 connection issues.
    HOMEPULSE_API_BASE: str = "http://127.0.0.1:8000"

    # App Settings
    APP_ENV: str = "development"
    DEFAULT_USER_ID: str = ""
    # Demo / fallback: when voice guidance repeats, email this address. If empty, uses first
    # emergency_contacts[].email on the DEFAULT_USER_ID user document.
    EMERGENCY_NOTIFY_EMAIL: str = ""
    CANCEL_WINDOW_SECONDS: int = 60
    # Consecutive sensor anomaly ticks before triage announces + emails emergency contacts (no voice ack required).
    SENSOR_STREAK_EMAIL_THRESHOLD: int = 3
    # Minimum seconds between full triage pipelines for the same event_type (stops 5s serial spam / "loops"). 0 = off.
    SENSOR_ANOMALY_COOLDOWN_SECONDS: float = 90.0
    # One MongoDB "slot" per investigating triage; vision + preview-snapshot share it (no stacked Cloudinary uploads).
    SNAPSHOT_CLOUDINARY_GATE_ENABLED: bool = True
    THRESHOLD_MULTIPLIER: float = 2.5
    CALIBRATION_HOURS: int = 48
    HEARTBEAT_TIMEOUT_SECONDS: int = 120
    REPORT_SCHEDULE_DAYS: int = 7

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
