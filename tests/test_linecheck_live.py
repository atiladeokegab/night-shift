"""Line check in the live path (#298): a second opinion on each checked lead line, off its path,
and a producer's fix sent to it as one example with the answer key code gives."""

import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from agent import linecheck
from agent.commentator import CORRECTION
from core import guard as guard_mod
from core.app import Deps, create_app
from core.guard import Guard
from core.replay import Replay, run_replay
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments, match_header
from eval import seed_linecheck
from eval.linecheck import dumps, gold

KOBE = "0020500591"  # idx 6: Bryant's three for 47 points, Lakers 73, Raptors 78
RIGHT = "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 78!"
WRONG = "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 79!"
UNDECIDED = "Kobe Bryant from deep, 47 now!"  # 47 a total or not: code can't tell


def _at(idx=6):
    moments = load_moments(KOBE)
    i = next(i for i, m in enumerate(moments) if m["idx"] == idx)
    return match_header(KOBE), moments[i], moments[:i]


class Says:
    """A fake model that answers every call with `text`, keeping each request."""

    def __init__(self, text, record=True):
        self.text, self.record, self.requests = text, record, []

    def call(self, req):
        self.requests.append(json.loads(json.dumps(req)))
        said = self.text
        if req["messages"][-1]["content"].startswith("Producer correction. Reply with exactly"):
            said = req["messages"][-1]["content"].split(": ", 1)[1]
        return {
            "content": [{"type": "text", "text": said}],
            "usage": {"input_tokens": 700, "output_tokens": 300},
            "request_id": f"lc-{len(self.requests)}",
        }


def _labels(**wrong):
    return {f: wrong.get(f, "ok") for f in linecheck.FIELDS}


def test_the_live_request_is_the_seeded_task_byte_for_byte():
    header, m, past = _at()
    fake = Says(dumps(_labels()))
    got = linecheck.check(header, m, past, RIGHT, fake)
    seeded = seed_linecheck.request({"match_id": KOBE, "idx": 6, "text": RIGHT})
    assert json.dumps(fake.requests[0], sort_keys=True) == json.dumps(seeded, sort_keys=True)
    # the fingerprint: system prompt, format, model, no tools; only the message differs by line
    req = fake.requests[0]
    assert req["system"] == linecheck.SYSTEM and req["model"] == linecheck.MODEL
    assert req["output_config"]["format"]["schema"] == linecheck.SCHEMA
    assert "tools" not in req and "tool_choice" not in req
    assert got["labels"] == _labels() and got["wrong"] == []
    assert (got["tokens_in"], got["tokens_out"], got["mubit_request_id"]) == (700, 300, "lc-1")


def test_a_reply_that_isnt_the_canonical_line_flags_nothing():
    header, m, past = _at()
    got = linecheck.check(header, m, past, RIGHT, Says("The score is wrong."))
    assert got["labels"] is None and got["wrong"] == []


def test_offline_there_is_no_second_opinion(monkeypatch):
    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    monkeypatch.setattr("agent.commentator._provider", None)
    header, m, past = _at()
    line = {"line_id": "x", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}
    assert linecheck.live_check(line, m, past) is None


def _moments(n=4):
    return [
        {"sport": "football", "match_id": "m", "idx": i, "clock": f"{i:02d}:00", "type": "Shot"}
        for i in range(n)
    ]


def _commentate(m, history):
    line = {"line_id": f"l{m['idx']}", "match_id": "m", "moment_idx": m["idx"], "text": "Shot!"}
    if m["idx"] == 3:  # the data said in place of a failed try: never checked
        return {**line, "checked": True, "fallback": True, "tried": "Goal!"}
    return {**line, "checked": True}


def test_line_check_never_holds_up_a_line(tmp_path):
    """Every line is out while every check still waits; then each check lands after its line."""
    go, calls = threading.Event(), []

    def slow_check(line, m, past):
        calls.append((line["line_id"], m["idx"], [p["idx"] for p in past]))
        assert go.wait(5)
        return {"labels": _labels(event="wrong"), "wrong": ["event"]}

    replay, store = Replay("m", 1e9), Store(tmp_path)

    async def main():
        run = asyncio.create_task(
            run_replay(replay, _moments(), _commentate, store, linecheck=slow_check)
        )
        for _ in range(200):
            if sum(e["event"] == "line" for e in replay.events) == 4:
                break
            await asyncio.sleep(0.01)
        lines_out = [e["event"] for e in replay.events].count("line")
        checks_out = [e["event"] for e in replay.events].count("linecheck")
        go.set()
        await run
        return lines_out, checks_out

    lines_out, checks_out = asyncio.run(main())
    assert (lines_out, checks_out) == (4, 0)
    # the fallback line goes unchecked; each check sees only the moments before its own
    assert sorted(calls) == [("l0", 0, []), ("l1", 1, [0]), ("l2", 2, [0, 1])]
    names = [e["event"] for e in replay.events]
    assert names.count("linecheck") == 3 and replay.done
    at = {(e["event"], e["data"].get("line_id")): i for i, e in enumerate(replay.events)}
    for e in (e for e in replay.events if e["event"] == "linecheck"):
        assert at["line", e["data"]["line_id"]] < at["linecheck", e["data"]["line_id"]]
        assert e["data"]["wrong"] == ["event"] and e["data"]["created_at"]
    assert sorted(r["line_id"] for r in store.all("linechecks")) == ["l0", "l1", "l2"]


