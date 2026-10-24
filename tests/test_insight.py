"""#130: the analyst's stat lines, and now and then the lead's reply, fill each quiet stretch of a
video replay, from data up to the moment they follow only, through the analyst's own request
(a line's message, agent/analyst.md, never recorded), and cached per match."""

import asyncio
import functools
import itertools
import json
import uuid
from collections import Counter

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
from core.voice import NAMES
from data.matches import (
    balls,
    list_matches,
    load_moments,
    match_header,
    orientation,
    video_map,
)

KOBE, CHELSEA = "0020500591", "3754092"


def letters(n: int) -> str:
    """A word of its own for each n, so no two fake lines nearly repeat each other."""
    return "x" + "".join(chr(97 + int(d)) for d in str(n))  # "x": never a stop word like "be"


CALLS = itertools.count()  # across Fakes: a new viewing's lines never open like the cached ones


class Fake(FakeProvider):
    """FakeProvider, its read-back swapped for 7 copies of a word new to each call: an insight's
    Event reads back the whole stat, and stretch lines that repeat one another are dropped."""

    def call(self, request):
        reply = super().call(request)
        word = letters(next(CALLS))
        for b in reply["content"]:
            if b["type"] == "text":
                b["text"] = " ".join([word] * 7)
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
    """The insight, reply or cold open key of a line between moments, else {} for a moment's
    line."""
    return ln.get("insight") or ln.get("reply") or ln.get("open") or {}


class Sized:
    """A commentator whose lines are 14 words, about a real line's length (13 on average), and say
    no number: an analyst line with one the stat doesn't give is dropped."""

    def __init__(self):
        self.stats = 0

    def __call__(self, moment, history):
        self.stats += moment["type"] == "Stat"
        # "i" keeps the moment's word apart from the count's, so no two lines nearly repeat
        said = f"{moment['type']} i{letters(moment['idx'])} " + f"{letters(self.stats)} " * 12
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": said.strip()}


def test_kobe_one_viewing_fills_each_quiet_stretch_up_to_the_cap_without_repeats(tmp_path):
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
        assert len(after) <= insight.PER_GAP  # two analyst lines a gap, then the reply (#162)
        for n, ln in enumerate(after):  # the analyst, and every 3rd line the lead's reply
            reply = n % insight.REPLY_EVERY == insight.REPLY_EVERY - 1
            assert ("reply" in ln, ln["speaker"]) == (reply, "lead" if reply else "analyst")
        t, said = line["video_t"], line["text"]
        for ln in after:  # each one due once the line before it has likely been spoken
            assert ln["video_t"] == pytest.approx(insight.due_after(t, said))
            assert ln["video_t"] <= end - insight.CLEAR_S
            t, said = ln["video_t"], ln["text"]
        full = len(after) == insight.PER_GAP
        assert full or insight.due_after(t, said) > end - insight.CLEAR_S, "left quiet"
        filled += full
    assert filled >= 10
    details = [ln["insight"]["detail"] for ln in lines if "insight" in ln]
    assert len(details) == len(set(details)) >= 25
    assert len({ln["insight"]["kind"] for ln in lines if "insight" in ln}) >= 4  # all kinds
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
    # the probe can go red: once the planted event is past, the insight requests do hear it
    assert any(p in q for q in asked[len(before) :] for p in planted)


