"""The commentator request, the no-leak rule (S10) and the traffic runner, all offline."""

import json
import time

import pytest

from agent import commentator, feed
from agent.commentator import FakeProvider, build_request, commentate, line_for
from data.matches import load_moments, match_header
from scripts import replay_matches

FOOT = {
    "sport": "football",
    "match_id": "7",
    "home": "Reds",
    "away": "Blues",
    "competition": "Cup",
    "stage": "Final",
    "date": "2020-01-01",
}
CRIC = {
    "sport": "cricket",
    "match_id": "8",
    "home": "A",
    "away": "B",
    "competition": "T20",
    "stage": "",
    "date": "2020-01-02",
}


def moment(header, idx, player="Ann", outcome="Saved", **extra):
    m = {
        "sport": header["sport"],
        "match_id": header["match_id"],
        "idx": idx,
        "period": 1,
        "clock": f"{idx:02d}:00",
        "type": "Shot",
        "team": "Reds",
        "players": {"shooter": player},
        "outcome": outcome,
        "score": {"home": 0, "away": 0},
        "detail": {},
    }
    if header["sport"] == "cricket":
        m.update(
            clock=f"{idx}.1",
            type="Wicket",
            team="A",
            players={"batter": player},
            score={"runs": 10 * idx, "wickets": idx},
            detail={"wicket_kind": "bowled"},
        )
    return {**m, **extra}