def test_a_failed_check_loses_only_its_second_opinion(tmp_path):
    def down(line, m, past):
        raise ConnectionError("mubit down")

    replay, store = Replay("m", 1e9), Store(tmp_path)
    asyncio.run(run_replay(replay, _moments(2), _commentate, store, linecheck=down))
    names = [e["event"] for e in replay.events]
    assert names.count("line") == 2 and "linecheck" not in names and "error" not in names
    assert store.all("linechecks") == []


def _app(tmp_path, check, guard=None, teach=None):
    def commentate(m, history):  # moment 6's line only; the rest say nothing
        if m["idx"] == 6:
            return {"line_id": "k6", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}

    store = Store(tmp_path)
    deps = Deps(
        list_matches,
        load_moments,
        commentate,
        correct=lambda line, text, reason="": {"mubit_request_id": "fix-1", "reply_passed": True},
        linecheck=check,
        teach=teach,
    )
    return TestClient(create_app(store=store, deps=deps, guard=guard)), store


def _only_six(line, m, past):
    if m["idx"] != 6:
        return None  # one check is enough here
    return {
        "labels": _labels(score="wrong"),
        "wrong": ["score"],
        "model": linecheck.MODEL,
        "tokens_in": 700,
        "tokens_out": 300,
    }


def test_a_flag_reaches_the_fix_queue_and_stats(tmp_path):
    client, store = _app(tmp_path, _only_six)
    with client:
        rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e9, "start_idx": 6})
        events = read_stream(client, rid.json()["replay_id"])
        queued = client.get("/review").json()
        stats = client.get("/stats").json()
    checks = [d for n, d in events if n == "linecheck"]
    assert [c["line_id"] for c in checks] == ["k6"] and checks[0]["wrong"] == ["score"]
    # the rules passed the line; Line check's flag puts it in the producer's queue all the same
    entry = next(q for q in queued if q["line_id"] == "k6")
    assert entry["wrong"] == ["Checker model: score may be wrong"] and entry["text"] == RIGHT
    assert {k: v for k, v in stats["linecheck"].items() if k != "heldout"} == {
        "checked": 1,
        "flags": 1,
        "rules_missed": 1,
        "fixes_sent": 0,
        "examples_today": 0,
        "examples_today_by_kind": {},
    }


def test_no_check_past_the_daily_cap(tmp_path, monkeypatch):
    calls = []

    class Spent(Guard):  # under the cap as the replay starts, over it by its first line
        def __init__(self):
            super().__init__({"DAILY_BUDGET_USD": "1"})
            self.reads = 0

        def off_air(self, store):
            self.reads += 1
            return self.reads > 1

    client, store = _app(tmp_path, lambda *a: calls.append(a) or _only_six(*a), Spent())
    with client:
        rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e9, "start_idx": 6})
        events = read_stream(client, rid.json()["replay_id"])
    assert any(n == "line" for n, _ in events) and calls == []
    assert store.all("linechecks") == []


def test_a_check_counts_toward_the_daily_spend(tmp_path):
    store = Store(tmp_path)
    today = datetime.now(UTC).isoformat(timespec="seconds")
    store.append(
        "linechecks",
        {
            "line_id": "k6",
            "model": linecheck.MODEL,
            "tokens_in": 1_000_000,
            "tokens_out": 0,
            "created_at": today,
        },
    )
    assert guard_mod.spent(store, today[:10]) == 2.0  # Sonnet's input price, $2 per 1M


