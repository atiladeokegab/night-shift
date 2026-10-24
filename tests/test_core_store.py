"""GcsStore against an in-memory stand-in that behaves like google-cloud-storage: a fresh
`bucket.blob(name)` knows no generation until it is loaded, and writes check if_generation_match."""

from core.store import GcsStore


class PreconditionFailed(Exception):
    pass


class FakeBlob:
    def __init__(self, objects, name, generation=None):
        self.objects, self.name, self.generation = objects, name, generation

    def exists(self):  # like the real client: answers, but does not load the generation
        return self.name in self.objects

    def download_as_text(self, if_generation_match=None):
        text, gen = self.objects[self.name]
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed()
        return text

    def upload_from_string(self, text, if_generation_match=None):
        gen = self.objects.get(self.name, ("", 0))[1]
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed()
        self.objects[self.name] = (text, gen + 1)


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return FakeBlob(self.objects, name)

    def get_blob(self, name):
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
