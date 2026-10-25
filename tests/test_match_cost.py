"""Cost per match (#174): what one full replay spent, model plus voice, from the store only."""

import asyncio
import json

from core.replay import Replay, run_replay
from core.store import Store

MOMENTS = [
    {"sport": "football", "match_id": "f1", "idx": i, "clock": clock, "type": "Shot"}
    for i, clock in enumerate(["03:10", "41:02"])
]
VIDEO = {
    "youtube_id": "abcdefghijk",
    # too close for a cold open or a stretch line (#297): the two moments' lines alone
    "moments": [{"idx": 0, "video_t": 1.0}, {"idx": 1, "video_t": 3.0}],
}


def commentate(moment, history):
    return {"line_id": f"f1-{moment['idx']}", "text": "Shot!", "model": "claude-haiku-4-5"}


def test_a_full_replay_tags_its_lines_and_voice_and_is_stored_as_a_match(tmp_path):
    store, spoken = Store(tmp_path), []
    replay = Replay("f1", speed=1.0)
    speak = lambda line, moment, at: spoken.append(line["replay_id"])  # noqa: E731
    asyncio.run(run_replay(replay, MOMENTS, commentate, store, VIDEO, speak))
    assert [ln["replay_id"] for ln in store.all("lines")] == [replay.id] * 2
    assert spoken == [replay.id] * 2
    match = {"replay_id": replay.id, "match_id": "f1", "line_ids": ["f1-0", "f1-1"]}
    assert store.all("replays") == [match]


def test_a_jump_is_not_a_match(tmp_path):
    store = Store(tmp_path)
    asyncio.run(run_replay(Replay("f1", speed=1.0), MOMENTS, commentate, store, VIDEO, None, 1))
    assert store.all("replays") == []


def test_a_smoke_replay_is_not_a_match(tmp_path):
    store = Store(tmp_path)
    asyncio.run(run_replay(Replay("f1", 1.0, smoke=True), MOMENTS, commentate, store, VIDEO, None))
    assert store.all("replays") == []


def test_the_voice_records_the_characters_of_each_call_that_spoke(monkeypatch, tmp_path):
    import httpx

    from core.voice import VOICES, Speaker

    def handle(request):  # v3 fails, so flash speaks the untagged text
        v3 = json.loads(request.content)["model_id"] == "eleven_v3"
        return httpx.Response(500 if v3 else 200, content=b"mp3")

    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-eleven")
    store = Store(tmp_path)
    speaker = Speaker(httpx.MockTransport(handle), store)
    line = {"line_id": "x", "sport": "football", "text": "Goal!", "replay_id": "r1"}
    assert asyncio.run(speaker.audio(line, VOICES[1])) == (b"mp3", "eleven_flash_v2_5")
    voice = store.all("voice")
    assert [{k: v for k, v in row.items() if k != "created_at"} for row in voice] == [
        {"line_id": "x", "replay_id": "r1", "model": "eleven_flash_v2_5", "chars": 5}
    ]
    assert voice[0]["created_at"]  # the daily cap counts voice by when it was made


def seeded(tmp_path):
    """Two full replays with known tokens and characters, plus spend that is not a full match."""
    store = Store(tmp_path)
    store.append("replays", {"replay_id": "a", "match_id": "f1", "line_ids": ["la"]})
    store.append("replays", {"replay_id": "b", "match_id": "f1", "line_ids": ["lb"]})
    haiku = {"model": "claude-haiku-4-5", "replay_id": "a"}
    store.append("lines", {**haiku, "line_id": "la", "tokens_in": 1_000_000, "tokens_out": 100_000})
    store.append("voice", {"replay_id": "a", "model": "eleven_v3", "chars": 10_000})  # $0.80
    sonnet = {"model": "claude-sonnet-5-5", "replay_id": "b"}
    store.append("lines", {**sonnet, "line_id": "lb", "tokens_in": 500_000, "tokens_out": 50_000})
    answer = {"model": "claude-haiku-4-5", "replay_id": "b", "tokens_in": 200_000, "tokens_out": 0}
    store.append("answers", answer)  # $0.20
    store.append("voice", {"replay_id": "b", "model": "eleven_flash_v2_5", "chars": 25_000})  # $1
    # a jump and a line from before #174: neither is a full match
    store.append("lines", {**haiku, "line_id": "lj", "replay_id": "jump", "tokens_in": 9_000_000})
    store.append("voice", {"replay_id": "jump", "model": "eleven_v3", "chars": 99_000})
    store.append("lines", {"model": "claude-haiku-4-5", "tokens_in": 9_000_000})
    return store


def test_cost_per_match_is_the_mean_of_full_replays_model_and_voice(tmp_path):
    from core.stats import stats

    out = stats(seeded(tmp_path))
    assert out["matches_measured"] == 2
    assert round(out["model_cost_per_match_usd"], 2) == 1.60  # (1.50 + 1.50 + 0.20) / 2
    assert round(out["voice_cost_per_match_usd"], 2) == 0.90  # (0.80 + 1.00) / 2
    assert round(out["cost_per_match_usd"], 2) == 2.50
    assert out["voice_chars"] == 134_000  # every voice record, the jump's too


def test_cost_per_match_is_null_when_it_cannot_be_measured(tmp_path):
    from core.stats import stats

    store = Store(tmp_path)
    out = stats(store)  # no full replay yet
    assert (out["matches_measured"], out["cost_per_match_usd"], out["voice_chars"]) == (0, None, 0)
    store.append("replays", {"replay_id": "a", "match_id": "f1", "line_ids": ["la"]})
    line = {"model": "claude-haiku-4-5", "line_id": "la", "replay_id": "a", "tokens_in": 1000}
    store.append("lines", line)
    out = stats(store)  # no voice record: the voice part is unmeasured, so is the total
    assert out["model_cost_per_match_usd"] == 0.001
    assert out["voice_cost_per_match_usd"] is None and out["cost_per_match_usd"] is None
    store.append("voice", {"replay_id": "a", "model": "eleven_unknown", "chars": 10})
    assert stats(store)["voice_cost_per_match_usd"] is None  # a model with no known price


def test_a_full_replay_pays_for_every_line_it_said_cached_or_not(tmp_path):
    """A cached stat line keeps the replay_id of the replay that made it; a later full replay that
    says it again is still charged its cost, so the figure is what describing the match costs."""
    from core.stats import stats

    store = Store(tmp_path)
    first = {"model": "claude-haiku-4-5", "replay_id": "a", "tokens_in": 1_000_000, "tokens_out": 0}
    store.append("lines", {**first, "line_id": "l1"})  # $1.00
    store.append("lines", {**first, "line_id": "l2"})  # $1.00, cached and said again by b
    store.append("replays", {"replay_id": "a", "match_id": "f1", "line_ids": ["l1", "l2"]})
    store.append("lines", {**first, "line_id": "l3", "replay_id": "b"})  # $1.00
    store.append("replays", {"replay_id": "b", "match_id": "f1", "line_ids": ["l2", "l3"]})
    store.append("replays", {"replay_id": "old", "match_id": "f1"})  # before line_ids: unmeasured
    for rid in ("a", "b"):
        store.append("voice", {"replay_id": rid, "model": "eleven_v3", "chars": 1000})  # $0.08
    out = stats(store)
    assert out["matches_measured"] == 2
    assert round(out["model_cost_per_match_usd"], 2) == 2.00
    assert round(out["cost_per_match_usd"], 2) == 2.08
