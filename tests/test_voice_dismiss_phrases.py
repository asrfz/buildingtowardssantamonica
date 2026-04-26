"""Unit tests for voice session dismiss phrases (no uagents import)."""
import re


def _strip_stt_artifacts(text: str) -> str:
    t = re.sub(r"\([^)]*\)", " ", text)
    return re.sub(r"\s+", " ", t).strip()


# Mirrors agents/voice_input_agent._DISMISS_VOICE_PATTERNS — update both when changing phrases.
_DISMISS_VOICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?is)^\s*(?:"
        r"bye\b|good-?bye\b|goodbye\b|see\s+you\b|see\s+ya\b|cya\b|cheerio\b"
        r")\s*(?:,|\s)*\s*(?:home\s*)?(?:pulse|post|posts|homepulse|program)?\s*\.{0,3}\s*$"
    ),
    re.compile(
        r"(?is)^\s*(?:home\s*)?(?:pulse|post|posts|homepulse)\s*(?:,|\s)+"
        r"(?:bye|good-?bye|goodbye|see\s+you|see\s+ya)\s*\.{0,3}\s*$"
    ),
    re.compile(
        r"(?is)^\s*(?:"
        r"stop\s+listening\b|end\s+(?:the\s+)?session\b|go\s+to\s+sleep\b|sleep\s+(?:now|mode)\b|"
        r"that(?:'|’)?s\s+all\b|that\s+is\s+all\b|we(?:'|’)?re\s+done\b|we\s+are\s+done\b|"
        r"i(?:'|’)?m\s+done\b|i\s+am\s+done\b|"
        r"no\s+more\s+questions?\b|nothing\s+else\b|all\s+set\b|"
        r"good\s+night\b(?:\s*(?:home\s*)?(?:pulse|post|posts|homepulse))?\s*|"
        r"dismiss(?:\s+(?:assistant|voice|home\s*pulse|homepulse))?\b|"
        r"turn\s+off(?:\s+(?:assistant|voice))?\b|mute\s+yourself\b|"
        r"later\s*,?\s*(?:home\s*)?(?:pulse|post|posts|homepulse)\b"
        r")\s*\.{0,3}\s*$"
    ),
)


def _is_dismiss_voice_session(text: str) -> bool:
    t = _strip_stt_artifacts(text)
    if not t:
        return False
    n = t.strip()
    n = re.sub(r"[.?!…]+$", "", n, flags=re.UNICODE).strip()
    if not n:
        return False
    return any(p.fullmatch(n) is not None for p in _DISMISS_VOICE_PATTERNS)


def test_dismiss_matches_common_phrases():
    assert _is_dismiss_voice_session("bye")
    assert _is_dismiss_voice_session("bye home pulse")
    assert _is_dismiss_voice_session("Bye Home Pulse")
    assert _is_dismiss_voice_session("goodbye homepulse")
    assert _is_dismiss_voice_session("home pulse bye")
    assert _is_dismiss_voice_session("stop listening")
    assert _is_dismiss_voice_session("end session")
    assert _is_dismiss_voice_session("go to sleep")
    assert _is_dismiss_voice_session("that's all")
    assert _is_dismiss_voice_session("we're done")
    assert _is_dismiss_voice_session("dismiss assistant")
    assert _is_dismiss_voice_session("good night")
    assert _is_dismiss_voice_session("later home pulse")


def test_dismiss_rejects_questions():
    assert not _is_dismiss_voice_session("what time is it")
    assert not _is_dismiss_voice_session("nearby store")
    assert not _is_dismiss_voice_session("hey")