def test_a_fix_with_a_wrong_reason_teaches_line_check_once(tmp_path):
    fake = Says(dumps(_labels(event="wrong")))  # the model disagrees with code on the event

    def teach(line):
        return linecheck.teach(line, provider=fake)

    client, store = _app(tmp_path, None, teach=teach)
    with client:
        store.append("lines", {"line_id": "w", "match_id": KOBE, "moment_idx": 6, "text": WRONG})
        fix = {"corrected_text": RIGHT, "reason": "Wrong score"}
        assert client.post("/lines/w/fix", json=fix).status_code == 200
        for _ in range(100):  # sent after the fix is answered
            if store.all("linecheck_fixes"):
                break
            time.sleep(0.02)
        tone = {"corrected_text": RIGHT, "reason": "Tone"}
        assert client.post("/lines/w/fix", json=tone).status_code == 200
        time.sleep(0.1)
        stats = client.get("/stats").json()
        shown = client.get("/lines/w").json()["linecheck_example"]
        store.append("linecheck_fixes", {"line_id": "x", "kind": "error", "created_at": "2026"})
        store.append("linecheck_fixes", {"line_id": "y", "kind": "matched", "created_at": "2020"})
        later = client.get("/stats").json()["linecheck"]
    # the line shows the example its fix sent: the correction turn's request id and the kind
    assert (shown["mubit_request_id"], shown["kind"]) == ("lc-2", "corrected")
    assert stats["linecheck"]["examples_today_by_kind"] == {"corrected": 1}
    # a failed send is no example, and an earlier day's counts in total but not today
    assert (later["fixes_sent"], later["examples_today"]) == (2, 1)
    key = gold(*_at(), WRONG)
    assert key["score"] == "wrong"  # the line as first said is the example, not the fix
    assert store.all("linecheck_fixes")[0]["gold"] == dumps(key)
    assert stats["linecheck"]["fixes_sent"] == 1  # Tone teaches nothing
    first, again = fake.requests
    assert WRONG in first["messages"][0]["content"] and len(first["messages"]) == 1
    assert again["messages"][-1]["content"] == CORRECTION.format(text=dumps(key))


def test_a_fix_code_cannot_label_sends_nothing():
    fake = Says(dumps(_labels()))
    line = {"line_id": "u", "match_id": KOBE, "moment_idx": 6, "text": UNDECIDED}
    assert linecheck.teach(line, provider=fake) is None and fake.requests == []


def test_a_matching_reply_is_one_call_and_no_correction():
    fake = Says(dumps(gold(*_at(), RIGHT)))
    line = {"line_id": "r", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}
    sent = linecheck.teach(line, provider=fake)
    assert (sent["kind"], sent["mubit_request_id"]) == ("matched", "lc-1") and len(
        fake.requests
    ) == 1


def test_a_held_out_match_or_no_recorder_sends_nothing(monkeypatch):
    fake = Says(dumps(_labels()))
    held = {"line_id": "h", "match_id": "9636", "moment_idx": 6, "text": "Ocon leads on lap 29!"}
    assert linecheck.teach(held, provider=fake) is None and fake.requests == []
    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    monkeypatch.delenv("MUBIT_FALLBACK_KEY", raising=False)
    monkeypatch.setattr("agent.commentator._provider", None)
    monkeypatch.setattr("agent.commentator._trainer", None)
    line = {"line_id": "r", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}
    assert linecheck.teach(line) is None  # FakeProvider records nothing: no example


def test_the_eval_scores_line_check_beside_the_rules_offline(tmp_path, capsys):
    from eval import checker_eval, linecheck_eval

    labels = [x for x in checker_eval.load() if not x.get("reply")][:6]
    out = linecheck_eval.compare(labels, Says(dumps(_labels(score="wrong"))))
    model, rules = out["line_check"]["overall"], out["rules"]["overall"]
    assert model["lines"] == rules["lines"] == 6 and out["errors"] == 0
    assert model["tp"] + model["fp"] == 6  # it flagged every line, so every line counts as a flag
    path = tmp_path / "held_out.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in labels))
    assert (
        linecheck_eval.main(["--dry", str(path), "--json", str(tmp_path / "r.json")], env={}) == 0
    )
    shown = capsys.readouterr().out
    assert "| Rules check | 6 |" in shown and "| Line check | 6 |" in shown
    assert linecheck_eval.main([], env={}) == 2  # no key: never a call
    # the counts /stats serves (#317), as the table: FakeProvider flags nothing
    rules = checker_eval.evaluate(labels)["overall"]
    assert json.loads((tmp_path / "r.json").read_text()) == {
        "labels": "held_out.jsonl",
        "lines": 6,
        "wrong": rules["tp"] + rules["fn"],
        "rules": {"caught": rules["tp"], "false_alarms": rules["fp"]},
        "line_check": {"caught": 0, "false_alarms": 0},
        "errors": 0,
    }


def test_stats_serve_the_held_out_result_the_eval_wrote(tmp_path, monkeypatch):
    from core import stats as stats_mod
    from eval import linecheck_eval

    # the shape --json writes (web/src/proof.test.ts reads the same fixture)
    fixture = Path(__file__).parent / "fixtures" / "linecheck_heldout.json"
    result = json.loads(fixture.read_text())
    rules = {"overall": {"lines": 288, "tp": 1, "fn": 4, "fp": 0}}
    model = {"overall": {"tp": 3, "fp": 5}}
    out = {"rules": rules, "line_check": model, "errors": 0}
    assert linecheck_eval.summary("heldout_labels.jsonl", out) == result
    store = Store(tmp_path / "store")
    monkeypatch.setattr(stats_mod, "HELDOUT", tmp_path / "linecheck_heldout.json")
    assert stats_mod.stats(store)["linecheck"]["heldout"] is None  # no file: nothing claimed
    monkeypatch.setattr(stats_mod, "HELDOUT", fixture)
    assert stats_mod.stats(store)["linecheck"]["heldout"] == result
