"""#221: the lead and the analyst talk to each other: names from one constant, each analyst line
hears the line just said and who said it, and a cached cold open before the first call. The lead's
recorded moment prompt and tools never change."""

import asyncio
import functools
import hashlib
import json

from agent import commentator
from core import insight
from core.replay import Replay, run_replay
from core.store import Store
from core.voice import NAMES
from data.matches import load_moments, match_header, video_map
from tests.test_insight import KOBE, Fake, stat_calls

CRICKET = "1298150"  # its first mapped moment is its first: a wicket at 1.1, 1 for 1
OPEN_EVENT = f"\nEvent: Stat, {insight.OPEN}: "


def replay(match_id, store, start=None):
    fake = Fake()
    vmap = video_map(match_id)
    if start is not None:  # a longer run-in than the bundled maps give, so both lines fit
        vmap = {**vmap, "start": start}
    r = Replay(match_id, 1e9)
    calls = functools.partial(commentator.commentate, provider=fake)
    asyncio.run(run_replay(r, load_moments(match_id), calls, store, vmap))
    assert not [e for e in r.events if e["event"] == "error"]
    return [e["data"] for e in r.events if e["event"] == "line"], fake, vmap


def opens(fake):
    return [q for q in stat_calls(fake) if OPEN_EVENT in q["messages"][0]["content"]]


def test_the_leads_recorded_prompt_and_tools_are_byte_identical():
    # the Mubit task: the names and the two-hander live only in the unrecorded analyst path
    sha = {
        "prompt.md": "b987fc85b4c689a93aadbdedca16dcb6cc96c7c3902cbe28cc7b425214960c4e",
        "tools.json": "a08ff3069c2380654a1f965e5a6011a0b1aaf77c5cf9d70e81ccae461290e2f1",
    }
    for name, want in sha.items():
        assert hashlib.sha256((commentator.AGENT / name).read_bytes()).hexdigest() == want, name
    assert commentator.SYSTEM == (commentator.AGENT / "prompt.md").read_text(encoding="utf-8")
    assert commentator.TOOLS == json.loads((commentator.AGENT / "tools.json").read_text())
    assert not any(n in commentator.SYSTEM for n in NAMES.values())


def test_the_cold_open_is_said_once_before_the_first_call_then_cached(tmp_path):
    store = Store(tmp_path)
    lines, fake, vmap = replay(KOBE, store, start=470)
    first_t = min(m["video_t"] for m in vmap["moments"])
    opened = [ln for ln in lines if "open" in ln]
    assert lines[: len(opened)] == opened  # before the first call
    assert [(ln["speaker"], ln["open"]["n"]) for ln in opened] == [("lead", 0), ("analyst", 1)]
    assert len(opens(fake)) == 2
    ends = [insight.due_after(ln["video_t"], ln["text"]) for ln in opened]
    assert opened[0]["video_t"] == 470 and ends[0] == opened[1]["video_t"]
    assert ends[-1] <= min(first_t, 470 + insight.OPEN_S)  # a breath before the call, under 15 s
    # the analyst hears the lead's welcome, by name
    q = opens(fake)[1]["messages"][0]["content"]
    assert f"{NAMES['lead']} just said: {opened[0]['text']}" in q
    # once per replay: a second viewing reuses both lines and makes no new call
    again, fake, _ = replay(KOBE, store, start=470)
    assert opens(fake) == []
    assert [ln["line_id"] for ln in again if "open" in ln] == [ln["line_id"] for ln in opened]
    assert sum("open" in ln for ln in store.all("lines")) == 2


def test_the_cold_open_never_runs_into_the_first_call(tmp_path):
    # the bundled 10 s run-in: the welcome fits, the analyst's line would run into the call
    lines, fake, vmap = replay(KOBE, Store(tmp_path))
    first_t = min(m["video_t"] for m in vmap["moments"])
    opened = [ln for ln in lines if "open" in ln]
    assert [ln["speaker"] for ln in opened] == ["lead"]
    assert all(insight.due_after(ln["video_t"], ln["text"]) <= first_t for ln in opened)


def test_a_kickoff_cold_open_hears_nothing_of_the_first_moment(tmp_path):
    lines, fake, _ = replay(CRICKET, Store(tmp_path))
    first = load_moments(CRICKET)[0]
    q = opens(fake)[0]["messages"][0]["content"]
    rows = dict(row.split(": ", 1) for row in q.splitlines() if ": " in row)
    assert rows["Score after this moment"] == f"{first['team']} 0 for 0"
    assert "Recent play:\n- none yet" in q and first["outcome"] not in q
    # a producer's fix goes back with that same request, unrecorded
    line = next(ln for ln in lines if "open" in ln)
    over = insight.said_over(line, load_moments)
    header = match_header(CRICKET)
    assert commentator.build_request(header, over)["messages"][0]["content"] == q
    assert commentator.provider_for(over[-1]) is commentator.unrecorded_provider()


def test_the_names_come_from_one_constant(tmp_path, monkeypatch):
    assert not any(n in commentator.ANALYST for n in NAMES.values())  # the prompt says <partner>
    monkeypatch.setitem(NAMES, "lead", "Zed")
    monkeypatch.setitem(NAMES, "analyst", "Quinn")
    lines, fake, _ = replay(KOBE, Store(tmp_path), start=470)
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    analyst = [q for q in asked if "speaker: analyst," in q]
    lead = [q for q in asked if "speaker: lead," in q]
    assert analyst and all("you are: Quinn, partner: Zed, the lead" in q for q in analyst)
    assert lead and all("you are: Zed, partner: Quinn, the analyst" in q for q in lead)
    assert not any(n in q for q in asked for n in ("Jim", "Julian"))


def test_the_partners_name_is_asked_for_about_one_line_in_three(tmp_path):
    _, fake, _ = replay(KOBE, Store(tmp_path))
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    asked = [q for q in asked if OPEN_EVENT not in q]
    named = sum("call partner by name: yes" in q for q in asked)
    assert len(asked) > 10 and 0.2 <= named / len(asked) <= 0.5
