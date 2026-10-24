"""#399: a line is recorded to Mubit only once it passed the number check, and `recorded` is True
only for a recorded reply that passed it too. Fake Mubit clients throughout: nothing is sent."""

import asyncio

from agent import commentator
from core.replay import Replay, run_replay
from core.store import Store
from tests.test_commentator import FOOT, GOAL, moment
from tests.test_linecheck_live import _commentate, _moments


class Fake:
    """A Mubit client that says `texts` in turn and counts its calls."""

    def __init__(self, *texts, record=False):
        self.texts, self.record, self.calls = list(texts), record, 0

    def call(self, request):
        self.calls += 1
        text = self.texts.pop(0)
        return {
            "request_id": f"r{self.calls}",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "first_word_ms": None,
        }


def test_a_live_line_is_made_unrecorded(monkeypatch):
    lent, unrec = Fake(record=True), Fake("Ann saves it!")
    monkeypatch.setattr(commentator, "_provider", lent)
    monkeypatch.setattr(commentator, "_unrecorded", unrec)
    line = commentator.commentate(moment(FOOT, 0), [], FOOT)
    assert line["text"] == "Ann saves it!" and (lent.calls, unrec.calls) == (0, 1)


def test_a_checked_line_is_sent_again_recorded_and_its_reply_checked_too():
    moments = [moment(FOOT, 0, **GOAL)]
    passes, fails = Fake("Goal for Ann!", record=True), Fake("Ann makes it 3-0!", record=True)
    assert commentator.recorded(FOOT, moments, 0, provider=passes)["recorded"] is True
    assert commentator.recorded(FOOT, moments, 0, provider=fails)["recorded"] is False
    assert (passes.calls, fails.calls) == (1, 1)


def test_nothing_is_sent_without_a_recording_provider_or_for_an_analyst_line():
    off, on = Fake(), Fake(record=True)
    stat = [moment(FOOT, 0), {**moment(FOOT, 1), "type": "Stat"}]
    assert commentator.recorded(FOOT, [moment(FOOT, 0)], 0, provider=off) is None
    assert commentator.recorded(FOOT, stat, 1, provider=on) is None
    assert (off.calls, on.calls) == (0, 0)


def test_a_fix_whose_recorded_reply_fails_is_not_called_recorded(monkeypatch):
    # the first, unrecorded reply passes; the recorded one Mubit makes does not
    trainer = Fake("Ann makes it 3-0!", record=True)
    monkeypatch.setattr(commentator, "correction_provider", lambda: trainer)
    moments = [moment(FOOT, 0, **GOAL)]
    line = {"match_id": FOOT["match_id"], "moment_idx": 0, "text": "Ann misses!"}
    sent = commentator.correct(line, "Ann scores!", FOOT, moments, provider=Fake("Goal for Ann!"))
    assert trainer.calls == 1 and sent["reply_passed"] is False and sent["recorded"] is False


def test_a_replay_records_each_checked_line_once_and_never_a_fallback(tmp_path):
    sent = []

    def record(m, history):
        sent.append((m["idx"], [p["idx"] for p in history]))
        return {"recorded": True}

    replay, store = Replay("m", 1e9), Store(tmp_path)
    asyncio.run(run_replay(replay, _moments(), _commentate, store, record=record))
    # idx 3 is the data said in place of a failed try: never recorded
    assert sorted(sent) == [(0, []), (1, [0]), (2, [0, 1])]


def test_a_failed_recording_loses_only_the_example(tmp_path):
    def down(m, history):
        raise ConnectionError("mubit down")

    replay, store = Replay("m", 1e9), Store(tmp_path)
    asyncio.run(run_replay(replay, _moments(2), _commentate, store, record=down))
    names = [e["event"] for e in replay.events]
    assert names.count("line") == 2 and "error" not in names
