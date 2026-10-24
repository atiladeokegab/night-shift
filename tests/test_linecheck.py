"""Line check (#209): the gold label comes from code, a reply is exactly one JSON object, and no
line of a held-out match is ever sent to Mubit."""

import hashlib
import json

import pytest

from agent import linecheck
from agent.commentator import CORRECTION, FakeProvider
from data.matches import load_moments, match_header
from eval import seed_linecheck
from eval.linecheck import HELD_OUT, dumps, gold, parse, plant


def _at(match_id, idx):
    moments = load_moments(match_id)
    i = next(i for i, m in enumerate(moments) if m["idx"] == idx)
    return match_header(match_id), moments[i], moments[:i]


def _gold(match_id, idx, text):
    return gold(*_at(match_id, idx), text)


def _labels(score, leader, total, event):
    return {"score": score, "leader": leader, "player_total": total, "event": event}


@pytest.mark.parametrize(
    "match_id, idx, text, want",
    [
        # basketball: Bryant's 3 for 47 points, Lakers 73, Raptors 78
        (
            "0020500591",
            6,
            "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 78!",
            _labels("ok", "ok", "ok", "ok"),
        ),
        # the same moment called as a layup, his total and the score wrong
        (
            "0020500591",
            6,
            "Kobe Bryant with the layup! He's got 49 points, Lakers trail 73 to 79!",
            _labels("wrong", "ok", "wrong", "wrong"),
        ),
        # football: Messi's penalty, 1-0
        (
            "3869685",
            5,
            "MESSI FROM THE SPOT! Argentina lead one nil!",
            _labels("ok", "ok", "not_said", "ok"),
        ),  # noqa: E501
        # a real wrong line from the store: Jordan's layup leaves Utah ahead 86-85
        (
            "0049700088",
            30,
            "Michael Jordan with the layup! Chicago Bulls take the lead, 85 to 86!",
            _labels("ok", "wrong", "not_said", "ok"),
        ),
        # cricket: Masood's four, Pakistan 28 for 2
        (
            "1298150",
            5,
            "Shan Masood, four! Pakistan 28 for 2.",
            _labels("ok", "not_said", "not_said", "ok"),
        ),  # noqa: E501
        (
            "1298150",
            5,
            "SIX! Shan Masood! Pakistan 28 for 3.",
            _labels("wrong", "not_said", "not_said", "wrong"),
        ),  # noqa: E501
        # F1: Ocon leads on lap 29
        ("9636", 6, "Ocon takes the lead on lap 29!", _labels("ok", "ok", "not_said", "ok")),
        (
            "9636",
            6,
            "Russell takes the lead on lap 30!",
            _labels("wrong", "wrong", "not_said", "ok"),
        ),
    ],
)
def test_gold_on_real_moments(match_id, idx, text, want):
    assert _gold(match_id, idx, text) == want


@pytest.mark.parametrize(
    "match_id, idx, text, want",
    [  # the audit's misses, each fixed
        (
            "1298150",
            0,
            "Babar Azam is lbw! Pakistan one for one!",
            _labels("ok", "not_said", "not_said", "ok"),
        ),  # noqa: E501
        (
            "0049700088",
            24,
            "Ron Harper from fifteen, he ties it up! Seventy-nine all!",
            _labels("ok", "ok", "not_said", "ok"),
        ),  # noqa: E501
        (
            "9636",
            14,
            "MAX VERSTAPPEN! WINS THE SÃO PAULO GRAND PRIX!",
            _labels("not_said", "ok", "not_said", "ok"),
        ),  # noqa: E501
        (
            "9636",
            12,
            "Verstappen takes the lead! Max Verstappen ahead of Ocon, into first place!",
            _labels("not_said", "ok", "not_said", "ok"),
        ),  # noqa: E501
    ],
)
def test_gold_after_the_audit(match_id, idx, text, want):
    assert _gold(match_id, idx, text) == want