class AskEverything(FakeProvider):
    """Calls every tool in the first round, as a curious model might."""

    def call(self, request):
        if len(request["messages"]) == 1:
            self.requests.append(json.loads(json.dumps(request)))
            uses = [
                ("get_score", {}),
                ("get_player", {"name": "Zed"}),
                ("get_recent_play", {"count": 10}),
            ]
            return {
                "content": [
                    {"type": "tool_use", "id": f"t{i}", "name": n, "input": a}
                    for i, (n, a) in enumerate(uses)
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "request_id": "r1",
                "first_word_ms": None,
            }
        return super().call(request)


def test_lead_model_env_overrides_haiku_at_request_time(monkeypatch):
    monkeypatch.delenv("LEAD_MODEL", raising=False)
    haiku = build_request(FOOT, [moment(FOOT, 0)])
    assert haiku["model"] == "claude-haiku-4-5" and "thinking" not in haiku
    monkeypatch.setenv("LEAD_MODEL", "claude-sonnet-5-5")
    sonnet = build_request(FOOT, [moment(FOOT, 0)])
    assert sonnet["model"] == "claude-sonnet-5-5"
    assert sonnet["thinking"] == {"type": "between_tools"}


def test_frozen_parts_are_byte_identical_across_sports():
    f = build_request(FOOT, [moment(FOOT, 0)])
    c = build_request(CRIC, [moment(CRIC, 0)])
    for key in ("model", "max_tokens", "system", "tools", "tool_choice"):
        assert json.dumps(f[key]) == json.dumps(c[key])
    assert f["metadata"] == {"user_id": "match-football-7"}
    assert c["metadata"] == {"user_id": "match-cricket-8"}
    # Only the template's fields differ: the template's fixed text is in both messages.
    for fixed in ("Sport: ", "Score after this moment: ", "Recent play:"):
        assert fixed in f["messages"][0]["content"] and fixed in c["messages"][0]["content"]


def test_a_later_event_never_reaches_the_model():
    for header in (FOOT, CRIC):
        moments = [moment(header, i) for i in range(4)]
        moments.append(moment(header, 4, player="Zed FUTURE", outcome="Goal FUTURE"))
        provider = AskEverything()
        line = line_for(header, moments, 2, provider)
        assert len(provider.requests) == 2 and len(line["tool_calls"]) == 3
        assert "FUTURE" not in json.dumps(provider.requests)
        assert "FUTURE" not in json.dumps(line)


def test_one_tool_round_then_a_line():
    moments = [moment(FOOT, 0, outcome="Goal", score={"home": 1, "away": 0})]
    provider = FakeProvider()
    line = line_for(FOOT, moments, 0, provider)
    assert [c["name"] for c in line["tool_calls"]] == ["get_score"]
    assert "Reds 1, Blues 0" in line["tool_calls"][0]["output"]
    assert line["text"] and line["mubit_request_ids"] == ["fake-1", "fake-2"]
    assert set(line) == {
        "line_id",
        "sport",
        "match_id",
        "moment_idx",
        "text",
        "model",
        "served_by",
        "latency_ms",
        "first_word_ms",
        "tokens_in",
        "tokens_out",
        "mubit_request_ids",
        "tool_calls",
        "created_at",
    }
    assert line["model"] == commentator.MODEL == "claude-haiku-4-5"


def test_runner_skips_demo_held_out_and_replayed_matches(monkeypatch, tmp_path):
    ids = [3754092, 105, 106, 107, 108]  # demo, held out, then eligible
    monkeypatch.setattr(replay_matches, "FOOTBALL", [(1, 1)])
    monkeypatch.setattr(feed, "statsbomb_matches", lambda c, s: [{"match_id": i} for i in ids])
    monkeypatch.setattr(
        feed,
        "load",
        lambda sport, mid, meta: (
            {**FOOT, "match_id": mid},
            [moment({**FOOT, "match_id": mid}, i) for i in range(3)],
        ),
    )
    out = tmp_path / "lines.jsonl"

    assert replay_matches.main(["--football", "2", "--fake", "--out", str(out)]) == 0
    lines = [json.loads(r) for r in out.read_text().splitlines()]
    assert {line["match_id"] for line in lines} == {"106", "107"}
    assert len(lines) == 6

    replay_matches.main(["--football", "2", "--fake", "--out", str(out)])
    again = [json.loads(r) for r in out.read_text().splitlines()][6:]
    assert {line["match_id"] for line in again} == {"108"}  # never a match already there


def test_pick_keeps_goals_and_spreads_the_rest():
    moments = [moment(FOOT, i, outcome="Goal" if i in (3, 40) else "Saved") for i in range(50)]
    picked = replay_matches.pick(moments, 10)
    assert len(picked) == 10 and {3, 40} <= set(picked) and picked == sorted(set(picked))


def test_server_seam_on_the_bundled_samples(monkeypatch):
    from data.matches import list_matches, load_moments

    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    monkeypatch.setattr(commentator, "_provider", None)
    samples = list_matches()
    assert {(m["sport"], m["match_id"]) for m in samples} == feed.DEMO
    assert all(m["sample"] for m in samples)
    for m in samples:
        moments = load_moments(m["match_id"])
        line = commentate(moments[3], moments[:3])
        assert line["match_id"] == m["match_id"] and line["moment_idx"] == 3 and line["text"]
    for bad in ("nope", "../sample/cricket-1298150", "*"):
        try:
            load_moments(bad)
            raise AssertionError(bad)
        except KeyError:
            pass


class Scripted:
    """Answers each call with the next scripted content list."""

    def __init__(self, *contents):
        self.contents = list(contents)

    def call(self, request):
        return {
            "content": self.contents.pop(0),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "request_id": f"r{len(self.contents)}",
            "first_word_ms": 5.0,
        }


TOOL = [{"type": "tool_use", "id": "t1", "name": "get_score", "input": {}}]


def text(t):
    return [{"type": "text", "text": t}]


def test_a_tool_only_last_reply_is_no_line_not_a_blank_one():
    moments = [moment(FOOT, 0)]
    with pytest.raises(commentator.NoLine):
        line_for(FOOT, moments, 0, Scripted(TOOL, TOOL))
    assert commentate(moments[0], [], header=FOOT, provider=Scripted(TOOL, TOOL)) is None


@pytest.mark.parametrize(
    "said",
    [
        "I have all the information I need from your message.",
        "Let me check the score first.",
        "There's a discrepancy here: you say the event is a shot off target. Could you clarify?",
        "",
    ],
)
def test_preamble_alone_is_no_line(said):
    with pytest.raises(commentator.NoLine):
        line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text(said)))


@pytest.mark.parametrize(
    "said",
    [
        "I have all the information I need from your message.\n\nGoal! Ann buries it.",
        "I have all the information I need from your message. Goal! Ann buries it.",
        "Based on the score, here goes: Goal! Ann buries it.",
        "I have all the information I need from your message… Goal! Ann buries it.",
        "The score confirms Reds 1, Blues 0, so despite being labeled a save, it went in.\n\n"
        "Goal! Ann buries it.",
    ],
)
def test_preamble_never_becomes_the_line(said):
    line = line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text(said)))
    assert line["text"] == "Goal! Ann buries it."


def test_a_line_starting_with_now_is_kept():
    line = line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text("Now that is a strike from Ann!")))
    assert line["text"] == "Now that is a strike from Ann!"


