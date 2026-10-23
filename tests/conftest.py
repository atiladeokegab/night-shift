import pytest


@pytest.fixture(autouse=True)
def no_real_voice(monkeypatch):
    """A shell's real ElevenLabs key never reaches a test: replays would voice every line."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
