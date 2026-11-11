"""The one store: JSON-lines files of lines and fixes. Local mode writes under STORE_DIR (default
data/); cloud mode (MODE=cloud) keeps the same files as GCS objects and refuses to start without
STORE_URL=gs://bucket/prefix."""

import json
import os
import re
import threading
import time
from pathlib import Path

KINDS = (
    "lines",
    "fixes",
    "auto_fixes",
    "adapter",
    "answers",
    "voice",
    "replays",
    "linechecks",  # Line check's second opinion on a live line (#298)
    "scorechecks",  # Score check asked live about a fresh line: its label, code's, served_by
    "linecheck_fixes",  # producer fixes sent to Line check as examples (#298)
    "scorecheck_examples",  # every Score check example sent, seeded or from a fix (#321)
    "scorecheck_evals",  # a model's score on Score check's held-out lines (#321)
    "scorecheck_receipts",  # one per fix once its Score check send ends: how many went (#400)
    "looks",  # frame calls and screen-note lines: that viewer's only (#291)
)


def clip_name(line_id: str, voice_id: str) -> str:
    """Where a line's finished clip in one voice is kept: ids only, never a path."""
    if not re.fullmatch(r"[\w-]+", line_id) or not re.fullmatch(r"[\w-]+", voice_id):
        raise ValueError(f"no clip name for {line_id!r} {voice_id!r}")
    return f"clips/{line_id}.{voice_id}"


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # kind -> (stamp, text): stats() reads every kind after each line (#243), so a kind is
        # fetched again only once its stamp changes, and our own appends extend it in place
        self._cache: dict[str, tuple] = {}

    def _stamp(self, kind: str):
        """Changes whenever the kind is written, by this process or another; cheap to get."""
        try:
            st = (self.root / f"{kind}.jsonl").stat()
        except FileNotFoundError:
            return None
        return st.st_size, st.st_mtime_ns

    def _read(self, kind: str) -> str:
        path = self.root / f"{kind}.jsonl"
        with self._lock:  # appends run on threads (#156): never read half of one
            return path.read_text() if path.exists() else ""

    def _write(self, kind: str, text: str) -> None:
        # newline="": the bytes written are the row's on every OS, as append's size check expects
        with (self.root / f"{kind}.jsonl").open("a", newline="") as f:
            f.write(text)

    def all(self, kind: str) -> list[dict]:
        stamp = self._stamp(kind)  # before the read: a write after it only costs a fetch
        cached = self._cache.get(kind)
        if not cached or cached[0] != stamp:
            cached = self._cache[kind] = (stamp, self._read(kind))
        return [json.loads(row) for row in cached[1].splitlines() if row.strip()]

    def append(self, kind: str, record: dict) -> dict:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        row = json.dumps(record) + "\n"
        with self._lock:
            before = self._stamp(kind)
            self._write(kind, row)
            cached, after = self._cache.get(kind), self._stamp(kind)
            grew = (after[0] if after else 0) - (before[0] if before else 0)
            # only our row landed since we read it; another process's append in between (our lock
            # is this process's only) or a lost write: fetch it all again on the next read
            if cached and cached[0] == before and grew == len(row.encode()):
                self._cache[kind] = (after, cached[1] + row)
            else:
                self._cache.pop(kind, None)
        return record

    def save_clip(self, line_id: str, voice_id: str, data: bytes, content_type: str) -> None:
        path = self.root / clip_name(line_id, voice_id)
        path.parent.mkdir(exist_ok=True)
        Path(f"{path}.type").write_text(content_type)
        part = Path(f"{path}.part")  # renamed whole: a reader never sees half a clip
        part.write_bytes(data)
        part.replace(path)

    def clip(self, line_id: str, voice_id: str) -> tuple[bytes, str] | None:
        path = self.root / clip_name(line_id, voice_id)
        if not path.exists():
            return None
        return path.read_bytes(), Path(f"{path}.type").read_text()