@pytest.mark.parametrize(
    "match_id, idx, text, lead",
    [  # the pilot's leader misses: a lead claim with no team, or a team that extends it
        (
            "0020500591",
            9,
            "BRYANT WITH THE SLAM DUNK! Kobe takes the lead, Lakers 87, Raptors 85!",
            "ok",
        ),
        (
            "0049700088",
            32,
            "Michael Jordan! The go-ahead bucket! Chicago Bulls 87, Utah Jazz 86!",
            "ok",
        ),
        ("0020500591", 19, "Kobe Bryant from the line, and the Lakers extend it to 119-102!", "ok"),
        (
            "0020500591",
            19,
            "Kobe Bryant from the line, and the Raptors extend it to 119-102!",
            "wrong",
        ),
        (
            "0020500591",
            6,
            "Kobe Bryant from deep, he takes the lead! Lakers 73, Raptors 78!",
            "wrong",
        ),
        ("0049700088", 24, "Ron Harper from fifteen! Seventy-nine all!", "ok"),
        ("0049700088", 24, "Ron Harper from fifteen, seventy-nine apiece!", "ok"),
    ],
)
def test_gold_reads_take_the_lead_go_ahead_extend_all_apiece(match_id, idx, text, lead):
    assert _gold(match_id, idx, text)["leader"] == lead


@pytest.mark.parametrize(
    "match_id, idx, text, want",
    [  # the gaps the first recorded run showed
        (
            "0020500591",
            5,
            "Kobe Bryant with the jump shot, his 43rd point! Lakers trail the Raptors, 67 to 77.",
            _labels("ok", "ok", "ok", "ok"),
        ),
        (
            "0020500591",
            7,
            "Kobe Bryant with the reverse layup! Raptors trail the Lakers 81 to 85.",
            _labels("ok", "wrong", "not_said", "ok"),
        ),
        (
            "3869685",
            25,
            "Mbappé! Penalty! France pulls one back, two-one to Argentina!",
            _labels("ok", "ok", "not_said", "ok"),
        ),
        (
            "3869685",
            25,
            "Mbappé! Penalty! France pulls one back, two-one to France!",
            _labels("ok", "wrong", "not_said", "ok"),
        ),
        (
            "3869685",
            1,
            "De Paul with the chance from open play, blocked away! Still goalless.",
            _labels("ok", "not_said", "not_said", "ok"),
        ),
        (
            "3869685",
            25,
            "Mbappé! Penalty! Still goalless!",
            _labels("wrong", "not_said", "not_said", "ok"),
        ),
        # a save called a goal: the gold is right that the event is wrong
        (
            "3869685",
            34,
            "GOAL! Messi with the left foot in open play, but Lloris is equal to it, two-two!",
            _labels("ok", "not_said", "not_said", "wrong"),
        ),
    ],
)
def test_gold_reads_trail_the_team_n_m_to_a_team_and_goalless(match_id, idx, text, want):
    assert _gold(match_id, idx, text) == want


@pytest.mark.parametrize(
    "idx, text, want",
    [
        # At idx 5 Messi has made it 1-0. "Goalless" describes the state before this goal;
        # it must not override the current one-nil score claim.
        (5, "Argentina break the goalless deadlock and lead one-nil.", "ok"),
        # Scoreless references to earlier states are not the current score.
        (5, "Argentina were scoreless before the penalty; now they lead one-nil.", "ok"),
        (
            5,
            "The earlier match ended goalless; Messi scores the penalty and Argentina lead one-nil.",
            "ok",
        ),
        # At idx 1 the score really is 0-0, while at idx 6 it is 1-0 and play is still live.
        (1, "Still goalless.", "ok"),
        (6, "Still goalless.", "wrong"),
        (5, "Messi's penalty! It is still goalless before half-time.", "wrong"),
        (
            5,
            "They were goalless before the penalty; still goalless now despite Argentina leading one-nil.",
            "wrong",
        ),
    ],
)
def test_gold_treats_goalless_as_current_state_not_any_mention_of_zero(idx, text, want):
    label = _gold("3869685", idx, text)
    assert label is not None
    assert label["score"] == want


def test_gold_does_not_turn_a_team_scoped_goalless_claim_into_match_0_0():
    # France have not scored at 1-0, but this line does not say the match is 0-0.
    # Since gold() has no team-scoped score label, decline to label it rather than call it wrong.
    assert _gold("3869685", 5, "France remain goalless.") is None


def test_gold_never_guesses_a_number_it_cannot_place():
    # 47 is Bryant's total, said without "points": a total or not, code can't tell
    assert _gold("0020500591", 6, "Kobe Bryant from deep, 47 now!") is None
    # a number the moment doesn't give at all
    assert _gold("0020500591", 6, "Kobe Bryant from deep, his 12th three!") is None


