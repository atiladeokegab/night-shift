"""#130: stat lines fill each quiet stretch of a video replay, from data up to the moment they
follow only, through the same commentator request as every line, and cached per match."""

import asyncio
import functools

import pytest

from agent import commentator
from agent.commentator import FakeProvider
from core import insight
from core.predict import load_pack
from core.replay import Replay, run_replay
from core.store import Store
from data.matches import load_moments, video_map

KOBE, CHELSEA = "0020500591", "3754092"


def replay(match_id, store, moments=None, video=True):
    fake = FakeProvider()
    r = Replay(match_id, 1e9)
    calls = functools.partial(commentator.commentate, provider=fake)
    moments = moments or load_moments(match_id)
    asyncio.run(run_replay(r, moments, calls, store, video_map(match_id) if video else None))
    assert not [e for e in r.events if e["event"] == "error"]
    return [e["data"] for e in r.events if e["event"] == "line"], fake


def stat_calls(fake):
    return [q for q in fake.requests if "\nEvent: Stat, " in q["messages"][0]["content"]]


def test_kobe_every_quiet_stretch_is_filled_at_the_spacing_without_repeats(tmp_path):
    store = Store(tmp_path)
    replay(KOBE, store)  # the first viewing stops at the cap; the second fills every stretch
    lines, _ = replay(KOBE, store)
    times = [m["video_t"] for m in video_map(KOBE)["moments"]]
    called = [ln for ln in lines if "insight" not in ln]
    assert [ln["video_t"] for ln in called] == times
    filled = 0
    for line, end in zip(called, times[1:], strict=False):
        after = [ln for ln in lines if ln.get("insight", {}).get("after_idx") == line["moment_idx"]]
        assert line["speaker"] == "lead"
        assert [ln["speaker"] for ln in after] == ["analyst", "lead"] * (len(after) // 2) + [
            "analyst"
        ] * (len(after) % 2)  # the analyst and the lead take turns
        t, said = line["video_t"], line["text"]
        for ln in after:  # each one due once the line before it has likely been spoken
            assert ln["video_t"] == pytest.approx(insight.due_after(t, said))
            assert ln["video_t"] <= end - insight.CLEAR_S
            t, said = ln["video_t"], ln["text"]
        assert insight.due_after(t, said) > end - insight.CLEAR_S, "the stretch was left quiet"
        filled += end - line["video_t"] >= 14
    assert filled >= 10
    details = [ln["insight"]["detail"] for ln in lines if "insight" in ln]
    assert len(details) == len(set(details)) > 100
    assert all(ln["text"] for ln in lines)  # FakeProvider calls a Stat moment like any other


def test_a_later_event_never_reaches_the_insights_before_it(tmp_path, monkeypatch):
    monkeypatch.setattr(insight, "MAX_CALLS", 1000)
    moments = load_moments(KOBE)
    k = next(i for i, m in enumerate(moments) if m["idx"] == 10)  # unmapped, between 9 and 11
    moments[k] = {
        **moments[k],
        "team": "Toronto Raptors",
        "players": {"shooter": "Planted Shooter"},
        "outcome": "3 points",
        "score": {"home": 990, "away": 991},
        "detail": {"player_points": 977},
    }
    lines, fake = replay(KOBE, Store(tmp_path), moments)
    planted = ("Planted", "990", "991", "977")
    before = [ln for ln in lines if ln.get("insight", {}).get("after_idx", 99) <= 9]
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    assert len(before) > 10 and len(asked) == len([ln for ln in lines if "insight" in ln])
    assert not any(p in ln["insight"]["detail"] for ln in before for p in planted)
    early = asked[: len(before)]
    assert not any(p in q for q in early for p in planted)
    # the probe can go red: once the planted event is past, the insights do use it
    later = [
        ln["insight"]["detail"] for ln in lines if ln.get("insight", {}).get("after_idx") == 11
    ]
    assert any("Planted Shooter" in d for d in later)


def test_an_insight_request_is_a_normal_line_request(tmp_path):
    _, fake = replay(CHELSEA, Store(tmp_path))
    stat = stat_calls(fake)[0]
    line = next(q for q in fake.requests if q not in stat_calls(fake))
    for key in ("model", "max_tokens", "system", "tools", "tool_choice", "metadata"):
        assert stat[key] == line[key], key
    assert stat["system"] == commentator.SYSTEM and stat["tools"] == commentator.TOOLS
    labels = [row.split(":")[0] for row in commentator.MESSAGE.splitlines()]
    for q in (stat, line):
        assert [row.split(":")[0] for row in q["messages"][0]["content"].splitlines()][:9] == (
            labels[:9]
        )


def test_each_insight_hears_the_line_before_it(tmp_path):
    lines, fake = replay(CHELSEA, Store(tmp_path))
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    heard = [prev["text"] for prev, ln in zip(lines, lines[1:], strict=False) if "insight" in ln]
    assert len(asked) == len(heard) > 0
    for q, before, ln in zip(asked, heard, [ln for ln in lines if "insight" in ln], strict=True):
        details = next(row for row in q.splitlines() if row.startswith("Details: "))
        assert f"speaker: {ln['speaker']}" in details and f"after: {before}" in details


def test_a_pack_match_cites_the_pack_and_one_without_uses_tonight_only(tmp_path):
    kobe, _ = replay(KOBE, Store(tmp_path / "kobe"))
    said = [ln["insight"] for ln in kobe if "insight" in ln]
    assert any("made 461 of 1036" in i["detail"] for i in said)  # Kobe's pre-match record
    assert {"player profile", "next to score"} <= {i["kind"] for i in said}
    assert load_pack("football", CHELSEA) is None
    chelsea, _ = replay(CHELSEA, Store(tmp_path / "chelsea"))
    said = [ln["insight"] for ln in chelsea if "insight" in ln]
    assert said and {i["kind"] for i in said} <= {"tally", "score story", "momentum"}
    assert not any("before tonight" in i["detail"] for i in said)


def test_a_second_replay_makes_no_new_insight_calls(tmp_path):
    store = Store(tmp_path)
    first, fake = replay(CHELSEA, store)
    assert 0 < len(stat_calls(fake)) < insight.MAX_CALLS
    again, fake = replay(CHELSEA, store)
    assert stat_calls(fake) == []
    ids = [ln["line_id"] for ln in first if "insight" in ln]
    assert [ln["line_id"] for ln in again if "insight" in ln] == ids
    assert len(store.all("lines")) == len(first) + len(again) - len(ids)  # nothing stored twice


def test_new_insight_calls_stop_at_the_cap(tmp_path):
    store = Store(tmp_path)
    counts = [len(stat_calls(replay(KOBE, store)[1])) for _ in range(3)]
    assert counts[0] == insight.MAX_CALLS == 120
    assert 0 < counts[1] <= insight.MAX_CALLS and counts[2] == 0  # Kobe needs a little over 120


def test_no_video_no_insights(tmp_path):
    lines, fake = replay(CHELSEA, Store(tmp_path), video=False)
    assert lines and stat_calls(fake) == [] and not any("insight" in ln for ln in lines)
    assert {ln["speaker"] for ln in lines} == {"lead"}
