"""GcsStore against an in-memory stand-in that behaves like google-cloud-storage: a fresh
`bucket.blob(name)` knows no generation until it is loaded, and writes check if_generation_match."""

import json

from core.store import GcsStore


class PreconditionFailed(Exception):
    pass


class FakeBlob:
    def __init__(self, objects, name, generation=None):
        self.objects, self.name, self.generation = objects, name, generation

    def exists(self):  # like the real client: answers, but does not load the generation
        return self.name in self.objects

    def download_as_text(self, if_generation_match=None):
        self.objects.calls.append("download")
        text, gen = self.objects[self.name]
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed()
        return text

    def upload_from_string(self, text, if_generation_match=None):
        self.objects.calls.append("upload")
        gen = self.objects.get(self.name, ("", 0))[1]
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed()
        self.objects[self.name] = (text, gen + 1)
        self.generation = gen + 1  # the real client loads the new generation from the response


class Objects(dict):
    """name: (text, generation), and every GCS call made, in order."""

    calls: list[str]


class FakeBucket:
    def __init__(self):
        self.objects = Objects()
        self.objects.calls = []

    def blob(self, name):
        return FakeBlob(self.objects, name)

    def get_blob(self, name):
        self.objects.calls.append("metadata")
        if name not in self.objects:
            return None
        return FakeBlob(self.objects, name, self.objects[name][1])


class FakeClient:
    def __init__(self):
        self.b = FakeBucket()

    def bucket(self, name):
        return self.b


def test_sequential_appends_keep_every_record(monkeypatch):
    monkeypatch.setattr("google.api_core.exceptions.PreconditionFailed", PreconditionFailed)
    store = GcsStore("gs://b/prefix", client=FakeClient())
    store.append("lines", {"line_id": "a"})
    store.append("lines", {"line_id": "b"})
    store.append("fixes", {"line_id": "a"})
    assert [r["line_id"] for r in store.all("lines")] == ["a", "b"]
    assert [r["line_id"] for r in store.all("fixes")] == ["a"]