@pytest.mark.parametrize(
    "match_id, idx, text, field",
    [
        (
            "0020500591",
            6,
            "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 78!",
            "score",
        ),  # noqa: E501
        (
            "0020500591",
            6,
            "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 78!",
            "player_total",
        ),  # noqa: E501
        (
            "0020500591",
            6,
            "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 78!",
            "event",
        ),  # noqa: E501
        ("0020500591", 6, "Kobe Bryant from deep! Raptors lead 78 to 73!", "leader"),
        ("1298150", 5, "Shan Masood, four! Pakistan 28 for 2.", "event"),
        ("3869685", 1, "Di María with a chance, but it goes wide!", "event"),
    ],
)
def test_a_planted_error_is_wrong_on_its_field_only(match_id, idx, text, field):
    header, m, past = _at(match_id, idx)
    label = gold(header, m, past, text)
    assert label[field] == "ok"
    planted = plant(header, m, past, text, label, field)
    assert planted and planted != text
    assert gold(header, m, past, planted) == {**label, field: "wrong"}


def test_parse_takes_exactly_one_json_object():
    good = dumps(_labels("ok", "wrong", "not_said", "ok"))
    assert parse(good) == _labels("ok", "wrong", "not_said", "ok")
    assert good == '{"score":"ok","leader":"wrong","player_total":"not_said","event":"ok"}'
    assert parse(f"  {good}\n") is not None
    assert parse(json.dumps(json.loads(good))) is not None  # whitespace aside, the same line
    reordered = json.dumps(dict(reversed(json.loads(good).items())), separators=(",", ":"))
    assert parse(reordered) is None
    assert parse(f"Here you go: {good}") is None
    assert parse(f"{good} The leader is wrong.") is None
    assert parse(f"```json\n{good}\n```") is None
    assert parse(json.dumps({**json.loads(good), "why": "x"})) is None
    assert parse(good.replace('"wrong"', '"maybe"')) is None
    assert parse(json.dumps({"score": "ok"})) is None


def _lines():
    """Store lines of a training match and both held-out matches."""
    return [
        {"match_id": "1298150", "moment_idx": 5, "text": "Shan Masood, four! Pakistan 28 for 2."},
        {
            "match_id": "0020500591",
            "moment_idx": 6,
            "text": "Kobe Bryant from deep! Lakers 73, Raptors 78!",
        },  # noqa: E501
        {"match_id": "9636", "moment_idx": 6, "text": "Ocon takes the lead on lap 29!"},
        {
            "match_id": "3913122",
            "moment_idx": 8,
            "text": "GOAL! Elisabeth Terland! Brighton one, Bristol City nil!",
        },  # noqa: E501
        {
            "match_id": "1298150",
            "moment_idx": 5,
            "text": "Wait, I need to check.",
            "fallback": True,
        },
    ]


def test_held_out_matches_never_reach_a_go_batch():
    exs = seed_linecheck.examples(_lines())
    assert {e["match_id"] for e in exs if e["held_out"]} == set(HELD_OUT)  # they are labelled
    sent = seed_linecheck.batch(exs, 10**6)
    assert sent and not {e["match_id"] for e in sent} & set(HELD_OUT)
    assert any(e.get("planted") for e in sent)


def test_a_wrong_first_reply_is_corrected_with_the_exact_gold(capsys):
    exs = seed_linecheck.batch(seed_linecheck.examples(_lines()), 1)
    fake = FakeProvider()  # its reply is no JSON, so every first reply is corrected
    tally = seed_linecheck.go(exs, fake)
    assert tally == {"corrected": 1}
    last = fake.requests[-1]["messages"][-1]["content"]
    assert last == CORRECTION.format(text=dumps(exs[0]["gold"]))
    assert "gold" not in json.dumps(fake.requests[0])  # the prompt carries inputs only
    assert f"REC {exs[0]['id']} matched=False corrected=True" in capsys.readouterr().out


