"""#221: the lead and the analyst talk to each other: names from one constant, each analyst line
hears the line just said and who said it, and a cached cold open before the first call. The lead's
recorded moment prompt and tools never change."""

import asyncio
import functools
import hashlib
import json
import uuid

from agent import commentator
from core import insight
from core.replay import Replay, run_replay
from core.store import Store
from core.voice import NAMES
from data.matches import load_moments, match_header, video_map
from tests.test_insight import KOBE, Fake, stat_calls

WSL = "3913122"
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
    lines, fake, vmap = replay(KOBE, store)  # the bundled map: 25 s before the first call
    first_t, start = min(m["video_t"] for m in vmap["moments"]), vmap["start"]
    opened = [ln for ln in lines if "open" in ln]
    assert lines[: len(opened)] == opened  # before the first call
    assert [(ln["speaker"], ln["open"]["n"]) for ln in opened] == [("lead", 0), ("analyst", 1)]
    assert len(opens(fake)) == 2
    ends = [insight.due_after(ln["video_t"], ln["text"]) for ln in opened]
    assert opened[0]["video_t"] == start and ends[0] == opened[1]["video_t"]
    assert ends[-1] <= first_t  # a breath before the call
    assert sum(len(ln["text"].split()) / insight.WORDS_PER_S for ln in opened) <= insight.OPEN_S
    # the analyst hears the lead's welcome, by name
    q = opens(fake)[1]["messages"][0]["content"]
    assert f"{NAMES['lead']} just said: {opened[0]['text']}" in q
    # once per replay: a second viewing reuses both lines and makes no new call
    again, fake, _ = replay(KOBE, store)
    assert opens(fake) == []
    assert [ln["line_id"] for ln in again if "open" in ln] == [ln["line_id"] for ln in opened]
    assert sum("open" in ln for ln in store.all("lines")) == 2


def test_the_cold_open_never_runs_into_the_first_call(tmp_path):
    # a 10 s run-in, as a video that starts near its first call: the welcome fits, the analyst's
    # line would run into the call
    lines, fake, vmap = replay(KOBE, Store(tmp_path), start=480)
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
    lines, fake, _ = replay(KOBE, Store(tmp_path))
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


def twelve_words(moment, history):
    """A cold open line at the prompt's 12-word cap, else nothing: only the open is timed here."""
    if not moment["outcome"].startswith(insight.OPEN):
        return None
    return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": "word " * 12}


def test_which_videos_have_room_for_both_cold_open_lines(tmp_path):
    said = {}
    for match_id in ("0020500591", "0049700088", "1298150", "9636", "3754092", "3869685", WSL):
        r = Replay(match_id, 1e9)
        store = Store(tmp_path / match_id)
        asyncio.run(run_replay(r, load_moments(match_id), twelve_words, store, video_map(match_id)))
        said[match_id] = [e["data"]["speaker"] for e in r.events if e["event"] == "line"]
    both, jim = ["lead", "analyst"], ["lead"]
    # 25 s before the first call where the video has it; a video that opens on play has less
    assert said == {
        "0020500591": both,
        "0049700088": both,
        "3869685": both,
        WSL: both,  # the film's opening shot
        "1298150": jim,  # 9.0 s in
        "9636": jim,  # 9.9 s in
        "3754092": [],  # 6.3 s in: a 12-word welcome would run into the first call
    }


def test_the_ball_line_opening_a_stretch_hears_the_call_by_name(tmp_path):
    # #205's orientation line takes slot 0 of a football stretch: it picks up Jim's call too
    _, fake, _ = replay("3869685", Store(tmp_path))
    asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
    ball = [q for q in asked if "\nEvent: Stat, orientation: " in q]
    assert ball and all("speaker: analyst, you are: Julian" in q for q in ball)
    assert all(f"{NAMES['lead']} just said: " in q for q in ball)


def test_a_cold_open_with_no_numbers_passes_the_number_check(tmp_path):
    # build-149's check over each open line and the request it was said over: a welcome that
    # says no number passes; one that adds a number the match doesn't give is caught
    header = {}

    def welcome(moment, history):
        if not moment["outcome"].startswith(insight.OPEN):
            return None
        h = header["now"]
        match = f"{h['home']} against {h['away']}" if h.get("home") else h["stage"]
        text = (
            f"Welcome along, {match} in the {h['competition']}, with {NAMES['analyst']}."
            if moment["detail"]["speaker"] == "lead"
            else f"Great to be with you, {NAMES['lead']}, what a night for it."
        )
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

    checked = 0
    for match_id in ("0020500591", "0049700088", "1298150", "9636", "3869685", WSL):
        header["now"] = match_header(match_id)
        store = Store(tmp_path / match_id)
        r = Replay(match_id, 1e9)
        asyncio.run(run_replay(r, load_moments(match_id), welcome, store, video_map(match_id)))
        for line in (e["data"] for e in r.events if e["event"] == "line"):
            over = insight.said_over(line, load_moments)
            m, past = over[-1], over[:-1]
            assert insight.wrong_numbers(line["text"], m, header["now"], past) == [], line["text"]
            crowd = f"{line['text']} A crowd of 61,482 tonight."
            assert insight.wrong_numbers(crowd, m, header["now"], past), match_id
            checked += 1
    assert checked >= 8  # both lines on the four long run-ins, at least Jim on the rest


