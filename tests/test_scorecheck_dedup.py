from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Lock

from core.store import Store
from eval.seed_scorecheck import send_fix


def _row(text):
    return {"id": text, "kind": "matched", "mubit_request_id": f"request-{text}"}


def test_concurrent_fixes_send_a_content_id_once(tmp_path):
    store = Store(tmp_path)
    rendezvous = Barrier(2)
    calls = []
    calls_lock = Lock()

    def teach(line, sent):
        content_id = line["text"]
        if content_id in sent:
            return None
        try:
            rendezvous.wait(timeout=0.1)
        except BrokenBarrierError:
            pass
        with calls_lock:
            calls.append(content_id)
        return _row(content_id)

    line = {"line_id": "line-1", "text": "said"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: send_fix(store, line, "fixed", teach), range(2)))

    rows = store.all("scorecheck_examples")
    assert len(calls) == 2  # one send each for the original and corrected content
    assert len(rows) == len({row["id"] for row in rows})
    assert {row["id"] for row in rows} == {"said", "fixed"}


def test_original_and_corrected_content_are_both_kept(tmp_path):
    store = Store(tmp_path)
    calls = []

    def teach(line, sent):
        content_id = line["text"]
        if content_id in sent:
            return None
        calls.append(content_id)
        return _row(content_id)

    send_fix(store, {"line_id": "line-2", "text": "said"}, "fixed", teach)

    assert calls == ["said", "fixed"]
    assert {row["id"] for row in store.all("scorecheck_examples")} == {"said", "fixed"}


def test_failed_send_is_not_recorded_and_can_retry(tmp_path):
    store = Store(tmp_path)
    attempts = {}

    def teach(line, sent):
        content_id = line["text"]
        attempts[content_id] = attempts.get(content_id, 0) + 1
        if attempts[content_id] == 1:
            return {"id": content_id, "kind": "error"}
        return _row(content_id)

    line = {"line_id": "line-3", "text": "said"}
    send_fix(store, line, "fixed", teach)
    assert store.all("scorecheck_examples") == []
    send_fix(store, line, "fixed", teach)

    assert attempts == {"said": 2, "fixed": 2}
    assert {row["id"] for row in store.all("scorecheck_examples")} == {"said", "fixed"}


def test_distinct_stores_can_send_concurrently(tmp_path):
    stores = [Store(tmp_path / "one"), Store(tmp_path / "two")]
    rendezvous = Barrier(2)
    passed = []
    passed_lock = Lock()

    def teach(line, sent):
        content_id = line["text"]
        if content_id in sent:
            return None
        try:
            rendezvous.wait(timeout=1)
        except BrokenBarrierError:
            pass
        else:
            with passed_lock:
                passed.append(content_id)
        return _row(content_id)

    line = {"line_id": "line", "text": "said"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda store: send_fix(store, line, "fixed", teach), stores))

    assert sorted(passed) == ["fixed", "fixed", "said", "said"]
    assert all(
        {row["id"] for row in store.all("scorecheck_examples")} == {"said", "fixed"}
        for store in stores
    )