class GcsStore(Store):
    """Each kind is one GCS object; an append rewrites it, compare-and-swap on its generation. Each
    kind's text is cached with its generation (#156): a read makes no GCS call while the cache was
    checked in the last FRESH_S, else one metadata call; an append uploads the cached text plus the
    record, and downloads only when another writer got there first."""

    FRESH_S = 2.0  # how stale another process's write may look; this process's own never is

    # shortcut: every append rewrites the whole object (about one write a second per object);
    # a database if two producers edit at once (IDEA.md ceilings).
    def __init__(self, url: str, client=None, clock=time.monotonic):
        from google.cloud import storage

        bucket, _, prefix = url.removeprefix("gs://").partition("/")
        self.bucket = (client or storage.Client()).bucket(bucket)
        self.prefix = prefix.strip("/")
        self._lock = threading.Lock()
        self._cache = {}
        self._checked: dict[str, float] = {}  # kind: when its generation was last read
        self.clock = clock

    def _blob(self, kind: str):
        return self.bucket.blob(f"{self.prefix}/{kind}.jsonl" if self.prefix else f"{kind}.jsonl")

    def _stamp(self, kind: str):
        cached, now = self._cache.get(kind), self.clock()
        # stats() reads every kind after each line of every replay: 9 metadata calls a line
        if cached and now - self._checked.get(kind, -self.FRESH_S) < self.FRESH_S:
            return cached[0]
        blob = self.bucket.get_blob(self._blob(kind).name)  # metadata only, never the object
        self._checked[kind] = now
        return blob.generation if blob else None

    def _fetch(self, kind: str) -> tuple[int, str]:
        """The object's generation (0: none yet) and text, downloaded at that generation."""
        from google.api_core.exceptions import PreconditionFailed

        for _ in range(8):
            # get_blob loads the generation; blob().exists() leaves it None, which read the
            # object as empty and let the next append overwrite every earlier record
            blob = self.bucket.get_blob(self._blob(kind).name)
            if blob is None:
                return 0, ""
            try:
                return blob.generation, blob.download_as_text(if_generation_match=blob.generation)
            except PreconditionFailed:  # it changed between the two calls
                continue
        raise RuntimeError(f"store: {kind} kept changing under the read")

    def _read(self, kind: str) -> str:
        blob = self._blob(kind)
        return blob.download_as_text() if blob.exists() else ""

    def append(self, kind: str, record: dict) -> dict:
        from google.api_core.exceptions import PreconditionFailed

        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        row = json.dumps(record) + "\n"
        with self._lock:
            cached = self._cache.get(kind)
            # a cached None is a kind not written yet: generation 0 uploads only if still none
            gen, text = (cached[0] or 0, cached[1]) if cached else self._fetch(kind)
            for _ in range(8):
                out = self._blob(kind)
                try:
                    out.upload_from_string(text + row, if_generation_match=gen)
                except PreconditionFailed:  # another writer: start again from its text
                    gen, text = self._fetch(kind)
                    continue
                if out.generation:  # the upload loads it; unknown, the next read fetches
                    self._cache[kind] = (out.generation, text + row)
                    self._checked[kind] = self.clock()
                else:
                    self._cache.pop(kind, None)
                return record
        raise RuntimeError(f"store: {kind} kept changing under the append")

    def _clip_blob_name(self, line_id: str, voice_id: str) -> str:
        name = clip_name(line_id, voice_id)
        return f"{self.prefix}/{name}" if self.prefix else name

    def save_clip(self, line_id: str, voice_id: str, data: bytes, content_type: str) -> None:
        blob = self.bucket.blob(self._clip_blob_name(line_id, voice_id))
        blob.upload_from_string(data, content_type=content_type)

    def clip(self, line_id: str, voice_id: str) -> tuple[bytes, str] | None:
        blob = self.bucket.get_blob(self._clip_blob_name(line_id, voice_id))
        return None if blob is None else (blob.download_as_bytes(), blob.content_type)


def open_store(env=os.environ) -> Store:
    if env.get("MODE", "local") == "cloud":
        url = env.get("STORE_URL", "")
        if not url.startswith("gs://"):
            raise RuntimeError("cloud mode refuses to start without STORE_URL=gs://bucket/prefix")
        return GcsStore(url)
    return Store(env.get("STORE_DIR", "data"))
