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
