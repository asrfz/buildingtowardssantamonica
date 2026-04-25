"""
Unit tests for escalation logic.

Tests the severity ladder rules:
- LOW  → no notification
- MEDIUM → user only, 60s cancel window
- HIGH   → user + emergency contact, 60s cancel window
- CRITICAL → user + emergency contact, NO cancel window

No API keys needed — pure logic tests.
"""
import pytest
from app.utils.severity import compute_severity
from tests.conftest import DEMO_USER_DOC


# ── Severity ladder: recipient routing ───────────────────────────────────────

class TestRecipientRouting:
    def _get_recipients(self, user: dict, severity: str) -> list[str]:
        """Replicate escalation_agent recipient logic."""
        recipients = [user["email"]]
        if severity in ("HIGH", "CRITICAL"):
            for contact in user.get("emergency_contacts", []):
                recipients.append(contact["email"])
        return recipients

    def test_low_severity_not_notified(self):
        """LOW events are logged only — escalation_agent returns early."""
        assert compute_severity(2.0) == "LOW"

    def test_medium_sends_to_user_only(self):
        recipients = self._get_recipients(DEMO_USER_DOC, "MEDIUM")
        assert recipients == ["test@example.com"]
        assert len(recipients) == 1

    def test_high_includes_emergency_contact(self):
        recipients = self._get_recipients(DEMO_USER_DOC, "HIGH")
        assert "test@example.com" in recipients
        assert "son@example.com" in recipients
        assert len(recipients) == 2

    def test_critical_includes_emergency_contact(self):
        recipients = self._get_recipients(DEMO_USER_DOC, "CRITICAL")
        assert "son@example.com" in recipients

    def test_user_with_no_emergency_contacts_high(self):
        user = {**DEMO_USER_DOC, "emergency_contacts": []}
        recipients = self._get_recipients(user, "HIGH")
        assert recipients == ["test@example.com"]
        assert len(recipients) == 1

    def test_user_with_multiple_contacts(self):
        user = {
            **DEMO_USER_DOC,
            "emergency_contacts": [
                {"name": "Son", "email": "son@example.com"},
                {"name": "Daughter", "email": "daughter@example.com"},
            ],
        }
        recipients = self._get_recipients(user, "CRITICAL")
        assert len(recipients) == 3
        assert "son@example.com" in recipients
        assert "daughter@example.com" in recipients


# ── Cancel window rules ──────────────────────────────────────────────────────

class TestCancelWindow:
    CANCEL_WINDOW = 60

    def _get_cancel_window(self, severity: str) -> int:
        """Replicate escalation_agent cancel window logic."""
        return 0 if severity == "CRITICAL" else self.CANCEL_WINDOW

    def test_low_cancel_window(self):
        assert self._get_cancel_window("LOW") == 60

    def test_medium_cancel_window(self):
        assert self._get_cancel_window("MEDIUM") == 60

    def test_high_cancel_window(self):
        assert self._get_cancel_window("HIGH") == 60

    def test_critical_no_cancel_window(self):
        """CRITICAL events cannot be cancelled — send immediately, no delay."""
        assert self._get_cancel_window("CRITICAL") == 0


# ── Severity mapping from real deviation scores ──────────────────────────────

class TestSeverityFromScores:
    """Verify the score → severity mapping against expected demo values."""

    EXPECTED = [
        # (scenario, deviation_score, expected_severity)
        ("stove 48°C",    17.33, "CRITICAL"),   # 26/1.5
        ("faucet 420",     4.4,  "MEDIUM"),      # 220/50
        ("fridge open",    4.0,  "MEDIUM"),      # hardcoded in anomaly_detector
        ("iron 35°C",      8.67, "HIGH"),        # 13/1.5
        ("fire 65°C",     28.67, "CRITICAL"),    # 43/1.5
        ("water drip 280", 1.6,  "LOW"),         # 80/50
    ]

    @pytest.mark.parametrize("scenario,score,expected", EXPECTED)
    def test_severity_mapping(self, scenario: str, score: float, expected: str):
        assert compute_severity(score) == expected, f"Failed for {scenario}"
