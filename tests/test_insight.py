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
from core import insight, predict
from core.app import Deps, create_app
from core.predict import load_pack
from core.replay import Replay, run_replay
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments, match_header, video_map

KOBE, CHELSEA = "0020500591", "3754092"


class Fake(FakeProvider):
    """FakeProvider, its read-back cut to 7 words: an insight's Event is the whole stat."""

    def call(self, request):
        reply = super().call(request)
        for b in reply["content"]:
            if b["type"] == "text":
                b["text"] = " ".join(b["text"].split()[:7])
        return reply


def replay(match_id, store, moments=None, video=True, calls=None):
    fake = Fake()
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
    for i, m in enumerate(moments):
        if m["idx"] in (10, 21):  # unmapped, 10 between 9 and 11; two make a tally
            moments[i] = {
                **m,
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
        ln["insight"]["detail"] for ln in lines if ln.get("insight", {}).get("after_idx", 0) > 9
    ]
    assert any(p in d for d in later for p in planted)


def test_an_insight_request_has_the_analysts_prompt_and_a_lines_message(tmp_path):
    _, fake = replay(CHELSEA, Store(tmp_path))
    stat = stat_calls(fake)[0]
    line = next(q for q in fake.requests if q not in stat_calls(fake))
    for key in ("model", "max_tokens", "metadata"):
        assert stat[key] == line[key], key
    assert line["system"] == commentator.SYSTEM and line["tools"] == commentator.TOOLS
    # the analyst's own prompt and no tools, so the lines' frozen fingerprint stays one task
    assert (
        stat["system"] == commentator.ANALYST and "tools" not in stat and "tool_choice" not in stat
    )
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
        event = next(row for row in q.splitlines() if row.startswith("Event: "))
        if "insight" in ln:  # the stat is the Event; a reply's Event is what it heard
            assert event == f"Event: Stat, {ln['insight']['kind']}: {ln['insight']['detail']}"
        else:
            assert event.endswith(f"who just said: {prev['text']}")
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


def test_a_pack_stretch_opens_on_the_pack_and_one_moment_is_no_tally(tmp_path):
    lines, _ = replay(KOBE, Store(tmp_path))
    first = [ln["insight"]["kind"] for ln in lines if ln.get("insight", {}).get("n") == 0]
    assert first and set(first) <= {"player profile", "next to score"}
    one = load_moments(CHELSEA)[:1]
    assert insight._tallies(None, one) == [] and insight._tallies(None, one * 2)


def test_a_cricket_profile_is_the_part_for_the_players_role():
    moments = load_moments("1298150")
    k = next(i for i, m in enumerate(moments) if m["idx"] == 10)  # Iftikhar Ahmed bats, over 11
    pack = load_pack("cricket", "1298150")
    said = {d.split(" (")[0]: d for d in insight._profiles(pack, moments[: k + 1])}
    batter, bowler = (moments[k]["players"][r] for r in ("batter", "bowler"))
    assert "- Batting, middle:" in said[batter] and "Bowling" not in said[batter]
    assert "- Bowling:" in said[bowler] and "Batting" not in said[bowler]


def test_analyst_and_reply_lines_never_go_through_the_recorded_provider(tmp_path, monkeypatch):
    recorded, unrecorded = Fake(), Fake()
    monkeypatch.setattr(commentator, "default_provider", lambda: recorded)
    monkeypatch.setattr(commentator, "unrecorded_provider", lambda: unrecorded)
    lines, _ = replay(CHELSEA, Store(tmp_path), calls=commentator.commentate)
    said = next(ln for ln in lines if "insight" in ln)
    commentator.correct(said, "Fixed.", moments=insight.said_over(said, load_moments))

    def stats(fake):
        return {"\nEvent: Stat, " in q["messages"][0]["content"] for q in fake.requests}

    assert any("reply" in ln for ln in lines)
    assert stats(recorded) == {False} and stats(unrecorded) == {True}
    assert unrecorded.requests[-1]["messages"][-1]["content"].startswith("Producer correction")


def test_a_second_replay_makes_no_new_insight_calls(tmp_path):
    store = Store(tmp_path)
    first, fake = replay(CHELSEA, store)
    assert 0 < len(stat_calls(fake)) < insight.MAX_CALLS
    again, fake = replay(CHELSEA, store)
    assert stat_calls(fake) == []
    ids = [ln["line_id"] for ln in first if gap(ln)]
    assert [ln["line_id"] for ln in again if gap(ln)] == ids
    assert len(store.all("lines")) == len(first) + len(again) - len(ids)  # nothing stored twice


def test_insights_stored_before_v2_are_never_replayed(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(insight, "VERSION", 1)  # v1 re-called the play
    replay(CHELSEA, store)
    monkeypatch.setattr(insight, "VERSION", 2)
    _, fake = replay(CHELSEA, store)
    assert stat_calls(fake)


def test_the_stat_is_the_event_and_the_moments_shooter_stays_out():
    moments = load_moments(CHELSEA)
    k = next(i for i, m in enumerate(moments) if m["players"].get("shooter"))
    m, header = moments[k], match_header(CHELSEA)
    shooter = m["players"]["shooter"]
    said_as = {"kind": "tally", "detail": "Chelsea tonight: Shot (Off T) x3", "heard": "Close!"}
    for reply, event in ((False, "tally: Chelsea tonight: Shot (Off T) x3"), (True, None)):
        stat = insight.stat_moment(m, said_as, reply)
        assert stat["type"] == "Stat" and stat["players"] == {}
        assert stat["outcome"] == (event or "the lead answers the analyst, who just said: Close!")
        q = commentator.build_request(header, [*moments[: k + 1], stat])["messages"][0]["content"]
        rows = dict(row.split(": ", 1) for row in q.splitlines() if ": " in row)
        assert rows["Event"] == f"Stat, {stat['outcome']}"
        assert shooter not in rows["Event"] + rows["Players"] + rows["Details"]


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
    fake = Fake()
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