def test_an_insight_request_has_the_analysts_prompt_and_a_lines_message(tmp_path):
    _, fake = replay(CHELSEA, Store(tmp_path))
    stat = stat_calls(fake)[0]
    line = next(q for q in fake.requests if q not in stat_calls(fake))
    for key in ("max_tokens", "metadata"):
        assert stat[key] == line[key], key
    assert (stat["model"], line["model"]) == (commentator.ANALYST_MODEL, commentator.MODEL)
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
    asked = [q for q in asked if f"\nEvent: Stat, {insight.OPEN}: " not in q]
    pairs = [
        (prev, ln)
        for prev, ln in zip(lines, lines[1:], strict=False)
        if gap(ln) and "open" not in ln
    ]
    assert len(asked) == len(pairs) > 0
    for q, (prev, ln) in zip(asked, pairs, strict=True):
        details = next(row for row in q.splitlines() if row.startswith("Details: "))
        # the line just said, by whoever said it: the lead's call opens each stretch (#221)
        assert details.startswith(f"Details: speaker: {ln['speaker']}, ")
        assert details.endswith(f"{NAMES[prev['speaker']]} just said: {prev['text']}")
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
    tonight = {"tally", "score story", "momentum", "orientation"}  # and the ball (#205)
    assert said and {i["kind"] for i in said} <= tonight
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
    facts = insight._profiles(pack, moments[: k + 1])
    batter, bowler = (moments[k]["players"][r] for r in ("batter", "bowler"))
    bats = [d for d in facts if d.startswith(batter)]
    bowls = [d for d in facts if d.startswith(bowler)]
    assert bats and all(d.startswith(f"{batter} batting ") for d in bats)
    assert bats[1].startswith(
        f"{batter} batting in the middle overs in T20 internationals this year before tonight: "
    )
    assert bowls and all(d.startswith(f"{bowler} bowling ") for d in bowls)


def test_a_profile_is_one_short_fact_at_a_time():
    for sport, match_id in (("football", "3869685"), ("basketball", KOBE), ("f1", "9636")):
        moments = load_moments(match_id)
        facts = insight._profiles(load_pack(sport, match_id), moments[:8])
        assert facts and all(d.count(".") <= 2 and len(d.split()) <= 20 for d in facts), sport