def test_messis_penalty_reaches_the_model_as_lionel_messi():
    moments = load_moments("3869685")
    pen = next(
        m for m in moments if m["outcome"] == "Goal" and m["detail"]["shot_type"] == "Penalty"
    )
    message = commentator.render_message(match_header("3869685"), moments[: pen["idx"] + 1])
    assert "Lionel Messi" in message and "Cuccittini" not in message


def test_one_untemplated_prompt_asks_for_a_broadcast_call_on_big_moments():
    # A-3.6, offline
    system = commentator.SYSTEM
    assert "$" not in system and "{" not in system  # fixed text, never templated per sport
    for sport in ("football", "cricket", "basketball", "formula"):
        assert sport not in system.lower()  # the sport goes in the message, never the prompt
    for rule in ("changes the score, the lead or the result", "emotion", "20 words"):
        assert rule in system
    assert "calmly" in system  # routine moments stay calm


@pytest.mark.parametrize(
    "said, line",
    [
        ("BAD Manenti hits four! Italy 98 for 5.", "Manenti hits four! Italy 98 for 5."),
        (
            "Miedema takes the shot from the right foot in open play, Mackenzie Arnold is equal to"
            " it! Arsenal still leading seven to one.",
            "Miedema takes the shot from the right foot in open play, Mackenzie Arnold is equal to"
            " it!",
        ),
        ("GOAL! Ann! Reds one, Blues nil!", "GOAL! Ann! Reds one, Blues nil!"),
        (  # the score closes the line, so the middle goes
            "What a header from Alexandra Popp! She climbs above everyone at the near post and"
            " buries it past the keeper! Germany extend it to four.",
            "What a header from Alexandra Popp! Germany extend it to four.",
        ),
        (  # a decimal point never ends a sentence
            "Bowled him at 19.4 overs! The stumps go cartwheeling back towards the keeper and the"
            " crowd erupts in noise! India 150 for 7.",
            "Bowled him at 19.4 overs! India 150 for 7.",
        ),
    ],
)
def test_line_is_trimmed_to_whole_sentences_within_20_words(said, line):
    assert line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text(said)))["text"] == line


def test_26_word_f1_line_keeps_its_call_and_the_gap():
    said = (
        "Verstappen takes the flag at Interlagos! From seventeenth on the grid to win in the rain,"
        " what a drive! Verstappen wins by 19.5 seconds from Ocon."
    )
    assert len(said.split()) == 26
    moments = load_moments("9636")
    line = line_for(match_header("9636"), moments, len(moments) - 1, Scripted(text(said)))
    assert (
        line["text"]
        == "Verstappen takes the flag at Interlagos! Verstappen wins by 19.5 seconds from Ocon."
    )


def test_one_sentence_over_20_words_is_no_line():
    said = " ".join(["word"] * 21) + "!"
    with pytest.raises(commentator.NoLine):
        line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text(said)))


def test_cricket_score_reads_runs_for_wickets():
    # "10/2" was read aloud backwards ("two for ten"); the message spells the order out.
    past = [moment(CRIC, 2, score={"runs": 10, "wickets": 2})]
    message = build_request(CRIC, past)["messages"][0]["content"]
    assert "Score after this moment: A 10 for 2\n" in message
    assert commentator.run_tool("get_score", {}, CRIC, past).startswith("A 10 for 2;")
    assert "10/2" not in json.dumps(build_request(CRIC, past))


def test_jordans_last_shot_reaches_the_model_with_names_and_score():
    moments = load_moments("0049700088")
    shot = next(m for m in moments if m["clock"] == "00:05" and m["period"] == 4)
    message = commentator.render_message(match_header("0049700088"), moments[: shot["idx"] + 1])
    assert "Sport: basketball" in message and "Moment: quarter 4, 00:05" in message
    assert "shooter: Michael Jordan" in message
    assert "Score after this moment: Chicago Bulls 87, Utah Jazz 86" in message


def test_kobes_81st_point_reaches_the_model():
    moments = load_moments("0020500591")
    record = next(m for m in moments if m["detail"].get("player_points") == 81)
    assert record["players"] == {"shooter": "Kobe Bryant"}
    assert record["score"] == {"home": 122, "away": 102}
    assert moments[-1]["type"] == "End of game"
    assert moments[-1]["score"] == {"home": 122, "away": 104}


