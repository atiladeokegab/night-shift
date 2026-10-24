"""GcsStore against an in-memory stand-in that behaves like google-cloud-storage: a fresh
`bucket.blob(name)` knows no generation until it is loaded, and writes check if_generation_match."""

from core.store import GcsStore


class PreconditionFailed(Exception):
    pass


class FakeBlob:
    def __init__(self, objects, name, generation=None, calls=None):
        self.objects, self.name, self.generation = objects, name, generation
        self.calls = calls if calls is not None else []

    def exists(self):  # like the real client: answers, but does not load the generation
        return self.name in self.objects

    def download_as_text(self, if_generation_match=None):
        self.calls.append("download")
        text, gen = self.objects[self.name]
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed()
        return text

    def upload_from_string(self, text, if_generation_match=None):
        gen = self.objects.get(self.name, ("", 0))[1]
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed()
        self.objects[self.name] = (text, gen + 1)
        self.generation = gen + 1  # like the real client: the upload's reply loads it


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def blob(self, name):
        return FakeBlob(self.objects, name, calls=self.calls)

    def get_blob(self, name):
        self.calls.append("metadata")
        if name not in self.objects:
            return None
        return FakeBlob(self.objects, name, self.objects[name][1], self.calls)


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


def test_a_read_costs_one_metadata_call_and_no_download(monkeypatch):
    monkeypatch.setattr("google.api_core.exceptions.PreconditionFailed", PreconditionFailed)
    client = FakeClient()
    store = GcsStore("gs://b/prefix", client=client)
    store.append("lines", {"line_id": "a"})
    store.append("lines", {"line_id": "b"})
    client.b.calls.clear()
    assert [r["line_id"] for r in store.all("lines")] == ["a", "b"]
    assert [r["line_id"] for r in store.all("lines")] == ["a", "b"]
    assert client.b.calls == ["metadata", "metadata"]


def test_an_append_after_another_writer_redownloads_once_and_keeps_both(monkeypatch):
    monkeypatch.setattr("google.api_core.exceptions.PreconditionFailed", PreconditionFailed)
    client = FakeClient()
    ours, theirs = GcsStore("gs://b/p", client=client), GcsStore("gs://b/p", client=client)
    ours.append("lines", {"line_id": "a"})
    theirs.append("lines", {"line_id": "b"})  # ours still caches the object without b
    client.b.calls.clear()
    ours.append("lines", {"line_id": "c"})
    assert client.b.calls == ["metadata", "download"]  # the conflict's re-read, nothing else
    assert [r["line_id"] for r in ours.all("lines")] == ["a", "b", "c"]
    assert [r["line_id"] for r in theirs.all("lines")] == ["a", "b", "c"]


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
