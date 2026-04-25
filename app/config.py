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

    # Arduino Serial
    ARDUINO_SERIAL_PORT: str = "COM3"
    ARDUINO_BAUD_RATE: int = 9600
    WEBCAM_INDEX: int = 0

    # FetchAI
    FETCHAI_AGENT_SEED: str = "homepulse_default_seed"
    AGENTVERSE_KEY: str = ""

    # Anthropic Claude API
    ANTHROPIC_API_KEY: str = ""

    # App Settings
    APP_ENV: str = "development"
    DEFAULT_USER_ID: str = ""
    CANCEL_WINDOW_SECONDS: int = 60
    THRESHOLD_MULTIPLIER: float = 2.5
    CALIBRATION_HOURS: int = 48
    HEARTBEAT_TIMEOUT_SECONDS: int = 120
    REPORT_SCHEDULE_DAYS: int = 7

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
