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
    assert first["text"] == FINE and not {"retried", "fallback", "tried"} & first.keys()
    again = insight.checked(calls({0: [WRONG, FINE]}), m, [])
    assert again["text"] == FINE and again["retried"] and again["rejected"]["text"] == WRONG
    gave_up = insight.checked(calls({0: [WRONG]}), m, [])
    assert gave_up["fallback"] and gave_up["text"] == insight.fallback_text(match_header(KOBE), m)
    assert gave_up["tried"] == WRONG and gave_up["wrong"] == ["58 is not in the moment"]


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


def test_a_retry_stored_before_the_flag_is_known_by_its_auto_fix(tmp_path):
    store = Store(tmp_path)
    store.append("lines", {"line_id": "k", "match_id": KOBE, "text": "Kept.", "speaker": "lead"})
    store.append("lines", {"line_id": "f", "match_id": KOBE, "text": "Fine.", "speaker": "lead"})
    store.append("auto_fixes", {"line_id": "rejected", "corrected_text": "Kept."})
    assert stats(store)["autonomy"] == {
        "called": 2,
        "first_time": 1,
        "auto_fixed": 1,
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
