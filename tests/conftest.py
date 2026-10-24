import pytest


@pytest.fixture(autouse=True)
def no_real_voice(monkeypatch):
    """A shell's real ElevenLabs key never reaches a test: replays would voice every line."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_budget_guard(monkeypatch):
    """The live site's limits (#244) are off in tests; tests/test_guard.py sets its own."""
    for name in ("MAX_LIVE_REPLAYS", "REPLAYS_PER_HOUR", "ASKS_PER_HOUR", "DAILY_BUDGET_USD"):
        monkeypatch.setenv(name, "0")
