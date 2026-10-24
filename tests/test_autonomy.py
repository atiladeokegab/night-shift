"""#204: every call is counted as passed first time, fixed by the retry, or sent to a human, and
a call whose retry fails is queued for the producer with the check's reason while the fallback is
still said. /stats and the Proof card read the same counts."""

import asyncio
import uuid

from fastapi.testclient import TestClient

from core import insight, review
from core.app import Deps, create_app
from core.replay import Replay, run_replay
from core.stats import stats
from core.store import Store
from data.matches import list_matches, load_moments, match_header

KOBE, CRICKET = "0020500591", "1298150"
WRONG = "Fifty-eight for Bryant!"  # 58 is in none of Kobe's first moments
FINE = "What a play!"


def calls(texts: dict[int, list[str]]):
    """A commentator saying, for each moment idx, its texts in turn (the last one again after)."""
    said: dict[int, int] = {}

    def commentate(m, history):
        seq = texts.get(m["idx"], [m["detail"].get("milestone", FINE)])  # a milestone is said
        n = said[m["idx"]] = said.get(m["idx"], -1) + 1
        text = seq[min(n, len(seq) - 1)]
        return {
            "line_id": uuid.uuid4().hex,
            "match_id": m["match_id"],
            "moment_idx": m["idx"],
            "text": text,
        }

    return commentate


def test_checked_marks_a_kept_retry_and_keeps_a_failed_try_for_the_producer():
    m = load_moments(KOBE)[0]
    first = insight.checked(calls({}), m, [])
    assert first["text"] == FINE and first["checked"]
    assert not {"retried", "fallback", "tried"} & first.keys()
    again = insight.checked(calls({0: [WRONG, FINE]}), m, [])
    assert again["text"] == FINE and again["retried"] and again["checked"]
    assert again["rejected"]["text"] == WRONG
    gave_up = insight.checked(calls({0: [WRONG]}), m, [])
    assert gave_up["fallback"] and gave_up["text"] == insight.fallback_text(match_header(KOBE), m)
    assert (
        gave_up["checked"]
        and gave_up["tried"] == WRONG
        and gave_up["wrong"] == ["58 is not in the moment"]
    )


def test_a_fallback_line_is_served_by_no_model_and_a_kept_retry_by_its_own(monkeypatch):
    # #250: the data-built line must not carry the rejected reply's model or adapter
    m = load_moments(KOBE)[0]

    def served(texts):
        said = calls(texts)
        models = iter(["adapter-test", "adapter-retry"])
        return lambda moment, history: {**said(moment, history), "served_by": next(models)}

    gave_up = insight.checked(served({0: [WRONG]}), m, [])
    assert gave_up["fallback"] and gave_up["served_by"] is None and gave_up["tried"] == WRONG
    kept = insight.checked(served({0: [WRONG, FINE]}), m, [])
    assert kept["text"] == FINE and kept["served_by"] == "adapter-retry"
    first = insight.checked(served({}), m, [])
    assert first["served_by"] == "adapter-test"


def replay(store, match_id, texts, n=6):
    moments = load_moments(match_id)[:n]
    r = Replay(match_id, 1e9)
    asyncio.run(run_replay(r, moments, calls(texts), store))
    return [e["data"] for e in r.events if e["event"] == "line"]


def test_a_failed_retry_is_said_as_the_fallback_and_queued_with_the_checks_reason(tmp_path):
    store = Store(tmp_path)
    said = replay(store, KOBE, {1: [WRONG, FINE], 2: [WRONG]})
    m2 = load_moments(KOBE)[2]
    assert said[2]["text"] == insight.fallback_text(match_header(KOBE), m2)  # still spoken
    queued = review.queue(store, Deps(list_matches, load_moments, lambda m, h: None))
    assert [(q["moment_idx"], q["text"], q["wrong"]) for q in queued] == [
        (2, WRONG, ["58 is not in the moment"])
    ]
    assert queued[0]["line_id"] == said[2]["line_id"]  # a fix trains on the failed request


def test_stats_count_each_call_per_match_and_overall(tmp_path):
    store = Store(tmp_path)
    replay(store, KOBE, {1: [WRONG, FINE], 2: [WRONG], 3: [WRONG]})  # 6 calls: 3, 1, 2
    replay(store, CRICKET, {0: [WRONG, FINE]}, n=4)  # 4 calls: 3, 1, 0
    store.append("lines", {"line_id": "a", "text": "A stat.", "speaker": "analyst"})
    reply = {"match_id": KOBE, "after_idx": 4, "heard": "x"}
    store.append("lines", {"line_id": "r", "text": FINE, "speaker": "lead", "reply": reply})
    s = stats(store)
    kobe = {"called": 6, "first_time": 3, "auto_fixed": 1, "to_human": 2}
    cricket = {"called": 4, "first_time": 3, "auto_fixed": 1, "to_human": 0}
    assert s["autonomy_by_match"] == {KOBE: kobe, CRICKET: cricket}
    assert s["autonomy"] == {"called": 10, "first_time": 6, "auto_fixed": 2, "to_human": 2}


def test_a_line_the_check_never_saw_is_not_counted_as_a_pass(tmp_path):
    store = Store(tmp_path)
    old = {"match_id": KOBE, "speaker": "lead"}  # said before the check existed: no `checked`
    store.append("lines", {**old, "line_id": "old", "text": WRONG})
    store.append("lines", {**old, "line_id": "new", "text": FINE, "checked": True})
    assert stats(store)["autonomy"] == {
        "called": 1,
        "first_time": 1,
        "auto_fixed": 0,
        "to_human": 0,
    }


def test_the_stats_route_and_the_replays_stats_event_give_the_same_counts(tmp_path):
    store = Store(tmp_path)
    r = Replay(KOBE, 1e9)
    asyncio.run(run_replay(r, load_moments(KOBE)[:6], calls({1: [WRONG, FINE], 2: [WRONG]}), store))
    event = [e["data"] for e in r.events if e["event"] == "stats"][-1]  # the card's live numbers
    deps = Deps(list_matches, load_moments, lambda m, h: None)
    with TestClient(create_app(store=store, deps=deps)) as c:
        route = c.get("/stats").json()  # the card's first numbers
    counts = {"called": 6, "first_time": 4, "auto_fixed": 1, "to_human": 1}
    assert route["autonomy"] == event["autonomy"] == counts
    assert route["autonomy_by_match"] == event["autonomy_by_match"] == {KOBE: counts}


WORSE = "Ninety-nine for Bryant!"  # wrong too, and not the first try


def test_the_queued_try_is_the_retrys_text_under_the_retrys_line_id(tmp_path):
    store = Store(tmp_path)
    said = replay(store, KOBE, {2: [WRONG, WORSE]})
    queued = review.queue(store, Deps(list_matches, load_moments, lambda m, h: None))
    assert [(q["line_id"], q["text"]) for q in queued] == [(said[2]["line_id"], WORSE)]


def test_two_failed_tries_at_one_moment_stay_two_queue_entries(tmp_path):
    store = Store(tmp_path)
    replay(store, KOBE, {2: [WRONG]})
    replay(store, KOBE, {2: [WORSE]})  # the same fallback said, a different try behind it
    queued = review.queue(store, Deps(list_matches, load_moments, lambda m, h: None))
    assert [q["text"] for q in queued] == [WORSE, WRONG]
