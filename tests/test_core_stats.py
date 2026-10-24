import pytest

from core.stats import stats
from core.store import Store


def line(i, model="claude-haiku-4-5", tokens_in=1000, tokens_out=20):
    return {"line_id": f"l{i}", "model": model, "tokens_in": tokens_in, "tokens_out": tokens_out}


def test_empty_store_has_no_cost_and_an_untrained_adapter(tmp_path):
    s = stats(Store(tmp_path))
    assert s["cost_per_line_usd"] is None
    assert s["adapter"] == {
        "status": "not_trained",
        "kept": None,
        "needed": 25,
        "agree": None,
        "total": None,
        "cost_measurable": False,
    }


def test_cost_per_line_is_tokens_times_list_price(tmp_path):
    store = Store(tmp_path)
    store.append("lines", line(1, tokens_in=1000, tokens_out=20))  # 0.001 + 0.0001
    store.append("lines", line(2, tokens_in=3000, tokens_out=60))  # 0.003 + 0.0003
    assert stats(store)["cost_per_line_usd"] == pytest.approx(0.0022)


def test_the_analysts_sonnet_lines_are_priced(tmp_path):
    store = Store(tmp_path)
    store.append("lines", line(1, model="claude-sonnet-5-5", tokens_in=1000, tokens_out=20))
    assert stats(store)["cost_per_line_usd"] == pytest.approx(0.0022)  # 0.002 + 0.0002


def test_lines_from_an_unpriced_model_are_left_out_of_cost(tmp_path):
    store = Store(tmp_path)
    store.append("lines", line(1, tokens_in=1000, tokens_out=20))
    store.append("lines", line(2, model="fake"))
    assert stats(store)["cost_per_line_usd"] == pytest.approx(0.0011)
    store2 = Store(tmp_path / "b")
    store2.append("lines", line(1, model="fake"))
    assert stats(store2)["cost_per_line_usd"] is None


def test_stored_lines_are_not_reported_as_kept(tmp_path):
    # a stored line doesn't prove Mubit kept it; kept stays unknown until a count is recorded
    store = Store(tmp_path)
    for i in range(30):
        store.append("lines", line(i))
    assert stats(store)["adapter"]["kept"] is None


def test_adapter_reads_the_latest_recorded_result(tmp_path):
    store = Store(tmp_path)
    store.append("lines", line(1))
    store.append("adapter", {"status": "training", "kept": 25})
    store.append("adapter", {"status": "ready", "kept": 31, "agree": 23, "total": 25})
    assert stats(store)["adapter"] == {
        "status": "ready",
        "kept": 31,
        "needed": 25,
        "agree": 23,
        "total": 25,
        "cost_measurable": False,
    }


def test_lead_and_analyst_lines_are_reported_apart(tmp_path):
    # #161: one line count, p95 and cost mixed Haiku's calls with Sonnet's stat lines
    store = Store(tmp_path)
    store.append("lines", {**line(1), "first_word_ms": 500, "speaker": "lead"})
    store.append("lines", {**line(2), "first_word_ms": 700})  # older lines carry no speaker
    store.append(
        "lines", {**line(3, model="claude-sonnet-5-5"), "first_word_ms": 2000, "speaker": "analyst"}
    )
    lead, analyst = stats(store)["by_speaker"]["lead"], stats(store)["by_speaker"]["analyst"]
    assert lead["model"] == "claude-haiku-4-5" and lead["lines"] == 2
    assert lead["first_word_ms_p95"] == 700 and lead["cost_per_line_usd"] == pytest.approx(0.0011)
    assert analyst == {
        "model": "claude-sonnet-5-5",
        "lines": 1,
        "first_word_ms_p50": 2000,
        "first_word_ms_p95": 2000,
        "cost_per_line_usd": pytest.approx(0.0022),  # 0.002 + 0.0002
    }


def test_moment_to_audio_counts_only_lines_with_audio(tmp_path, monkeypatch):
    # #233: a voice that takes 50 ms; a second line it never voices is left out, not counted as 0
    import asyncio

    import httpx

    from core.replay import Replay, run_replay
    from core.voice import Speaker

    async def slow_voice(request):
        await asyncio.sleep(0.05)
        silent = b"no audio" in request.content
        return httpx.Response(500 if silent else 200, content=b"mp3")

    def commentate(moment, history):
        text = "Shot!" if moment["idx"] == 0 else "no audio"
        return {"line_id": f"f1-{moment['idx']}", "text": text, "model": "claude-haiku-4-5"}

    monkeypatch.setenv("ELEVENLABS_API_KEY", "fake-eleven")
    moments = [
        {"sport": "football", "match_id": "f1", "idx": i, "clock": c, "type": "Shot"}
        for i, c in enumerate(["03:10", "03:11"])
    ]
    store = Store(tmp_path)
    speaker = Speaker(httpx.MockTransport(slow_voice), store)

    async def run():
        await run_replay(Replay("f1", speed=1e6), moments, commentate, store, None, speaker.prepare)
        await asyncio.gather(*speaker.jobs.values())

    asyncio.run(run())
    lead = stats(store)["by_speaker"]["lead"]
    assert lead["lines"] == 2 and lead["audio_lines"] == 1
    assert lead["audio_first_ms_p50"] >= 50 and lead["audio_first_ms_p95"] >= 50


def fix(line_id, at, recorded=True):
    return {"line_id": line_id, "created_at": f"2026-10-24T{at}:00:00+00:00", "recorded": recorded}


def test_fixes_toward_the_next_adapter_count_since_its_latest_record(tmp_path):
    store = Store(tmp_path)
    store.append("fixes", fix("a", "12"))
    assert stats(store)["fixes_toward_next"] == 1  # no adapter yet: every recorded fix counts
    store.append("adapter", {"status": "training", "created_at": "2026-10-24T13:00:00+00:00"})
    store.append("fixes", fix("b", "14"))
    assert stats(store)["fixes_recorded"] == 2 and stats(store)["fixes_toward_next"] == 1
    # another task's adapter record isn't commentary's: the count toward the next one runs on
    store.append(
        "adapter",
        {"task": "line_check", "status": "ready", "created_at": "2026-10-24T15:00:00+00:00"},
    )
    assert stats(store)["fixes_toward_next"] == 1


def test_only_recorded_fixes_count_as_recorded(tmp_path):
    # a fix to an analyst line goes out unrecorded; one stored before #161 carries no flag
    store = Store(tmp_path)
    store.append("fixes", fix("lead", "12"))
    store.append("fixes", fix("analyst", "12", recorded=False))
    store.append("fixes", {"line_id": "old", "created_at": "2026-10-24T11:00:00+00:00"})
    s = stats(store)
    assert s["fixes"] == 3 and s["fixes_recorded"] == 1 and s["fixes_toward_next"] == 1


def test_with_no_owners_key_no_fix_counts_as_recorded(tmp_path):
    store = Store(tmp_path)
    store.append("fixes", fix("lead", "12", recorded=False))
    assert stats(store)["fixes_recorded"] == 0 and stats(store)["fixes_toward_next"] == 0
