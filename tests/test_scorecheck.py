"""Score check (#321): the frozen task, its seeding (gold from event data, idempotent, held-out
never sent), its held-out scorer, and a producer's fix sent as one example."""

import hashlib
import json
import time

from fastapi.testclient import TestClient

from agent import scorecheck
from agent.commentator import CORRECTION
from core.app import Deps, create_app
from core.store import Store
from data.matches import list_matches, load_moments, match_header
from eval import seed_scorecheck
from eval.linecheck import HELD_OUT, example_id, gold
from tests.test_linecheck import _lines
from tests.test_linecheck_live import KOBE, RIGHT, UNDECIDED, WRONG, Says, _at


def test_the_task_is_pinned():
    """Any change to the prompt, format or model starts a new Mubit task: edit these on purpose."""
    assert (
        hashlib.sha256(scorecheck.SYSTEM.encode()).hexdigest()
        == "8b61b7c52ad58f534ff7e5e8ff4f12b30a42fac77eea46de2daac3b019c90de7"
    )
    req = scorecheck.request(scorecheck.MESSAGE.template, "M", 0)
    digest = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
    assert digest == "a7baec167fd7fb2a4859a00abca67b33e6fbf9bfa3cc23b68f945f6d24ffc659"


def test_parse_takes_only_the_canonical_answer():
    assert scorecheck.parse('{"score":"wrong"}') == "wrong"
    assert scorecheck.parse('{"score": "ok"}') == "ok"
    for bad in ("ok", '{"score":"maybe"}', '{"score":"ok","x":1}', "", None):
        assert scorecheck.parse(bad) is None


def test_every_example_is_labelled_by_code_and_held_out_never_trains():
    exs = seed_scorecheck.examples(_lines())
    assert exs
    for e in exs:
        moments = load_moments(e["match_id"])
        i = next(i for i, m in enumerate(moments) if m["idx"] == e["idx"])
        assert (
            gold(match_header(e["match_id"]), moments[i], moments[:i], e["text"])["score"]
            == (e["gold"])
        )
        assert e["held_out"] == (e["match_id"] in HELD_OUT)
    assert all(not e["held_out"] for e in seed_scorecheck.batch(exs, 100))


def test_batch_takes_labels_in_turn_and_a_larger_batch_keeps_the_smaller():
    exs = [
        {"id": f"{g}{n}", "gold": g, "held_out": False, "match_id": "x"}
        for g in ("ok", "wrong", "not_said")
        for n in range(10)
    ]
    first = seed_scorecheck.batch(exs, 6)
    assert sorted(e["gold"] for e in first) == ["not_said"] * 2 + ["ok"] * 2 + ["wrong"] * 2
    assert seed_scorecheck.batch(exs, 12)[:6] == first


def test_go_sends_each_example_once(tmp_path):
    store = Store(tmp_path)
    exs = seed_scorecheck.batch(seed_scorecheck.examples(_lines()), 50)
    fake = Says('{"score":"ok"}')
    tally = seed_scorecheck.go(exs, fake, store, workers=1)
    rows = store.all("scorecheck_examples")
    assert len(rows) == len(exs) and tally["skipped"] == 0
    assert all(r["source"] == "seed" and r["mubit_request_id"] for r in rows)
    calls = len(fake.requests)
    again = seed_scorecheck.go(exs, fake, store, workers=1)
    assert again["skipped"] == len(exs) and len(fake.requests) == calls  # a rerun sends nothing


def test_a_reply_off_the_gold_gets_the_correction_turn():
    ex = {"id": "w", "match_id": KOBE, "idx": 6, "text": WRONG, "gold": "wrong"}
    fake = Says('{"score":"ok"}')
    sent = seed_scorecheck.send(ex, fake)
    assert (sent["kind"], sent["mubit_request_id"]) == ("corrected", "lc-2")
    assert fake.requests[-1]["messages"][-1]["content"] == CORRECTION.format(
        text='{"score":"wrong"}'
    )


def test_score_counts_agreement_on_held_out_lines_only():
    exs = [
        {"id": "a", "gold": "ok", "held_out": True},
        {"id": "b", "gold": "wrong", "held_out": True},
        {"id": "c", "gold": "ok", "held_out": False},
    ]
    rows = [{"id": "a", "output": '{"score":"ok"}'}, {"id": "b", "output": "nope"}]
    rows.append({"id": "c", "output": '{"score":"ok"}'})
    r = seed_scorecheck.score(exs, rows)
    assert (r["scored"], r["agree"], r["unparsed"], r["held_out"]) == (2, 1, 1, 2)
    assert r["by_gold"]["ok"] == [1, 1] and r["by_gold"]["wrong"] == [0, 1]