def test_verstappens_win_reaches_the_model_with_places_and_gaps():
    moments, header = load_moments("9636"), match_header("9636")
    message = commentator.render_message(header, moments)
    assert "Sport: f1" in message and "Moment: lap 69, 127:14" in message
    assert "Match: Formula 1 São Paulo Grand Prix, Interlagos, 2024-11-03" in message
    assert "winner: Max Verstappen" in message
    assert (
        "Score after this moment: Lap 69 of 69: P1 Max Verstappen leader, "
        "P2 Esteban Ocon 19.5 seconds, P3 Pierre Gasly 22.6 seconds" in message
    )
    lead = next(m for m in moments if m["type"] == "Lead change" and m["period"] == 43)
    assert lead["players"] == {"driver": "Max Verstappen", "passed": "Esteban Ocon"}
    lead = next(m for m in moments if m["type"] == "Lead change" and m["period"] == 29)
    assert lead["players"] == {"driver": "Esteban Ocon", "passed": "George Russell"}
    stop = moments[lead["idx"] + 1]  # called as he leaves the pit lane, after the lead change
    assert (stop["type"], stop["players"]) == ("Pit stop", {"driver": "Lando Norris"})
    message = commentator.render_message(header, moments[: stop["idx"] + 1])
    assert "pit_lane_time: 24.7 seconds in the pit lane" in message
    assert "P1 Esteban Ocon leader" in message and "P1 Lando Norris" not in message
    race = build_request(header, moments)  # A-10.3: the same frozen model, prompt and tools
    assert (race["model"], race["system"]) == (commentator.MODEL, commentator.SYSTEM)
    assert (race["tools"], race["tool_choice"]) == (commentator.TOOLS, commentator.TOOL_CHOICE)


@pytest.mark.parametrize("setting, recorded", [(None, True), ("on", True), ("off", False)])
def test_mubit_record_off_keeps_lines_out_of_the_keys_training(monkeypatch, setting, recorded):
    made = []

    class Mubit(FakeProvider):
        def __init__(self, key, record=True, fallback=None):
            super().__init__()
            made.append(record)

    monkeypatch.setattr(commentator, "MubitProvider", Mubit)
    monkeypatch.setattr(commentator, "_provider", None)
    monkeypatch.setenv("MUBIT_API_KEY", "test-key")
    monkeypatch.delenv("MUBIT_FALLBACK_KEY", raising=False)
    if setting is None:
        monkeypatch.delenv("MUBIT_RECORD", raising=False)
    else:
        monkeypatch.setenv("MUBIT_RECORD", setting)
    commentator.default_provider()
    assert made == [recorded]


