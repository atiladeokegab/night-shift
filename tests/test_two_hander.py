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
from tests.test_insight import CHELSEA, KOBE, Fake, stat_calls

WSL = "3913122"
CRICKET = "1298150"  # its first mapped moment is its first: a wicket at 1.1, 1 for 1
OPEN_EVENT = f"\nEvent: Stat, {insight.OPEN}: "


def replay(match_id, store, start=None):
    fake = Fake()
    vmap = video_map(match_id)
    if start is not None:  # a different run-in than the bundled maps give
        vmap = {**vmap, "start": start}
    r = Replay(match_id, 1e9)
    calls = functools.partial(commentator.commentate, provider=fake)
    asyncio.run(run_replay(r, load_moments(match_id), calls, store, vmap))
    assert not [e for e in r.events if e["event"] == "error"]
    return [e["data"] for e in r.events if e["event"] == "line"], fake, vmap


def before_first(lines, store):
    """The lines said before the first call, each with its video time from the store: the
    welcome goes out untimed (#297)."""
    stored = {ln["line_id"]: ln for ln in store.all("lines")}
    out = []
    for ln in lines:
        if not (ln.get("open") or ln.get("insight") or ln.get("reply")):
            break
        out.append({**ln, "video_t": ln.get("video_t", stored[ln["line_id"]]["video_t"])})
    return out


def opens(fake):
    return [q for q in stat_calls(fake) if OPEN_EVENT in q["messages"][0]["content"]]


def test_the_leads_recorded_prompt_and_tools_are_byte_identical():
    # the Mubit task: the names and the two-hander live only in the unrecorded analyst path
    sha = {
        "prompt.md": "8471d0222c81ff72a6b2b89fa0a8bb61e11ae6a73f1067b3c5010dd1229cfecc",
        "tools.json": "a08ff3069c2380654a1f965e5a6011a0b1aaf77c5cf9d70e81ccae461290e2f1",
    }
    for name, want in sha.items():
        assert hashlib.sha256((commentator.AGENT / name).read_bytes()).hexdigest() == want, name
    assert commentator.SYSTEM == (commentator.AGENT / "prompt.md").read_text(encoding="utf-8")
    assert commentator.TOOLS == json.loads((commentator.AGENT / "tools.json").read_text())
    assert not any(n in commentator.SYSTEM for n in NAMES.values())


def test_the_cold_open_is_said_once_before_the_first_call_then_cached(tmp_path):
    store = Store(tmp_path)
    lines, fake, vmap = replay(KOBE, store)  # the bundled map: 12 s before the first call
    first_t, start = min(m["video_t"] for m in vmap["moments"]), vmap["start"]
    opened = [ln for ln in lines if "open" in ln]
    # the lead's welcome, untimed so it plays at once (#297), then a stretch over the moments
    # before the first call: the analyst's fact, and on, voice after voice
    assert [(ln["speaker"], ln["open"]["n"]) for ln in opened] == [("lead", 0)]
    assert lines[0] == opened[0] and "video_t" not in opened[0]
    said = before_first(lines, store)
    assert said[0]["video_t"] == start and len(said) >= 4
    assert [ln["speaker"] for ln in said] == (["lead", "analyst"] * len(said))[: len(said)]
    fact = said[1]["insight"]
    assert fact["kind"] in insight.ANGLES and fact["heard"] == said[0]["text"]
    for prev, ln in zip(said, said[1:], strict=False):
        assert ln["video_t"] == insight.due_after(prev["video_t"], prev["text"], insight.TURN_S)
    assert insight.due_after(said[-1]["video_t"], said[-1]["text"], 0) <= first_t - insight.TURN_S
    assert len(opens(fake)) == 1
    # the analyst hears the lead's welcome, by name
    q = next(
        q for q in stat_calls(fake) if f"Stat, {fact['kind']}: " in q["messages"][0]["content"]
    )
    assert f"{NAMES['lead']} just said: {opened[0]['text']}" in q["messages"][0]["content"]
    # once per replay: a second viewing reuses the open's lines and asks for none of them again
    again, fake, _ = replay(KOBE, store)
    assert opens(fake) == []
    assert not [
        q for q in stat_calls(fake) if any(ln["text"] in q["messages"][0]["content"] for ln in said)
    ]
    assert [ln["line_id"] for ln in before_first(again, store)] == [ln["line_id"] for ln in said]
    assert sum("open" in ln for ln in store.all("lines")) == 1


