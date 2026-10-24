"""#130: the analyst's stat lines, and now and then the lead's reply, fill each quiet stretch of a
video replay, from data up to the moment they follow only, through the same commentator request as
every line, and cached per match."""

import asyncio
import functools
import uuid

import pytest
from fastapi.testclient import TestClient

from agent import commentator
from agent.commentator import FakeProvider
from core import insight, predict, smoke
from core.app import Deps, create_app
from core.predict import load_pack
from core.replay import Replay, run_replay
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments, video_map

KOBE, CHELSEA = "0020500591", "3754092"


def replay(match_id, store, moments=None, video=True, calls=None):
    fake = FakeProvider()
    r = Replay(match_id, 1e9)
    calls = calls or functools.partial(commentator.commentate, provider=fake)
    moments = moments or load_moments(match_id)
    asyncio.run(run_replay(r, moments, calls, store, video_map(match_id) if video else None))
    assert not [e for e in r.events if e["event"] == "error"]
    return [e["data"] for e in r.events if e["event"] == "line"], fake


def stat_calls(fake):
    return [q for q in fake.requests if "\nEvent: Stat, " in q["messages"][0]["content"]]


def gap(ln):
    """The insight or reply key of a line in a quiet stretch, else {} for a moment's line."""
    return ln.get("insight") or ln.get("reply") or {}


class Sized:
    """A commentator whose lines are 14 words, about a real line's length (13 on average)."""

    def __init__(self):
        self.stats = 0

    def __call__(self, moment, history):
        self.stats += moment["type"] == "Stat"
        said = f"{moment['type']} {moment['idx']} " + "word " * 12
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": said.strip()}


def test_kobe_one_viewing_fills_every_quiet_stretch_at_the_spacing_without_repeats(tmp_path):
    store, sized = Store(tmp_path), Sized()
    lines, _ = replay(KOBE, store, calls=sized)
    assert 0 < sized.stats <= insight.MAX_CALLS
    times = [m["video_t"] for m in video_map(KOBE)["moments"]]
    called = [ln for ln in lines if not gap(ln)]
    assert [ln["video_t"] for ln in called] == times
    filled = 0
    for line, end in zip(called, times[1:], strict=False):
        after = [ln for ln in lines if gap(ln).get("after_idx") == line["moment_idx"]]
        assert line["speaker"] == "lead"
        assert [gap(ln)["n"] for ln in after] == list(range(len(after)))
        for n, ln in enumerate(after):  # the analyst, and every 4th line the lead's reply
            reply = n % insight.REPLY_EVERY == insight.REPLY_EVERY - 1
            assert ("reply" in ln, ln["speaker"]) == (reply, "lead" if reply else "analyst")
        t, said = line["video_t"], line["text"]
        for ln in after:  # each one due once the line before it has likely been spoken
            assert ln["video_t"] == pytest.approx(insight.due_after(t, said))
            assert ln["video_t"] <= end - insight.CLEAR_S
            t, said = ln["video_t"], ln["text"]
        assert insight.due_after(t, said) > end - insight.CLEAR_S, "the stretch was left quiet"
        filled += end - line["video_t"] >= 14
    assert filled >= 10
    details = [ln["insight"]["detail"] for ln in lines if "insight" in ln]
    assert len(details) == len(set(details)) > 60
    sized.stats = 0
    replay(KOBE, store, calls=sized)
    assert sized.stats == 0  # the second viewing is all cache


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
    before = [ln for ln in lines if gap(ln).get("after_idx", 99) <= 9]
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    assert len(before) > 10 and len(asked) == len([ln for ln in lines if gap(ln)])
    assert not any(p in gap(ln)["detail"] for ln in before for p in planted)
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


def test_each_insight_hears_the_line_before_it_and_the_lead_replies(tmp_path):
    lines, fake = replay(KOBE, Store(tmp_path))
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    pairs = [(prev, ln) for prev, ln in zip(lines, lines[1:], strict=False) if gap(ln)]
    assert len(asked) == len(pairs) > 0
    for q, (prev, ln) in zip(asked, pairs, strict=True):
        details = next(row for row in q.splitlines() if row.startswith("Details: "))
        assert f"speaker: {ln['speaker']}, Partner just said: {prev['text']}" in details
        assert ("stat: " in details) == ("insight" in ln)  # a reply brings no new number
    replies = [(prev, ln) for prev, ln in pairs if "reply" in ln]
    assert replies and all(prev["speaker"] == "analyst" for prev, _ in replies)
    assert {ln["speaker"] for ln in lines if "insight" in ln} == {"analyst"}
    assert {ln["speaker"] for ln in lines if not gap(ln)} == {"lead"}