def test_an_open_line_with_a_number_the_match_doesnt_give_is_asked_once_more_then_dropped(
    tmp_path,
):
    asked = []

    def counting(text):
        def calls(moment, history):
            if not moment["outcome"].startswith(insight.OPEN):
                return None
            asked.append(moment["detail"]["speaker"])
            return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

        return calls

    def run(calls, store):
        r = Replay(WSL, 1e9)
        asyncio.run(run_replay(r, load_moments(WSL), calls, store, video_map(WSL)))
        return [e["data"] for e in r.events if e["event"] == "line" and "open" in e["data"]]

    store = Store(tmp_path)
    assert run(counting("Welcome, with 40000 here tonight."), store) == []
    assert asked == ["lead", "lead"]  # the welcome twice, then no open at all
    asked.clear()
    good = run(counting("Welcome to the Women's Super League."), store)
    assert [ln["speaker"] for ln in good] == ["lead", "analyst"] and all(
        ln["checked"] for ln in good
    )
    # a stored open line the check now fails is made again, never said
    stale = Store(tmp_path / "stale")
    for ln in store.all("lines"):
        stale.append(
            "lines", {**ln, "text": "Welcome, with 40000 here tonight."} if "open" in ln else ln
        )
    asked.clear()
    again = run(counting("Welcome to the Women's Super League."), stale)
    assert asked == ["lead", "analyst"] and "40000" not in " ".join(ln["text"] for ln in again)


KEYED = {  # the open of the keyed WSL run at 7f28aaa, where Julian's line was cut for time
    "lead": "Hello everyone, welcome to Brighton against Bristol City in the Women's Super League, "
    "Julian alongside me.",
    "analyst": "Good to be here with you, Jim, and it should be a lively afternoon.",
}


def test_wsl_hears_both_open_lines_at_a_real_lines_length(tmp_path):
    # 17 and 13 words: the welcome alone took 8.3 s with its breath, so a 15 s cap that counted
    # breaths cut Julian; the speech is 11.1 s, said in full a breath before the goal at 39 s
    def keyed(moment, history):
        if not moment["outcome"].startswith(insight.OPEN):
            return None
        text = KEYED[moment["detail"]["speaker"]]
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

    r = Replay(WSL, 1e9)
    asyncio.run(run_replay(r, load_moments(WSL), keyed, Store(tmp_path), video_map(WSL)))
    said = [e["data"] for e in r.events if e["event"] == "line"]
    assert [(ln["speaker"], ln["text"]) for ln in said] == list(KEYED.items())
    first_t = min(m["video_t"] for m in video_map(WSL)["moments"])
    assert insight.due_after(said[1]["video_t"], said[1]["text"]) <= first_t


class SameBridge(Fake):
    """Every analyst line opens "Right, Jim, and", as in the keyed WSL run at 7f28aaa, unless the
    request says which opener to avoid."""

    def call(self, request):
        reply = super().call(request)
        q = request["messages"][0]["content"]
        for b in reply["content"]:
            if b["type"] == "text" and "speaker: analyst," in q and "never open with: " not in q:
                b["text"] = f"Right, {NAMES['lead']}, and {b['text']}"
        return reply


def test_no_analyst_opener_repeats_within_a_match(tmp_path):
    for match_id in ("3869685", WSL, KOBE):
        fake = SameBridge()
        r = Replay(match_id, 1e9)
        calls = functools.partial(commentator.commentate, provider=fake)
        store = Store(tmp_path / match_id)
        asyncio.run(run_replay(r, load_moments(match_id), calls, store, video_map(match_id)))
        said = [e["data"] for e in r.events if e["event"] == "line"]
        # the data's own ball line (#205's fallback) is not the analyst's words
        analyst = [ln for ln in said if ln["speaker"] == "analyst" and not ln.get("fallback")]
        openers = [insight.opener(ln["text"]) for ln in analyst]
        assert len(analyst) > 5 and len(set(openers)) == len(openers), match_id
        # one line kept the bridge; the rest were asked again, told which opener to avoid
        assert sum(o == ("right", "jim", "and") for o in openers) == 1
        asked = [q["messages"][0]["content"] for q in stat_calls(fake)]
        assert any("never open with: right jim and" in q for q in asked)


def test_a_fix_on_the_kickoff_welcome_is_never_said_as_the_first_call(tmp_path):
    # a kickoff open is said over the first moment, so its lines carry that moment's idx (#232)
    store = Store(tmp_path)
    lines, _, _ = replay(CRICKET, store)
    welcome = next(ln for ln in lines if "open" in ln)
    first = load_moments(CRICKET)[0]["idx"]
    assert welcome["moment_idx"] == first and welcome["open"]["kickoff"]
    store.append("fixes", {"line_id": welcome["line_id"], "corrected_text": "Welcome, fixed."})
    again, _, _ = replay(CRICKET, store)
    call = next(ln for ln in again if "open" not in ln and ln["moment_idx"] == first)
    assert not call.get("fixed") and "Welcome, fixed." not in [ln["text"] for ln in again]