def test_the_cold_open_fits_a_welcome_before_a_first_call_at_six_seconds(tmp_path):
    # 3754092's first call is 6.3 s in: a breath counted into the welcome's own length dropped
    # it, and the page said nothing for the first 22.7 s (#297)
    store = Store(tmp_path)
    lines, fake, vmap = replay(CHELSEA, store)
    first_t = min(m["video_t"] for m in vmap["moments"])
    said = before_first(lines, store)
    assert said and said[0]["speaker"] == "lead" and "open" in said[0]
    assert all(
        insight.due_after(ln["video_t"], ln["text"], 0) <= first_t - insight.TURN_S for ln in said
    )


def test_the_cold_open_never_runs_into_the_first_call(tmp_path):
    # a 10 s run-in, as a video that starts near its first call
    store = Store(tmp_path)
    lines, fake, vmap = replay(KOBE, store, start=480)
    first_t = min(m["video_t"] for m in vmap["moments"])
    said = before_first(lines, store)
    assert said and said[0]["speaker"] == "lead"
    assert all(
        insight.due_after(ln["video_t"], ln["text"], 0) <= first_t - insight.TURN_S for ln in said
    )


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


def test_which_videos_open_on_both_cold_open_lines(tmp_path):
    said, asked = {}, {}

    def counted(moment, history):
        asked[match_id] += moment["outcome"].startswith(insight.OPEN)
        return twelve_words(moment, history)

    for match_id in ("0020500591", "0049700088", "1298150", "9636", "3754092", "3869685", WSL):
        r, asked[match_id] = Replay(match_id, 1e9), 0
        store = Store(tmp_path / match_id)
        asyncio.run(run_replay(r, load_moments(match_id), counted, store, video_map(match_id)))
        said[match_id] = [e["data"]["speaker"] for e in r.events if e["event"] == "line"]
    # a line with no room for 8 words is never asked for; 1298150's analyst has room for 8, not 12
    assert asked == {
        match_id: len(speakers) + (match_id == CRICKET) for match_id, speakers in said.items()
    }
    both, jim = ["lead", "analyst"], ["lead"]
    # with moments before the first call, the analyst's reply is a stretch's fact (#297), which
    # this commentator never says; from kick-off, the light line, where it fits
    assert said == {
        "0020500591": jim,
        "0049700088": jim,
        "3869685": both,  # from kick-off, 12 s
        WSL: jim,
        "1298150": jim,  # from kick-off, 9.0 s in
        "9636": both,  # from the start, 9.9 s in
        "3754092": jim,  # 6.3 s in: the welcome alone
    }


def test_an_open_leftover_too_short_for_a_line_is_never_asked_for(tmp_path):
    # the welcome said, a turn, then 1 s before the first call's turn: too short to ask Julian
    asked = []

    def counted(moment, history):
        asked.append(moment["outcome"].startswith(insight.OPEN))
        return twelve_words(moment, history)

    vmap = video_map(CRICKET)
    first_t = min(m["video_t"] for m in vmap["moments"])
    start = first_t - (12 / insight.WORDS_PER_S + 2 * insight.TURN_S + 1)
    r = Replay(CRICKET, 1e9)
    asyncio.run(
        run_replay(r, load_moments(CRICKET), counted, Store(tmp_path), {**vmap, "start": start})
    )
    said = [e["data"]["speaker"] for e in r.events if e["event"] == "line"]
    assert said == ["lead"] and sum(asked) == 1


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
    assert [ln["speaker"] for ln in good] == ["lead"] and all(ln["checked"] for ln in good)
    # a stored open line the check now fails is made again, never said
    stale = Store(tmp_path / "stale")
    for ln in store.all("lines"):
        stale.append(
            "lines", {**ln, "text": "Welcome, with 40000 here tonight."} if "open" in ln else ln
        )
    asked.clear()
    again = run(counting("Welcome to the Women's Super League."), stale)
    assert asked == ["lead"] and "40000" not in " ".join(ln["text"] for ln in again)