def test_the_frozen_held_out_set_is_held_out_and_labelled():
    with open(seed_scorecheck.HELD, encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    assert len(rows) >= 50 and all(r["match_id"] in HELD_OUT for r in rows)
    assert {r["gold"] for r in rows} <= set(scorecheck.LABELS)


def test_teach_sends_nothing_it_cannot_label_or_already_sent():
    fake = Says('{"score":"ok"}')
    line = {"line_id": "u", "match_id": KOBE, "moment_idx": 6, "text": UNDECIDED}
    assert scorecheck.teach(line, provider=fake) is None
    held = {"line_id": "h", "match_id": "3913122", "moment_idx": 8, "text": "Brighton one nil!"}
    assert scorecheck.teach(held, provider=fake) is None
    right = {"line_id": "r", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}
    assert scorecheck.teach(right, {example_id(KOBE, 6, RIGHT)}, provider=fake) is None
    assert fake.requests == []
    assert scorecheck.teach(right, provider=fake)["kind"] == "matched"
    assert gold(*_at(), RIGHT)["score"] == "ok"


def test_a_fix_sends_the_line_and_the_fixed_text_as_score_check_examples(tmp_path):
    fake = Says('{"score":"ok"}')  # Claude says ok; the data says the line's score is wrong

    def commentate(m, history):
        return None

    store = Store(tmp_path)
    deps = Deps(
        list_matches,
        load_moments,
        commentate,
        correct=lambda line, text, reason="": {"mubit_request_id": "fix-1", "reply_passed": True},
        score_teach=lambda line, sent: scorecheck.teach(line, sent, provider=fake),
    )
    client = TestClient(create_app(store=store, deps=deps))
    with client:
        store.append("lines", {"line_id": "w", "match_id": KOBE, "moment_idx": 6, "text": WRONG})
        # the review page's reason, never a Wrong one: every fix reached no example before
        fix = {"corrected_text": RIGHT, "reason": "fix list: wrong number"}
        ids = []
        for n in (1, 2):  # the same line fixed twice is still two examples
            got = client.post("/lines/w/fix", json=fix)
            assert got.status_code == 200
            ids.append(got.json()["fix_uid"])
            for _ in range(200):  # the receipt is written last, once the send ends
                if len(store.all("scorecheck_receipts")) == n:
                    break
                time.sleep(0.02)
        line = client.get("/lines/w").json()
    rows = store.all("scorecheck_examples")
    assert [(r["source"], r["kind"], r["gold"], r["line_id"], r["text"]) for r in rows] == [
        ("fix", "corrected", "wrong", "w", WRONG),
        ("fix", "matched", "ok", "w", RIGHT),
    ]
    # the review page's training panel (#400): each example names the fix that sent it, and each
    # fix's receipt says how many went: the second sent none (each example goes once ever)
    assert ids[0] != ids[1] and [r["fix_uid"] for r in rows] == [ids[0], ids[0]]
    assert line["scorecheck_examples"] == rows
    assert [(r["fix_uid"], r["sent"], r["failed"]) for r in line["scorecheck_receipts"]] == [
        (ids[0], 2, False),
        (ids[1], 0, False),
    ]


def test_a_failed_score_check_send_gets_a_failed_receipt(tmp_path):
    def boom(line, sent):
        raise RuntimeError("mubit down")

    store = Store(tmp_path)
    deps = Deps(
        list_matches,
        load_moments,
        lambda m, history: None,
        correct=lambda line, text, reason="": {"mubit_request_id": "fix-1", "reply_passed": True},
        score_teach=boom,
    )
    with TestClient(create_app(store=store, deps=deps)) as client:
        store.append("lines", {"line_id": "w", "match_id": KOBE, "moment_idx": 6, "text": WRONG})
        fix = client.post("/lines/w/fix", json={"corrected_text": RIGHT}).json()
        for _ in range(200):
            if store.all("scorecheck_receipts"):
                break
            time.sleep(0.02)
    [receipt] = store.all("scorecheck_receipts")
    assert (receipt["fix_uid"], receipt["sent"], receipt["failed"]) == (fix["fix_uid"], 0, True)


def test_fixes_made_before_now_are_sent_once_and_counted(tmp_path):
    from core.stats import stats

    fake = Says('{"score":"ok"}')
    store = Store(tmp_path)
    store.append("lines", {"line_id": "w", "match_id": KOBE, "moment_idx": 6, "text": WRONG})
    store.append("fixes", {"line_id": "w", "corrected_text": RIGHT, "reason": "Tone"})
    store.append("fixes", {"line_id": "gone", "corrected_text": RIGHT, "reason": "Tone"})

    def teach(line, sent):
        return scorecheck.teach(line, sent, provider=fake)

    assert seed_scorecheck.fixes(store, teach) == {"corrected": 1, "matched": 1}
    assert seed_scorecheck.fixes(store, teach) == {}  # a rerun sends nothing again
    sc = stats(store)["scorecheck"]
    assert sc["by_source"]["human"] == 2 and sc["from_fixes_by_kind"] == {
        "corrected": 1,
        "matched": 1,
    }


def test_stats_show_examples_by_source_and_each_held_out_score(tmp_path):
    from core.stats import stats

    store = Store(tmp_path)
    for source, kind in (("seed", "matched"), ("seed", "corrected"), ("fix", "corrected")):
        store.append("scorecheck_examples", {"id": kind + source, "kind": kind, "source": source})
    for agree in (60, 70):  # the latest per model counts
        store.append("scorecheck_evals", {"what": "Claude", "agree": agree, "scored": 74})
    sc = stats(store)["scorecheck"]
    assert (sc["examples_sent"], sc["from_fixes_by_kind"]) == (3, {"corrected": 1})
    assert sc["by_source"] == {"answer_key": 2, "auto_fixed": 0, "human": 1}
    assert [(w, e["agree"], e["scored"]) for w, e in sc["held_out"].items()] == [("Claude", 70, 74)]
