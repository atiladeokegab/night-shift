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
    assert parse(json.dumps(json.loads(good))) is None  # spaced: not the canonical line
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
    change this hash only with a deliberate edit to agent/linecheck.py."""
    req = linecheck.request(linecheck.MESSAGE.template)
    digest = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    assert digest == "2eb1f287d0c636cf25e8b94b3165442fa6997197620fd1036776ddc700869de5"
    assert req["temperature"] == 0 and "tools" not in req


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
    assert tally["n"] == tally["agree"] == tally["same"] == len(exs)
    tally = seed_linecheck.pilot(exs, FakeProvider())  # no JSON: never the gold, same each time
    assert tally["agree"] == 0 and tally["same"] == len(exs)
    assert "agrees with gold 0.0%, same on repeat 100.0%" in capsys.readouterr().out