KEYED = {  # the open of the keyed WSL run at 7f28aaa, where Julian's line was cut for time
    "lead": "Hello everyone, welcome to Brighton against Bristol City in the Women's Super League, "
    "Julian alongside me.",
    "analyst": "Good to be here with you, Jim, and it should be a lively afternoon.",
}


def test_a_kickoff_open_hears_both_lines_at_a_real_lines_length(tmp_path):
    # 17 and 13 words, as the keyed WSL run's: the speech is 11.1 s, said in full a turn before
    # the first call; a 15 s cap that counted breaths once cut Julian
    def keyed(moment, history):
        if not moment["outcome"].startswith(insight.OPEN):
            return None
        text = KEYED[moment["detail"]["speaker"]]
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

    final, store = "3869685", Store(tmp_path)  # its first mapped moment is its first, 12 s in
    r = Replay(final, 1e9)
    asyncio.run(run_replay(r, load_moments(final), keyed, store, video_map(final)))
    said = before_first([e["data"] for e in r.events if e["event"] == "line"], store)
    assert [(ln["speaker"], ln["text"]) for ln in said] == list(KEYED.items())
    first_t = min(m["video_t"] for m in video_map(final)["moments"])
    assert insight.due_after(said[1]["video_t"], said[1]["text"], 0) <= first_t - insight.TURN_S


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


def test_a_kickoff_open_leaves_no_quiet_before_the_first_call(tmp_path):
    # #297: a line asked to fit what is left, and the video starting no earlier than two lines
    # need, so a kick-off open runs up to the first call: 14 s of quiet were left on 3869685
    asked = []

    def obeys(moment, history):
        if not moment["outcome"].startswith(insight.OPEN):
            return None
        most = int(moment["detail"]["length"].split()[2])  # "at most N words"
        asked.append(most)
        text = " ".join(["word"] * most)
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

    for match_id in ("3869685", "9636", CRICKET):
        store, vmap = Store(tmp_path / match_id), video_map(match_id)
        r = Replay(match_id, 1e9)
        asyncio.run(run_replay(r, load_moments(match_id), obeys, store, vmap))
        said = before_first([e["data"] for e in r.events if e["event"] == "line"], store)
        first_t = min(m["video_t"] for m in vmap["moments"])
        end = insight.due_after(said[-1]["video_t"], said[-1]["text"], 0)
        assert end <= first_t - insight.TURN_S, match_id
        assert insight.room(end + insight.TURN_S, first_t) < insight.MIN_WORDS, match_id
    assert asked and max(asked) == insight.OPEN_WORDS and min(asked) >= insight.MIN_WORDS


def test_a_stored_welcome_too_long_for_the_room_is_made_again_to_fit(tmp_path):
    # 3754092's first call is 6.3 s in: a 17-word welcome, stored by a replay whose model ignored
    # the length, ran into it; the next replay makes it again, asked for what fits
    asked = []

    def welcome(obeys):
        def said(moment, history):
            if not moment["outcome"].startswith(insight.OPEN):
                return None
            asked.append(int(moment["detail"]["length"].split()[2]))
            text = " ".join(["word"] * (asked[-1] if obeys else 17))
            return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

        return said

    store, vmap = Store(tmp_path), video_map(CHELSEA)
    first_t = min(m["video_t"] for m in vmap["moments"])
    for obeys in (False, True):
        asked.clear()
        r = Replay(CHELSEA, 1e9)
        asyncio.run(run_replay(r, load_moments(CHELSEA), welcome(obeys), store, vmap))
        said = before_first([e["data"] for e in r.events if e["event"] == "line"], store)
    assert asked == [min(insight.OPEN_WORDS, int((first_t - insight.TURN_S) * insight.WORDS_PER_S))]
    assert said and insight.due_after(said[0]["video_t"], said[0]["text"], 0) <= first_t
