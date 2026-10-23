"""The one store: JSON-lines files of lines and fixes. Local mode writes under STORE_DIR (default
data/); cloud mode (MODE=cloud) keeps the same files as GCS objects and refuses to start without
STORE_URL=gs://bucket/prefix."""

import json
import os
import threading
from pathlib import Path

KINDS = ("lines", "fixes", "adapter")


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self, kind: str) -> str:
        path = self.root / f"{kind}.jsonl"
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
    """Each kind is one GCS object; an append rewrites it, compare-and-swap on its generation."""

    # shortcut: every append rewrites the whole object (about one write a second per object);
    # a database if two producers edit at once (IDEA.md ceilings).
    def __init__(self, url: str, client=None):
        from google.cloud import storage

        bucket, _, prefix = url.removeprefix("gs://").partition("/")
        self.bucket = (client or storage.Client()).bucket(bucket)
        self.prefix = prefix.strip("/")
        self._lock = threading.Lock()

    def _blob(self, kind: str):
        return self.bucket.blob(f"{self.prefix}/{kind}.jsonl" if self.prefix else f"{kind}.jsonl")

    def _read(self, kind: str) -> str:
        blob = self._blob(kind)
        return blob.download_as_text() if blob.exists() else ""

    def append(self, kind: str, record: dict) -> dict:
        from google.api_core.exceptions import PreconditionFailed

        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        with self._lock:
            for _ in range(8):
                # get_blob loads the generation; blob().exists() leaves it None, which read
                # the object as empty and let the next append overwrite every earlier record
                blob = self.bucket.get_blob(self._blob(kind).name)
                gen = blob.generation if blob else 0
                try:
                    text = blob.download_as_text(if_generation_match=gen) if blob else ""
                    self._blob(kind).upload_from_string(
                        text + json.dumps(record) + "\n", if_generation_match=gen
                    )
                    return record
                except PreconditionFailed:
                    continue
        raise RuntimeError(f"store: {kind} kept changing under the append")


def open_store(env=os.environ) -> Store:
    if env.get("MODE", "local") == "cloud":
        url = env.get("STORE_URL", "")
        if not url.startswith("gs://"):
            raise RuntimeError("cloud mode refuses to start without STORE_URL=gs://bucket/prefix")
        return GcsStore(url)
    return Store(env.get("STORE_DIR", "data"))