def _sse(text: str, model: str = commentator.MODEL) -> bytes:
    """A whole Messages stream saying `text`, as Mubit would send it."""
    message = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }
    events = [
        ("message_start", {"type": "message_start", "message": message}),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()


def _mubit(monkeypatch, primary_status, fallback=True, record="off", primary_s=0.0, bodies=None):
    """default_provider() on fake keys, its HTTP stubbed: the primary key answers
    `primary_status`, the fallback always speaks. Returns the provider and the requests seen;
    `bodies`, when given, collects each request's JSON body as the SDK sent it."""
    import httpx2 as httpx  # the HTTP package the anthropic SDK uses

    seen = []

    def handle(request):
        key = request.headers["authorization"].removeprefix("Bearer ")
        seen.append((key, request.headers.get("x-middleware-record")))
        if bodies is not None:
            bodies.append(json.loads(request.content))
        if key == "fake-lent" and primary_status != 200:
            time.sleep(primary_s)
            body = {"type": "error", "error": {"type": "billing_error", "message": "no credit"}}
            return httpx.Response(primary_status, json=body)
        return httpx.Response(
            200,
            content=_sse(f"Goal from the {key} key."),
            headers={"content-type": "text/event-stream", "x-middleware-request-id": key},
        )

    monkeypatch.setattr(commentator, "_provider", None)
    monkeypatch.setattr(commentator, "_trainer", None)
    monkeypatch.setattr(commentator, "_unrecorded", None)
    monkeypatch.setenv("MUBIT_API_KEY", "fake-lent")
    monkeypatch.setenv("MUBIT_RECORD", record)
    if fallback:
        monkeypatch.setenv("MUBIT_FALLBACK_KEY", "fake-owner")
    else:
        monkeypatch.delenv("MUBIT_FALLBACK_KEY", raising=False)
    provider = commentator.default_provider()
    http = httpx.Client(transport=httpx.MockTransport(handle))
    trainer, unrecorded = commentator.correction_provider(), commentator.unrecorded_provider()
    for p in (provider, provider.fallback, trainer, unrecorded, unrecorded.fallback):
        if p is not None:
            p.client = p.client.with_options(http_client=http)
    return provider, seen


def _two_lines(provider):
    moments = [moment(FOOT, 0), moment(FOOT, 1)]
    return [line_for(FOOT, moments, i, provider)["text"] for i in (0, 1)]


def test_a_402_on_the_lent_key_moves_the_lines_to_the_owners_key_for_good(monkeypatch, caplog):
    provider, seen = _mubit(monkeypatch, 402)
    lines = _two_lines(provider)
    assert lines == ["Goal from the fake-owner key."] * 2
    # one failed call on the lent key, then the owner's key: the next line never tries the lent one
    assert [key for key, _ in seen] == ["fake-lent", "fake-owner", "fake-owner"]
    assert "fake-" not in caplog.text and "402" in caplog.text


def test_the_owners_key_records_and_the_lent_key_stays_unrecorded(monkeypatch):
    provider, seen = _mubit(monkeypatch, 402, record="off")
    _two_lines(provider)
    assert seen == [("fake-lent", "off"), ("fake-owner", None), ("fake-owner", None)]


GOAL = {"outcome": "Goal", "score": {"home": 1, "away": 0}}  # "Goal from the ... key." passes


def test_a_fix_records_on_the_owners_key_while_lines_stay_unrecorded(monkeypatch):
    # #161: the lent key never records, so a fix sent on it trained nothing; #245: the fix is
    # checked unrecorded first, then sent once more on the owner's key
    provider, seen = _mubit(monkeypatch, 200, record="off")
    moments = [moment(FOOT, 0, **GOAL)]
    line = line_for(FOOT, moments, 0, provider)
    sent = commentator.correct(line, "Ann scores!", FOOT, moments)
    assert seen == [("fake-lent", "off"), ("fake-lent", "off"), ("fake-owner", None)]
    assert sent["recorded"] is True and sent["mubit_request_id"] == "fake-owner"


@pytest.mark.parametrize("outcome", ["Goal", "Saved"])
def test_a_fix_through_the_sdk_is_recorded_only_when_its_reply_passes(monkeypatch, outcome):
    # #245: through the real SDK call. The correction goes unrecorded first; its reply ("Goal from
    # the fake-lent key.") passes on a goal, so the same request is sent once more, recorded; on a
    # save it fails, and nothing is recorded
    bodies = []
    provider, seen = _mubit(monkeypatch, 200, record="off", bodies=bodies)
    moments = [moment(FOOT, 0, **(GOAL if outcome == "Goal" else {}))]
    line = line_for(FOOT, moments, 0, provider)
    sent = commentator.correct(line, "Ann scores!", FOOT, moments, reason="Wrong event")
    said, checked, *recorded = bodies
    assert {k: v for k, v in checked.items() if k != "messages"} == {
        k: v for k, v in said.items() if k != "messages"
    }
    assert checked["messages"] == said["messages"] + [
        {"role": "assistant", "content": line["text"]},
        {"role": "user", "content": sent["correction"]},
    ]
    assert sent["correction"].startswith("Producer correction: Wrong event\n")
    assert seen[1] == ("fake-lent", "off")  # the check is never recorded
    if outcome == "Goal":
        assert recorded == [checked] and seen[2:] == [("fake-owner", None)]
        assert sent["reply_passed"] is True and sent["recorded"] is True
    else:
        assert recorded == [] and len(seen) == 2
        assert sent["reply_passed"] is False and sent["recorded"] is False


def test_a_fix_to_an_analyst_line_goes_unrecorded_and_says_so(monkeypatch):
    provider, seen = _mubit(monkeypatch, 200, record="off")
    stat = {**moment(FOOT, 1), "type": "Stat"}
    moments = [moment(FOOT, 0), stat]
    line = {**line_for(FOOT, moments, 1, provider), "moment_idx": 1}
    sent = commentator.correct(line, "Ann has two saves.", FOOT, moments)
    assert seen[-1] == ("fake-lent", "off") and sent["recorded"] is False


def test_a_fix_after_a_402_is_checked_unrecorded_then_recorded_on_the_owners_key(monkeypatch):
    provider, seen = _mubit(monkeypatch, 402, record="off")
    moments = [moment(FOOT, 0, **GOAL)]
    line = line_for(FOOT, moments, 0, provider)
    sent = commentator.correct(line, "Ann scores!", FOOT, moments)
    assert seen == [
        ("fake-lent", "off"),  # the line: 402, then the owner's key
        ("fake-owner", None),
        ("fake-lent", "off"),  # the check: 402, then the owner's key, still unrecorded
        ("fake-owner", "off"),
        ("fake-owner", None),  # the recorded correction
    ]
    assert sent["recorded"] is True


def test_without_an_owners_key_a_fix_goes_as_its_line_did(monkeypatch):
    provider, seen = _mubit(monkeypatch, 200, fallback=False, record="off")
    moments = [moment(FOOT, 0)]
    sent = commentator.correct(line_for(FOOT, moments, 0, provider), "Ann saves it!", FOOT, moments)
    assert seen == [("fake-lent", "off"), ("fake-lent", "off")] and sent["recorded"] is False


def test_a_500_does_not_switch_keys(monkeypatch):
    import anthropic

    provider, seen = _mubit(monkeypatch, 500)
    with pytest.raises(anthropic.InternalServerError):
        _two_lines(provider)
    assert {key for key, _ in seen} == {"fake-lent"}


def test_without_a_fallback_key_a_402_still_takes_the_commentator_off_air(monkeypatch):
    import anthropic

    provider, seen = _mubit(monkeypatch, 402, fallback=False)
    with pytest.raises(anthropic.APIStatusError) as err:
        _two_lines(provider)
    assert err.value.status_code == 402 and [key for key, _ in seen] == ["fake-lent"]


def test_the_first_word_after_a_402_counts_the_failed_call(monkeypatch):
    provider, _ = _mubit(monkeypatch, 402, primary_s=0.3)
    line = line_for(FOOT, [moment(FOOT, 0)], 0, provider)
    # the viewer waited through the lent key's 402 too
    assert line["first_word_ms"] >= 300


def test_a_line_says_which_model_served_it_from_the_reply_and_keeps_mubits_headers():
    # #250: what answered comes from Mubit's reply, never from what was asked or a name in the app
    import httpx2 as httpx

    def handle(request):
        return httpx.Response(
            200,
            content=_sse("Goal for Ann!", model="some-adapter-v3"),
            headers={
                "content-type": "text/event-stream",
                "x-middleware-request-id": "mreq_1",
                "X-Middleware-Route": "adapter",
                "request-id": "req_provider",
            },
        )

    provider = commentator.MubitProvider("fake-key")
    provider.client = provider.client.with_options(
        http_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    reply = provider.call(commentator.build_request(FOOT, [moment(FOOT, 0)]))
    assert reply["served_by"] == "some-adapter-v3" and reply["request_id"] == "mreq_1"
    assert reply["middleware"] == {
        "x-middleware-request-id": "mreq_1",
        "x-middleware-route": "adapter",
    }
    line = line_for(FOOT, [moment(FOOT, 0)], 0, provider)
    assert line["served_by"] == "some-adapter-v3" and line["model"] == commentator.MODEL
    assert line["mubit_request_ids"] == ["mreq_1"]


def test_the_side_ahead_is_named_first_in_the_score_the_model_reads():
    """Live 00163: given "Lakers 53, Raptors 69", the model said "Toronto leads fifty-three to
    sixty-nine". Away ahead flips the order; home ahead and level keep it; so does cricket."""
    moments, header = load_moments("0020500591"), match_header("0020500591")
    away = next(m for m in moments if m["idx"] == 3)  # Raptors 69, Lakers 53
    home = next(m for m in moments if m["idx"] == 22)  # Lakers 121, Raptors 102
    tied = next(m for m in moments if m["idx"] == 2)  # 5-5
    score = commentator._score_leader_first
    assert score(header, away) == "Toronto Raptors 69, Los Angeles Lakers 53"
    assert score(header, home) == "Los Angeles Lakers 121, Toronto Raptors 102"
    assert score(header, tied) == "Los Angeles Lakers 5, Toronto Raptors 5"
    assert "Score after this moment: Toronto Raptors 69, Los Angeles Lakers 53" in (
        commentator.render_message(header, moments[:4])
    )
    cricket = load_moments("1298150")
    h = match_header("1298150")
    assert score(h, cricket[5]) == commentator._score(h, cricket[5])


def test_a_leader_first_line_passes_the_number_check():
    from core import insight

    moments, header = load_moments("0020500591"), match_header("0020500591")
    m = next(m for m in moments if m["idx"] == 3)
    line = "Bryant's ten-footer, thirty points, but Toronto lead sixty-nine to fifty-three."
    assert insight.wrong_numbers(line, m, header, moments[:3]) == []
    assert (
        insight.wrong_numbers(
            "Toronto Raptors 69, Los Angeles Lakers 53, Bryant has thirty.", m, header, moments[:3]
        )
        == []
    )
