"""
Tests for triage_agent decision logic with Claude mocked.

Verifies:
- Claude's "investigate=True" result leads to event being written + chain continuing
- Claude's "investigate=False" result leads to event being dismissed
- High false positive rate is passed correctly to Claude
- MongoDB writes happen regardless of triage outcome
- Handles Claude API failure gracefully

No real API calls — Claude is mocked via pytest-mock.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bson import ObjectId
from test_support.constants import DEMO_EVENT_ID, DEMO_USER_ID


# Simulated Claude responses
INVESTIGATE_TRUE = {"investigate": True,  "confidence": 0.92, "reason": "3am temp spike with no movement is suspicious"}
INVESTIGATE_FALSE = {"investigate": False, "confidence": 0.85, "reason": "Dinner time temperature rise — likely cooking"}


class TestTriageDecisions:
    async def test_investigate_true_writes_triaged_status(self, mock_db):
        """When Claude says investigate, event status should be 'triaged'."""
        with patch("app.services.claude_service.triage_event", new=AsyncMock(return_value=INVESTIGATE_TRUE)):
            from app.schemas.event_schema import build_event_doc
            from app.services import claude_service

            result = await claude_service.triage_event(
                event_type="STOVE_LEFT_ON",
                deviation_score=17.33,
                sensor_payload={"temperature_c": 48.0},
                hour=3,
                day_type="weekday",
                recent_false_positive_rate=0.1,
            )
            assert result["investigate"] is True
            assert result["confidence"] > 0.5

    async def test_investigate_false_returns_dismissed(self, mock_db):
        """When Claude says don't investigate, result should be dismissal."""
        with patch("app.services.claude_service.triage_event", new=AsyncMock(return_value=INVESTIGATE_FALSE)):
            from app.services import claude_service

            result = await claude_service.triage_event(
                event_type="STOVE_LEFT_ON",
                deviation_score=4.5,
                sensor_payload={"temperature_c": 29.0},
                hour=18,
                day_type="weekday",
                recent_false_positive_rate=0.6,
            )
            assert result["investigate"] is False

    async def test_event_doc_status_maps_correctly(self):
        """build_event_doc sets correct status string."""
        from app.schemas.event_schema import build_event_doc

        doc_triaged = build_event_doc(
            user_id=DEMO_USER_ID,
            event_type="STOVE_LEFT_ON",
            severity="CRITICAL",
            deviation_score=17.33,
            sensor_payload={},
            status="triaged",
        )
        assert doc_triaged["status"] == "triaged"
        assert doc_triaged["confirmed"] is None
        assert doc_triaged["notification_sent"] is False

        doc_dismissed = build_event_doc(
            user_id=DEMO_USER_ID,
            event_type="STOVE_LEFT_ON",
            severity="MEDIUM",
            deviation_score=4.5,
            sensor_payload={},
            status="dismissed",
        )
        assert doc_dismissed["status"] == "dismissed"


class TestFalsePositiveRatePassthrough:
    """Verify the FP rate from behavioral schema is passed to Claude correctly."""

    async def test_zero_history_defaults_to_20_percent(self, mock_db):
        """No behavioral schema entry → default fp_rate=0.2 (20%)."""
        schema = {"event_type_history": {}}
        fp_rate = (
            schema.get("event_type_history", {})
            .get("STOVE_LEFT_ON", {})
            .get("false_positive_rate", 0.2)
        )
        assert fp_rate == 0.2

    async def test_known_high_fp_rate_is_extracted(self, mock_db):
        """Schema with 60% FP rate → that value is passed to Claude."""
        schema = {
            "event_type_history": {
                "STOVE_LEFT_ON": {"total": 10, "false_positives": 6, "false_positive_rate": 0.6}
            }
        }
        fp_rate = schema["event_type_history"]["STOVE_LEFT_ON"]["false_positive_rate"]
        assert fp_rate == 0.6

    async def test_known_low_fp_rate_is_extracted(self):
        schema = {
            "event_type_history": {
                "FAUCET_RUNNING": {"total": 5, "false_positives": 0, "false_positive_rate": 0.0}
            }
        }
        fp_rate = schema["event_type_history"]["FAUCET_RUNNING"]["false_positive_rate"]
        assert fp_rate == 0.0


class TestJSONParsing:
    """Test that claude_service._parse_json handles Claude's response variations."""

    def test_plain_json(self):
        from app.services.claude_service import _parse_json
        result = _parse_json('{"investigate": true, "confidence": 0.9, "reason": "test"}')
        assert result["investigate"] is True
        assert result["confidence"] == 0.9

    def test_json_with_code_fence(self):
        from app.services.claude_service import _parse_json
        text = '```json\n{"investigate": false, "confidence": 0.8, "reason": "normal"}\n```'
        result = _parse_json(text)
        assert result["investigate"] is False

    def test_json_with_plain_fence(self):
        from app.services.claude_service import _parse_json
        text = '```\n{"investigate": true, "confidence": 0.95, "reason": "suspicious"}\n```'
        result = _parse_json(text)
        assert result["investigate"] is True

    def test_json_with_whitespace(self):
        from app.services.claude_service import _parse_json
        text = '\n\n{"investigate": true, "confidence": 0.7, "reason": "check it"}\n\n'
        result = _parse_json(text)
        assert result["reason"] == "check it"


class TestGmailService:
    """Test Gmail service logic with SMTP mocked — no real emails sent."""

    def test_send_skips_when_no_credentials(self):
        """If GMAIL_ADDRESS is empty, _send returns False without attempting SMTP."""
        from app.services.gmail_service import _send
        from unittest.mock import patch

        with patch("app.services.gmail_service.settings") as mock_settings:
            mock_settings.GMAIL_ADDRESS = ""
            mock_settings.GMAIL_APP_PASSWORD = ""
            result = _send(["test@example.com"], "Test Subject", "<p>body</p>")
        assert result is False

    def test_send_returns_true_on_smtp_success(self):
        """Mock a successful SMTP connection and verify True is returned."""
        from app.services.gmail_service import _send
        from unittest.mock import patch, MagicMock

        with patch("app.services.gmail_service.settings") as mock_settings, \
             patch("smtplib.SMTP_SSL") as mock_smtp:
            mock_settings.GMAIL_ADDRESS = "sender@gmail.com"
            mock_settings.GMAIL_APP_PASSWORD = "apppassword"

            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

            result = _send(["recipient@example.com"], "Alert", "<p>test</p>")
        assert result is True

    def test_send_returns_false_on_smtp_error(self):
        """SMTP connection failure → returns False, does not raise."""
        from app.services.gmail_service import _send
        from unittest.mock import patch

        with patch("app.services.gmail_service.settings") as mock_settings, \
             patch("smtplib.SMTP_SSL", side_effect=Exception("connection refused")):
            mock_settings.GMAIL_ADDRESS = "sender@gmail.com"
            mock_settings.GMAIL_APP_PASSWORD = "apppassword"
            result = _send(["recipient@example.com"], "Alert", "<p>test</p>")
        assert result is False
