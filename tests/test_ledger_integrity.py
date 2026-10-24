"""Regressions for correction identity and concurrent ledger cache misses."""

import threading
from concurrent.futures import ThreadPoolExecutor

from core import ledger
from core.app import Deps
from core.store import Store
from data.matches import list_matches, load_moments


def deps():
    return Deps(list_matches, load_moments, lambda *_: None)


def append_auto_fix(store, *, line_id, corrected_text, request_id="request"):
    store.append(
        "auto_fixes",
        {
            "line_id": line_id,
            "corrected_text": corrected_text,
            "mubit_request_id": request_id,
            "recorded": True,
            "created_at": "2026-10-24T20:00:00Z",
        },
    )


def retry(store, line_id, match_id, text, idx=0):
    store.append(
        "lines",
        {
            "line_id": line_id,
            "match_id": match_id,
            "moment_idx": idx,
            "text": text,
            "retried": True,
        },
    )


def test_duplicate_corrected_text_across_matches_stays_unattributed(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_cache", {})
    store = Store(tmp_path)
    retry(store, "retry-a", "3869685", "What a goal!")
    retry(store, "retry-b", "3754092", "What a goal!")
    append_auto_fix(store, line_id="rejected-not-stored", corrected_text="What a goal!")

    row = ledger.ledger(store, deps())["rows"][0]

    assert row["match_id"] is None
    assert row["session"] is None
    assert row["idx"] is None


def test_auto_fix_uses_rejected_line_identity_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_cache", {})
    store = Store(tmp_path)
    store.append(
        "lines",
        {
            "line_id": "rejected",
            "match_id": "3869685",
            "moment_idx": 0,
            "text": "Original line",
        },
    )
    retry(store, "retry-a", "3869685", "What a goal!")
    retry(store, "retry-b", "3754092", "What a goal!")
    append_auto_fix(store, line_id="rejected", corrected_text="What a goal!")

    row = ledger.ledger(store, deps())["rows"][0]

    assert row["match_id"] == "3869685"
    assert row["idx"] == 0
    assert row["session"] == "match-football-3869685"


def test_duplicate_text_with_same_moment_identity_is_still_resolvable(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_cache", {})
    store = Store(tmp_path)
    retry(store, "retry-a", "3869685", "What a goal!", idx=0)
    retry(store, "retry-b", "3869685", "What a goal!", idx=0)
    append_auto_fix(store, line_id="rejected-not-stored", corrected_text="What a goal!")

    row = ledger.ledger(store, deps())["rows"][0]

    assert row["match_id"] == "3869685"
    assert row["idx"] == 0
    assert row["session"] == "match-football-3869685"


def test_concurrent_cold_polls_share_one_build(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_cache", {})
    store = Store(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    contending = threading.Event()

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.owner_lock = threading.Lock()
            self.first_thread = None

        def __enter__(self):
            thread_id = threading.get_ident()
            with self.owner_lock:
                if self.first_thread is None:
                    self.first_thread = thread_id
                elif thread_id != self.first_thread:
                    contending.set()
            self.lock.acquire()

        def __exit__(self, *_):
            self.lock.release()

    monkeypatch.setattr(ledger, "_cache_lock", ObservedLock(), raising=False)

    def slow_build(*_):
        calls.append(1)
        if len(calls) > 1:
            contending.set()
        entered.set()
        assert release.wait(timeout=2)
        return {"sent": 1, "rows": []}

    monkeypatch.setattr(ledger, "ledger", slow_build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(ledger.cached, store, deps())
        assert entered.wait(timeout=2)
        second = pool.submit(ledger.cached, store, deps())
        assert contending.wait(timeout=2)
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert calls == [1]


def test_cached_results_are_isolated_by_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_cache", {})
    calls = []

    def build(store, _):
        result = {"sent": len(calls) + 1, "rows": []}
        calls.append(store)
        return result

    monkeypatch.setattr(ledger, "ledger", build)
    first, second = Store(tmp_path / "first"), Store(tmp_path / "second")

    assert ledger.cached(first, deps())["sent"] == 1
    assert ledger.cached(second, deps())["sent"] == 2
    assert calls == [first, second]