def test_every_pre_match_fact_names_its_period():
    for sport, match_id, period in (
        ("football", "3869685", "at this World Cup before tonight"),
        ("football", CHELSEA, "this season before tonight"),
        ("basketball", KOBE, "this season before tonight"),
        ("f1", "9636", "this season before tonight"),
        ("cricket", "1298150", "in T20 internationals this year before tonight"),
    ):
        moments = load_moments(match_id)
        facts = insight._profiles(load_pack(sport, match_id), moments[: len(moments) // 2])
        tonight = [d for d in facts if "tonight" in d and "before tonight" not in d]
        assert len(tonight) < len(facts), (sport, match_id)
        assert all(period in d for d in facts if d not in tonight), (sport, match_id)


def test_a_profile_never_reads_a_match_clock_as_an_over():
    for sport, match_id in (("football", "3869685"), ("basketball", KOBE), ("cricket", "1298150")):
        moments = load_moments(match_id)[:5]
        past = moments[:-1] + [{**moments[-1], "clock": "16:15"}]
        assert insight._profiles(load_pack(sport, match_id), past), sport


@pytest.mark.parametrize("env", [None, "claude-sonnet-test"])
def test_the_analyst_model_is_a_setting_and_the_lines_model_never_moves(tmp_path, monkeypatch, env):
    if env:
        monkeypatch.setenv("ANALYST_MODEL", env)
    else:
        monkeypatch.delenv("ANALYST_MODEL", raising=False)
    want = env or "claude-sonnet-5-5"
    lines, fake = replay(CHELSEA, Store(tmp_path))
    stats = stat_calls(fake)
    assert stats and {q["model"] for q in stats} == {want}
    assert {q["model"] for q in fake.requests if q not in stats} == {"claude-haiku-4-5"}
    assert {ln["model"] for ln in lines if gap(ln)} == {want}


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-haiku-4-5"])
def test_only_a_sonnet_stat_request_turns_thinking_down(tmp_path, monkeypatch, model):
    monkeypatch.setenv("ANALYST_MODEL", model)
    _, fake = replay(CHELSEA, Store(tmp_path))
    stats = stat_calls(fake)
    want = [{"type": "between_tools"}] if model == "claude-sonnet-5-5" else [None]
    assert stats and [q.get("thinking") for q in stats] == want * len(stats)
    frozen = {
        "model": commentator.MODEL,
        "max_tokens": commentator.MAX_TOKENS,
        "system": commentator.SYSTEM,
        "tools": commentator.TOOLS,
        "tool_choice": commentator.TOOL_CHOICE,
    }
    moments = [q for q in fake.requests if q not in stats]
    assert moments  # each one is exactly a line's request: the frozen parts, byte for byte
    for q in moments:
        assert set(q) == {*frozen, "metadata", "messages"}
        assert json.dumps({k: q[k] for k in frozen}) == json.dumps(frozen)


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


def test_a_dropped_analyst_line_hands_its_slot_to_the_next_kind_once(tmp_path):
    fake, asked = Fake(), []

    def calls(moment, history, drop="player profile"):
        if moment["type"] == "Stat" and not moment["outcome"].startswith(insight.OPEN):
            asked.append((moment["idx"], moment["outcome"]))
        if moment["outcome"].startswith(drop):
            return None  # the line filter dropped it
        return commentator.commentate(moment, history, provider=fake)

    lines, _ = replay(KOBE, Store(tmp_path / "some"), calls=calls)
    first = [ln["insight"]["kind"] for ln in lines if ln.get("insight", {}).get("n") == 0]
    assert first and "player profile" not in first
    assert any(o.startswith("player profile") for _, o in asked)
    # every line dropped: each stretch spends at most two calls, then falls quiet
    asked.clear()
    lines, _ = replay(KOBE, Store(tmp_path / "all"), calls=functools.partial(calls, drop=""))
    assert not any(gap(ln) for ln in lines)
    per_stretch = Counter(idx for idx, _ in asked)
    assert per_stretch and set(per_stretch.values()) == {2}


GOAL = "GOAL! Cole Palmer slots it home, and it's 1-0!"  # Chelsea never lead this game


def test_the_analyst_never_restates_the_leads_call(tmp_path):
    fake, opened = Fake(), set()

    def calls(moment, history):
        if moment["type"] != "Stat":
            return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": GOAL}
        # each stretch opens on the real repeat shape (the cold open hears no call to repeat)
        if moment["idx"] not in opened and not moment["outcome"].startswith(insight.OPEN):
            opened.add(moment["idx"])
            return {
                "line_id": uuid.uuid4().hex,
                "moment_idx": moment["idx"],
                "text": "Palmer scores, and it's 1-0.",
            }
        return commentator.commentate(moment, history, provider=fake)

    store = Store(tmp_path)
    lines, _ = replay(CHELSEA, store, calls=calls)
    assert opened and all(ln["text"] != "Palmer scores, and it's 1-0." for ln in lines)
    assert [ln["text"] for ln in store.all("lines")] == [ln["text"] for ln in lines]
    # a moment's own line is always said (where 1-0 is the wrong score, the number check's)
    assert sum(not gap(ln) for ln in lines) == len(video_map(CHELSEA)["moments"])
    assert any("insight" in ln for ln in lines)  # the next kind took the slot


@pytest.mark.parametrize(
    ("line", "repeat"),
    [
        ("Palmer scores, and it's 1-0.", True),
        ("Palmer finds the net, Chelsea 1-0 up.", True),
        (GOAL, True),
        ("Cole Palmer this season before tonight: 5 goals from 20 shots.", False),
        ("Chance Palmer scores the next Chelsea goal: 18%.", False),
        ("Chelsea tonight: 4 shots, 2 on target.", False),
    ],
)
def test_a_line_repeats_the_call_unless_it_adds_a_fact(line, repeat):
    assert insight.repeats(line, [GOAL]) is repeat


@pytest.mark.parametrize(
    ("line", "before"),
    [
        ("Palmer tonight: 3 shots, 1 goal.", "Palmer tonight: 2 shots, 1 goal."),
        ("Ocon up to P5 now, three places gained.", "Ocon up to P8 now, three places gained."),
    ],
)
def test_an_updated_stat_is_a_new_fact(line, before):
    assert insight.repeats(before, [before]) and not insight.repeats(line, [before])
    assert not insight.repeats(line, [GOAL, "a", "b", "c"])  # only the last 3 lines count


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


def test_new_insight_calls_stop_at_the_cap(tmp_path, monkeypatch):
    # three lines a gap keep Kobe well under 160 calls, so a lower cap shows it still holds
    monkeypatch.setattr(insight, "MAX_CALLS", 20)
    store = Store(tmp_path)
    counts = [len(stat_calls(replay(KOBE, store)[1])) for _ in range(4)]
    # each viewing tops up the stretches the one before left quiet, until all are cached
    assert counts[0] == counts[1] == 20 and 0 < counts[2] <= 20 and counts[3] == 0


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
                assert f" just said: {gap(ln)['heard']}" in q[0]["content"]


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


FINAL = "3869685"  # the 2022 World Cup final


def ball_line(match_id: str, i: int) -> str | None:
    """The plain orientation sentence for the gap after moments[i], if there is a ball."""
    moments, header = load_moments(match_id), match_header(match_id)
    b = balls(match_id).get(moments[i]["idx"])
    return orientation(header, moments[: i + 1], b) if b else None


def seconds(period, clock):
    minute, second = (int(x) for x in clock.split(":"))
    return period, minute * 60 + second


def test_a_football_stretch_opens_on_who_has_the_ball_then_the_pack(tmp_path):
    lines, _ = replay(FINAL, Store(tmp_path))
    at = {m["idx"]: i for i, m in enumerate(load_moments(FINAL))}
    opened = 0
    for ln in lines:
        said_as = ln.get("insight") or {}
        if said_as.get("n") not in (0, 1):
            continue
        ball = ball_line(FINAL, at[said_as["after_idx"]])
        assert ln["speaker"] == "analyst"
        if said_as["n"] == 0:  # the ball where the data has it, never anywhere else
            assert (said_as["kind"] == "orientation") == bool(ball)
            assert said_as["detail"] == ball or not ball
            opened += bool(ball)
        elif ball:  # then the stretch's first stat, from the pre-match pack
            assert said_as["kind"] in ("player profile", "next to score")
    assert opened >= 5


def test_an_orientation_line_is_said_at_the_balls_time_and_no_moment_carries_it(tmp_path):
    """A-1.4: an orientation line's time is the latest feed time it reads, after the moment it
    follows and before the next; no published moment carries the ball."""
    r, fake = Replay(FINAL, 1e9), Fake()
    calls = functools.partial(commentator.commentate, provider=fake)
    moments = load_moments(FINAL)
    asyncio.run(run_replay(r, moments, calls, Store(tmp_path), video_map(FINAL)))
    published = [e["data"] for e in r.events if e["event"] == "moment"]
    assert published and not any("ball" in m for m in published)
    found, nxt = balls(FINAL), dict(zip([m["idx"] for m in moments], moments[1:], strict=False))
    said = [m for m in published if str(m.get("outcome", "")).startswith("orientation")]
    assert len(said) >= 5
    for m in said:
        b = found[m["idx"]]
        assert m["clock"] == b["clock"]  # its time is the ball's, the latest it reads
        here = seconds(m["period"], m["clock"])
        assert seconds(m["period"], moments[m["idx"]]["clock"]) < here  # after its moment
        if m["idx"] in nxt:  # and before the next one
            assert here < seconds(nxt[m["idx"]]["period"], nxt[m["idx"]]["clock"])


def test_the_ball_after_messis_penalty_is_said_with_the_score_it_made():
    assert load_moments(FINAL)[5]["outcome"] == "Goal"
    assert ball_line(FINAL, 5) == (
        "France have the ball in Argentina's half, attacking Argentina's goal. Argentina lead 1-0."
    )
    assert ball_line(FINAL, 3) == (  # idx 3: no goal, no score
        "France have the ball inside their own box, attacking Argentina's goal."
    )


@pytest.mark.parametrize("match_id", [FINAL, "3913122"])
def test_every_orientation_sentence_passes_the_checks(match_id):
    moments, header = load_moments(match_id), match_header(match_id)
    said = 0
    for i, m in enumerate(moments):
        if text := ball_line(match_id, i):
            b = balls(match_id)[m["idx"]]
            said_as = {"kind": "orientation", "detail": text, "heard": "", "clock": b["clock"]}
            assert insight.wrong_orientation(text, m, said_as, header, moments[: i + 1]) == []
            said += 1
    assert said >= 10


@pytest.mark.parametrize(
    "wrong",
    [
        "Messi scores again, and France are on the back foot!",  # no goal in open play
        "France have the ball, three goals down.",  # no number the moment gives
        "France lead and they have the ball.",  # Argentina lead 1-0
        "France have the ball and they're looking to get it wide.",  # not in the data
        "France'll push forward from their own half.",
    ],
)
def test_an_orientation_line_that_gets_it_wrong_says_the_ball_instead(tmp_path, wrong):
    def calls(moment, history):
        line = commentator.commentate(moment, history, provider=FakeProvider())
        if moment["outcome"].startswith("orientation") and moment["idx"] == 5:
            line["text"] = wrong
        return line and {**line, "served_by": "adapter-test"}

    lines, _ = replay(FINAL, Store(tmp_path), calls=calls)
    after = [
        ln for ln in lines if gap(ln).get("kind") == "orientation" and gap(ln)["after_idx"] == 5
    ]
    assert after, "the gap after Messi's penalty opens on the ball"
    assert after[0]["text"] == after[0]["insight"]["detail"] and after[0]["fallback"] is True
    assert after[0]["served_by"] is None  # #250: the data's ball line, not the rejected model's


def test_a_stretch_stored_before_the_ball_now_opens_on_it(tmp_path, monkeypatch):
    store = Store(tmp_path)
    with monkeypatch.context() as before:  # stored before #205: every stretch opens on a stat
        before.setattr(insight.Gaps, "balls", lambda self: {})
        replay(FINAL, store)
    lines, _ = replay(FINAL, store)
    first = [ln["insight"]["kind"] for ln in lines if ln.get("insight", {}).get("n") == 0]
    assert "orientation" in first


def test_a_wsl_side_has_the_ball_without_its_wfc():
    assert ball_line("3913122", 8) == (
        "Bristol City have the ball in Brighton & Hove Albion's half, attacking Brighton & Hove "
        "Albion's goal. Brighton & Hove Albion lead 1-0."
    )


def test_a_dropped_orientation_hands_its_slot_to_a_stat_at_the_moments_time(tmp_path):
    fake = Fake()

    def calls(moment, history):
        if moment["outcome"].startswith("orientation") and moment["idx"] == 5:
            return None  # the line filter dropped it
        return commentator.commentate(moment, history, provider=fake)

    lines, _ = replay(FINAL, Store(tmp_path), calls=calls)
    [first] = [ln for ln in lines if gap(ln).get("after_idx") == 5 and gap(ln)["n"] == 0]
    assert first["insight"]["kind"] != "orientation"
    stat = insight.said_over(first, load_moments)[-1]
    assert stat["clock"] == load_moments(FINAL)[5]["clock"] == "22:24"


def test_the_ball_is_said_again_though_it_reads_like_the_last_ball_line(tmp_path):
    # the fake reads the stat back, "Stat, orientation: France have the ball ...", so ball lines
    # read alike; each is still where the ball is now, so each gap with a ball opens on it
    calls = functools.partial(commentator.commentate, provider=FakeProvider())
    lines, _ = replay(FINAL, Store(tmp_path), calls=calls)
    first = {
        gap(ln)["after_idx"]: gap(ln)["kind"]
        for ln in lines
        if gap(ln).get("n") == 0 and "open" not in ln  # the cold open shares its after_idx
    }
    with_ball = [idx for idx in first if idx in balls(FINAL)]
    assert len(with_ball) >= 5 and {first[idx] for idx in with_ball} == {"orientation"}