def test_dry_runs_offline_and_scores_held_out(tmp_path, capsys):
    lines = tmp_path / "lines.jsonl"
    lines.write_text("\n".join(json.dumps(x) for x in _lines()))
    assert seed_linecheck.main(["--dry", "--lines", str(lines)], env={}) == 0
    out = capsys.readouterr().out
    assert "held out" in out and "tally:" in out
    held = [e for e in seed_linecheck.examples(_lines()) if e["held_out"]]
    outputs = tmp_path / "out.jsonl"
    outputs.write_text(
        "\n".join(json.dumps({"id": e["id"], "output": dumps(e["gold"])}) for e in held)
        + "\n"
        + json.dumps({"id": held[0]["id"], "output": "not json"})
    )
    r = seed_linecheck.score(seed_linecheck.examples(_lines()), str(outputs))
    assert r["scored"] == len(held) + 1 and r["unparsed"] == 1 and r["exact"] == len(held)


def test_the_task_is_pinned():
    """Mubit groups calls into one task only when prompt, tools, format and model are identical:
    change these hashes only with a deliberate edit to agent/linecheck.py."""
    assert (
        hashlib.sha256(linecheck.SYSTEM.encode()).hexdigest()
        == "5122b3495bfdf70124ac7a7dffafc7b0a6f1b2e039676f8d337f3a606a4f7a3d"
    )
    req = linecheck.request(linecheck.MESSAGE.template, "M", 0)
    digest = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    assert digest == "4385ce91bd2b19d56fb4a7e34ced88ab9f746d64a54e516c9f49e89ac064b982"
    assert "tools" not in req


def test_one_mubit_session_per_moment():
    """Mubit sets test cases aside by session: a moment's lines share one, moments never do."""
    one = seed_linecheck.request({"match_id": "1298150", "idx": 5, "text": "Four!"})
    two = seed_linecheck.request({"match_id": "1298150", "idx": 5, "text": "FOUR! Masood!"})
    other = seed_linecheck.request({"match_id": "1298150", "idx": 6, "text": "Four!"})
    assert one["metadata"] == two["metadata"] == {"user_id": "line-check-1298150-5"}
    assert other["metadata"]["user_id"] == "line-check-1298150-6"


def test_go_keeps_eight_in_flight_and_reports_every_example(capsys):
    exs = seed_linecheck.batch(seed_linecheck.examples(_lines()), 10)
    assert seed_linecheck.go(exs, FakeProvider(), workers=8) == {"corrected": len(exs)}
    out = capsys.readouterr().out
    assert all(f"REC {e['id']} matched=False corrected=True" in out for e in exs)


def test_pilot_reports_gold_and_repeat_agreement(capsys):
    exs = seed_linecheck.batch(seed_linecheck.examples(_lines()), 10)

    class Echo:  # Claude, if it answered every case with the gold
        def call(self, req):
            ex = next(e for e in exs if e["text"] in req["messages"][0]["content"])
            return {"content": [{"type": "text", "text": dumps(ex["gold"])}]}

    tally = seed_linecheck.pilot(exs, Echo())
    assert tally["n"] == tally["agree"] == tally["same"] == tally["event"] == len(exs)
    tally = seed_linecheck.pilot(exs, FakeProvider())  # no JSON: never the gold, same each time
    assert tally["agree"] == tally["score"] == 0 and tally["same"] == len(exs)
    assert "agrees with gold 0.0%, same on repeat 100.0%" in capsys.readouterr().out


def test_go_never_corrects_on_leader_alone(capsys):
    exs = seed_linecheck.batch(seed_linecheck.examples(_lines()), 10)
    ex = next(e for e in exs if e["gold"]["leader"] != "wrong")

    class LeaderOff:  # the gold, but for the leader
        requests = []

        def call(self, req):
            self.requests.append(req)
            return {"content": [{"type": "text", "text": dumps({**ex["gold"], "leader": "wrong"})}]}

    fake = LeaderOff()
    assert seed_linecheck.go([ex], fake) == {"leader_only": 1}
    assert len(fake.requests) == 1  # no correction turn
    assert f"REC {ex['id']} matched=False corrected=-" in capsys.readouterr().out


def test_the_request_holds_the_answer_to_the_schema():
    req = linecheck.request("Line: x", "M", 0)
    assert "temperature" not in req and req["model"] == "claude-sonnet-5-5"
    schema = req["output_config"]["format"]["schema"]
    assert schema["required"] == list(linecheck.FIELDS) and not schema["additionalProperties"]
    assert all(schema["properties"][f]["enum"] == list(linecheck.LABELS) for f in linecheck.FIELDS)
