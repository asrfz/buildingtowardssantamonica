import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings

logger = logging.getLogger(__name__)


def _send(to_addresses: list[str], subject: str, html_body: str) -> bool:
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        logger.warning("Gmail credentials not configured — skipping send")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.GMAIL_ADDRESS
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            server.sendmail(settings.GMAIL_ADDRESS, to_addresses, msg.as_string())
        logger.info(f"Email sent to {to_addresses}: {subject!r}")
        return True
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        return False


async def send_alert(user: dict, event: dict, email_body: str) -> bool:
    subject = (
        f"[HomePulse {event['severity']}] "
        f"{event['event_type'].replace('_', ' ').title()} detected"
    )
    return _send([user["email"]], subject, email_body)


async def send_to_contact(contact: dict, event: dict, email_body: str) -> bool:
    subject = f"[HomePulse] Alert for {event.get('user_name', 'your loved one')}"
    return _send([contact["email"]], subject, email_body)


async def send_weekly_digest(recipients: list[str], digest_html: str) -> bool:
    return _send(recipients, "HomePulse Weekly Safety Digest", digest_html)


async def send_system_offline_alert(user: dict) -> bool:
    body = (
        "<h2 style='color:#e53e3e'>⚠️ HomePulse Sensor Offline</h2>"
        "<p style='font-size:18px'>Your HomePulse sensor has gone silent. "
        "Please check that the device is plugged in and connected.</p>"
    )
    return _send([user["email"]], "[HomePulse] Sensor offline — please check device", body)


def send_voice_guidance_escalation_sync(
    to_addresses: list[str],
    *,
    event_id: str,
    object_name: str,
    repeated_phrase: str,
    user_id: str,
) -> bool:
    """Alert emergency contact when voice guidance repeats the same instruction."""
    if not to_addresses:
        return False
    body = (
        "<h2 style='color:#c2410c'>HomePulse — voice guidance needs attention</h2>"
        "<p>The voice assistant gave the <strong>same directional instruction at least three times</strong> "
        "without the situation resolving. Please check in with the resident.</p>"
        f"<ul style='font-size:16px;line-height:1.6'>"
        f"<li><strong>Event ID:</strong> {event_id}</li>"
        f"<li><strong>User ID:</strong> {user_id}</li>"
        f"<li><strong>Object:</strong> {object_name}</li>"
        f"<li><strong>Repeated phrase:</strong> {repeated_phrase}</li>"
        "</ul>"
    )
    return _send(
        to_addresses,
        "[HomePulse] Voice guidance stuck — please check in",
        body,
    )


async def send_test_email(to_address: str) -> bool:
    body = (
        "<h2 style='color:#38a169'>✅ HomePulse Gmail Connection Verified</h2>"
        "<p>Your HomePulse system can send email notifications successfully.</p>"
    )
    return _send([to_address], "[HomePulse] System test — connection verified", body)