def test_a_pack_match_cites_the_pack_and_one_without_uses_tonight_only(tmp_path, monkeypatch):
    kobe, _ = replay(KOBE, Store(tmp_path / "kobe"))
    said = [ln["insight"] for ln in kobe if "insight" in ln]
    assert any("made 461 of 1036" in i["detail"] for i in said)  # Kobe's pre-match record
    assert {"player profile", "next to score"} <= {i["kind"] for i in said}
    # Chelsea has a pack (#134): take it away to see a match without one
    assert load_pack("football", CHELSEA) is not None
    monkeypatch.setattr(predict, "load_pack", lambda sport, match_id: None)
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
    ids = [ln["line_id"] for ln in first if gap(ln)]
    assert [ln["line_id"] for ln in again if gap(ln)] == ids
    assert len(store.all("lines")) == len(first) + len(again) - len(ids)  # nothing stored twice


def test_new_insight_calls_stop_at_the_cap(tmp_path):
    store = Store(tmp_path)
    counts = [len(stat_calls(replay(KOBE, store)[1])) for _ in range(3)]
    assert counts[0] == insight.MAX_CALLS == 160
    # FakeProvider's 7-word lines leave room for more than 120 on Kobe: the second viewing tops up
    assert 0 < counts[1] <= insight.MAX_CALLS and counts[2] == 0


def test_no_video_no_insights(tmp_path):
    lines, fake = replay(CHELSEA, Store(tmp_path), video=False)
    assert lines and stat_calls(fake) == [] and not any(gap(ln) for ln in lines)
    assert {ln["speaker"] for ln in lines} == {"lead"}


def test_a_fix_on_an_insight_or_reply_goes_back_with_its_own_request(tmp_path):
    fake = FakeProvider()
    calls = functools.partial(commentator.commentate, provider=fake)
    fix = functools.partial(commentator.correct, provider=fake)
    deps = Deps(list_matches, load_moments, calls, video_map, fix)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": CHELSEA}).json()["replay_id"]
        lines = [d for n, d in read_stream(client, rid) if n == "line"]
        moment = next(ln for ln in lines if not gap(ln))
        picks = [
            moment,
            next(ln for ln in lines if "insight" in ln),
            next(ln for ln in lines if "reply" in ln),
        ]
        for ln in picks:
            said = len(fake.requests)
            assert (
                client.post(
                    f"/lines/{ln['line_id']}/fix", json={"corrected_text": "Fixed."}
                ).status_code
                == 200
            )
            q = fake.requests[said]["messages"]
            assert q[1:] == [
                {"role": "assistant", "content": ln["text"]},
                {"role": "user", "content": commentator.CORRECTION.format(text="Fixed.")},
            ]
            first = int(ln["mubit_request_ids"][0].removeprefix("fake-")) - 1
            assert q[0] == fake.requests[first]["messages"][0]  # the message the line came from
            assert ("\nEvent: Stat, " in q[0]["content"]) == bool(gap(ln))
            if gap(ln):
                assert f"Partner just said: {gap(ln)['heard']}" in q[0]["content"]


def test_the_live_smoke_passes_on_a_replay_that_reuses_stored_insight_lines(tmp_path, monkeypatch):
    # #149: the deployed smoke match already has stored insight lines; a replay streams them again
    # without storing them twice, so the store grows by fewer lines than were streamed
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    calls = functools.partial(commentator.commentate, provider=FakeProvider())
    app = create_app(store=Store(tmp_path), deps=Deps(list_matches, load_moments, calls, video_map))
    monkeypatch.setattr(smoke.httpx, "Client", lambda **_: TestClient(app))
    assert smoke.live("http://testserver") == 0
    assert smoke.live("http://testserver") == 0  # its insight lines come from the store


def test_the_live_smoke_fails_when_a_streamed_line_never_reached_the_store(tmp_path, monkeypatch):
    class Lossy(Store):  # every line append is lost
        def _write(self, kind, text):
            if kind != "lines":
                super()._write(kind, text)

    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    calls = functools.partial(commentator.commentate, provider=FakeProvider())
    app = create_app(store=Lossy(tmp_path), deps=Deps(list_matches, load_moments, calls, video_map))
    monkeypatch.setattr(smoke.httpx, "Client", lambda **_: TestClient(app))
    with pytest.raises(AssertionError, match="not in store"):
        smoke.live("http://testserver")
    assert TestClient(app).get("/lines/nope").status_code == 404