def test_threads_appending_and_reading_at_once_only_ever_see_whole_lines(tmp_path):
    import threading
    import time

    from core.store import Store

    class HalfThenRest(Store):  # a write that lands in two pieces, as a long line can
        def _write(self, kind, text):
            with (self.root / f"{kind}.jsonl").open("a") as f:
                f.write(text[:10])
                f.flush()
                time.sleep(0.02)
                f.write(text[10:])

    store, errors = HalfThenRest(tmp_path), []

    def read():
        try:
            for _ in range(10):
                store.all("lines")
                time.sleep(0.01)
        except ValueError as exc:  # json.JSONDecodeError
            errors.append(exc)

    threads = [
        threading.Thread(target=store.append, args=("lines", {"line_id": f"l{i}"}))
        for i in range(8)
    ]
    threads += [threading.Thread(target=read) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert sorted(r["line_id"] for r in store.all("lines")) == [f"l{i}" for i in range(8)]


def test_a_replay_fetches_each_kind_once_and_stats_match_a_fresh_read(tmp_path):
    """#243: stats() after every line used to read the whole store each time."""
    import asyncio
    from collections import Counter

    from core.replay import Replay, run_replay
    from core.stats import stats
    from core.store import KINDS, Store

    class Counted(Store):
        reads: Counter = Counter()

        def _read(self, kind):
            self.reads[kind] += 1
            return super()._read(kind)

    store = Counted(tmp_path)
    moments = [
        {"sport": "football", "match_id": "m", "idx": i, "clock": f"{i:02d}:00", "type": "Shot"}
        for i in range(20)
    ]

    def commentate(m, history):
        return {"line_id": f"l{m['idx']}", "match_id": "m", "moment_idx": m["idx"], "text": "Shot!"}

    r = Replay("m", 1e9)
    asyncio.run(run_replay(r, moments, commentate, store))
    assert len([e for e in r.events if e["event"] == "stats"]) == 20
    assert stats(store) == stats(Store(tmp_path))  # what /stats says from cold
    assert max(store.reads.values()) == 1 and set(store.reads) <= set(KINDS)


def test_a_write_from_another_process_is_seen(tmp_path, monkeypatch):
    from core.store import Store

    a, b = Store(tmp_path), Store(tmp_path)
    a.append("adapter", {"status": "not_trained"})
    assert a.all("adapter") == [{"status": "not_trained"}]
    b.append("adapter", {"status": "trained"})  # eval/record_adapter.py, say
    assert a.all("adapter")[-1] == {"status": "trained"}
    a.append("adapter", {"status": "again"})
    assert [r["status"] for r in a.all("adapter")] == ["not_trained", "trained", "again"]

    monkeypatch.setattr("google.api_core.exceptions.PreconditionFailed", PreconditionFailed)
    client, now = FakeClient(), [0.0]
    g = GcsStore("gs://b/p", client=client, clock=lambda: now[0])
    h = GcsStore("gs://b/p", client=client)
    g.append("lines", {"line_id": "a"})
    assert len(g.all("lines")) == 1
    h.append("lines", {"line_id": "b"})
    assert len(g.all("lines")) == 1  # within FRESH_S another process's write may not show yet
    now[0] += GcsStore.FRESH_S
    assert [r["line_id"] for r in g.all("lines")] == ["a", "b"]


def test_gcs_reads_and_appends_reuse_the_cached_text(monkeypatch):
    # #156: stats() read every kind after each line (a metadata call each), and every append
    # downloaded the whole object before uploading it again
    monkeypatch.setattr("google.api_core.exceptions.PreconditionFailed", PreconditionFailed)
    client, now = FakeClient(), [0.0]
    calls = client.b.objects.calls
    store = GcsStore("gs://b/p", client=client, clock=lambda: now[0])
    store.append("lines", {"line_id": "a"})
    calls.clear()
    for i in range(5):  # a replay's lines, each followed by its stats read
        store.append("lines", {"line_id": f"l{i}"})
        assert len(store.all("lines")) == i + 2
    assert calls == ["upload"] * 5  # no download, and no metadata call while fresh
    now[0] += GcsStore.FRESH_S
    calls.clear()
    assert len(store.all("lines")) == 6 and calls == ["metadata"]  # unchanged: no download


def test_a_gcs_append_over_another_writers_change_keeps_both(monkeypatch):
    monkeypatch.setattr("google.api_core.exceptions.PreconditionFailed", PreconditionFailed)
    client = FakeClient()
    ours, theirs = GcsStore("gs://b/p", client=client), GcsStore("gs://b/p", client=client)
    ours.append("fixes", {"line_id": "a"})
    theirs.append("fixes", {"line_id": "b"})  # our cached generation is now stale
    ours.append("fixes", {"line_id": "c"})  # the upload is refused, so it fetches theirs first
    text, _ = client.b.objects["p/fixes.jsonl"]
    assert [json.loads(r)["line_id"] for r in text.splitlines()] == ["a", "b", "c"]
    assert [r["line_id"] for r in ours.all("fixes")] == ["a", "b", "c"]


def test_another_process_appending_inside_our_append_is_not_lost(tmp_path):
    from core.store import Store

    other, race = Store(tmp_path), []

    class Racing(Store):  # another process appends between our stamp and our write
        def _write(self, kind, text):
            if race:
                other.append(kind, {"line_id": "theirs"})
            super()._write(kind, text)

    ours = Racing(tmp_path)
    ours.append("lines", {"line_id": "first"})
    assert len(ours.all("lines")) == 1  # cached
    race.append(True)
    ours.append("lines", {"line_id": "ours"})
    assert [r["line_id"] for r in ours.all("lines")] == ["first", "theirs", "ours"]
