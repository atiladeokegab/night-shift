import pytest


@pytest.fixture(autouse=True)
def no_real_voice(monkeypatch):
    """A shell's real ElevenLabs key never reaches a test: replays would voice every line."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY_FALLBACKS", raising=False)


@pytest.fixture(autouse=True)
def no_budget_guard(monkeypatch):
    """The live site's limits (#244) are off in tests; tests/test_guard.py sets its own."""
    for name in ("MAX_LIVE_REPLAYS", "REPLAYS_PER_HOUR", "ASKS_PER_HOUR", "DAILY_BUDGET_USD"):
        monkeypatch.setenv(name, "0")


@pytest.fixture(autouse=True)
def fresh_stats(monkeypatch):
    """The live stats throttle is off in tests, so counts are current; a test sets its own."""
    monkeypatch.setattr("core.stats.STATS_EVERY_S", 0.0)


@pytest.fixture(autouse=True)
def long_stretches(monkeypatch, request):
    """The turn cap on a quiet stretch is off, so tests of the stretch's machinery see long ones;
    tests/test_pair_repeat.py keeps the real cap."""
    if not request.module.__name__.endswith("test_pair_repeat"):
        monkeypatch.setattr("core.insight.STRETCH_TURNS", 10**6)
