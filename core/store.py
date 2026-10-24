"""The one store: JSON-lines files of lines and fixes. Local mode writes under STORE_DIR (default
data/); cloud mode (MODE=cloud) keeps the same files as GCS objects and refuses to start without
STORE_URL=gs://bucket/prefix."""

import json
import os
import threading
from pathlib import Path

KINDS = ("lines", "fixes", "auto_fixes", "adapter", "answers", "voice", "replays")


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self, kind: str) -> str:
        path = self.root / f"{kind}.jsonl"
        with self._lock:  # appends run on threads (#156): never read half of one
            return path.read_text() if path.exists() else ""

    def _write(self, kind: str, text: str) -> None:
        with (self.root / f"{kind}.jsonl").open("a") as f:
            f.write(text)

    def all(self, kind: str) -> list[dict]:
        return [json.loads(row) for row in self._read(kind).splitlines() if row.strip()]

    def append(self, kind: str, record: dict) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        with self._lock:
            self._write(kind, json.dumps(record) + "\n")
        return record


class GcsStore(Store):
    """Each kind is one GCS object; an append rewrites it, compare-and-swap on its generation. Each
    kind's text is cached with its generation: a read costs one metadata call, and downloads only
    when another writer changed the object."""

    # shortcut: every append rewrites the whole object (about one write a second per object);
    # a database if two producers edit at once (IDEA.md ceilings).
    def __init__(self, url: str, client=None):
        from google.cloud import storage

        bucket, _, prefix = url.removeprefix("gs://").partition("/")
        self.bucket = (client or storage.Client()).bucket(bucket)
        self.prefix = prefix.strip("/")
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[int, str]] = {}  # kind: (generation, text)

    def _blob(self, kind: str):
        return self.bucket.blob(f"{self.prefix}/{kind}.jsonl" if self.prefix else f"{kind}.jsonl")

    def _fetch(self, kind: str) -> tuple[int, str]:
        """The object's generation and text: the cached text while the generation is unchanged."""
        from google.api_core.exceptions import PreconditionFailed

        for _ in range(8):
            # get_blob loads the generation; blob().exists() leaves it None, which read the
            # object as empty and let the next append overwrite every earlier record
            blob = self.bucket.get_blob(self._blob(kind).name)
            if blob is None:
                return 0, ""
            cached = self._cache.get(kind)
            if cached and cached[0] == blob.generation:
                return cached
            try:
                got = blob.generation, blob.download_as_text(if_generation_match=blob.generation)
            except PreconditionFailed:  # it changed between the two calls
                continue
            self._cache[kind] = got
            return got
        raise RuntimeError(f"store: {kind} kept changing under the read")

    def _read(self, kind: str) -> str:
        return self._fetch(kind)[1]

    def append(self, kind: str, record: dict) -> dict:
        from google.api_core.exceptions import PreconditionFailed

        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        with self._lock:
            gen, text = self._cache.get(kind) or self._fetch(kind)
            for _ in range(8):
                blob, new = self._blob(kind), text + json.dumps(record) + "\n"
                try:
                    blob.upload_from_string(new, if_generation_match=gen)
                except PreconditionFailed:  # another writer: start again from its text
                    gen, text = self._fetch(kind)
                    continue
                if blob.generation:  # never cache an unknown one: it would match any object
                    self._cache[kind] = blob.generation, new
                return record
        raise RuntimeError(f"store: {kind} kept changing under the append")


def open_store(env=os.environ) -> Store:
    if env.get("MODE", "local") == "cloud":
        url = env.get("STORE_URL", "")
        if not url.startswith("gs://"):
            raise RuntimeError("cloud mode refuses to start without STORE_URL=gs://bucket/prefix")
        return GcsStore(url)
    return Store(env.get("STORE_DIR", "data"))
