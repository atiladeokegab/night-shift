"""Load check: several judges at once against a local server, offline (no keys, no prod).

    uv run python scripts/load_check.py [--sessions 5] [--store local|gcs] [--seed 7000]
    make load

Starts the real app in a child process on a fresh store, seeded with `--seed` stored lines (about
production's size, so /stats and the store reads cost what they cost there). `--store gcs` runs
GcsStore over an in-memory bucket with GCS-like latency instead of files. Each session is one
judge: its own client IP (X-Forwarded-For, as Cloud Run passes it), a different match, its stream
read until `--lines` lines, and two questions asked along the way. Reports the p95 time to first
line, every 429 and 5xx, /health latency while the sessions run, and the server's memory growth.
"""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OFFLINE = {
    "MUBIT_API_KEY": "",
    "MUBIT_FALLBACK_KEY": "",
    "ANTHROPIC_API_KEY": "",
    "ELEVENLABS_API_KEY": "",
    "MODE": "local",
}
QUESTIONS = ("Where are we?", "Who has been the best player so far?")


def pct(xs: list[float], q: float) -> float | None:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


# --- the server, in its own process -------------------------------------------------------------


class SlowBucket:
    """An in-memory bucket with GCS-like costs: `ms` a call, plus the bytes moved at `mbps`."""

    def __init__(self, ms: float, mbps: float):
        self.objects: dict[str, tuple[str, int]] = {}
        self.ms, self.mbps = ms, mbps
        self.lock = threading.Lock()

    def wait(self, size: int = 0) -> None:
        time.sleep(self.ms / 1000 + size / (self.mbps * 1e6))

    def blob(self, name: str):
        return SlowBlob(self, name)

    def get_blob(self, name: str):
        self.wait()
        with self.lock:
            got = self.objects.get(name)
        return SlowBlob(self, name, got[1]) if got else None


class SlowBlob:
    def __init__(self, bucket: SlowBucket, name: str, generation: int | None = None):
        self.bucket, self.name, self.generation = bucket, name, generation

    def exists(self) -> bool:
        self.bucket.wait()
        return self.name in self.bucket.objects

    def download_as_text(self, if_generation_match=None) -> str:
        from google.api_core.exceptions import PreconditionFailed

        with self.bucket.lock:
            text, gen = self.bucket.objects[self.name]
        self.bucket.wait(len(text))
        if if_generation_match is not None and if_generation_match != gen:
            raise PreconditionFailed("generation")
        return text

    def upload_from_string(self, text: str, if_generation_match=None) -> None:
        from google.api_core.exceptions import PreconditionFailed

        self.bucket.wait(len(text))
        with self.bucket.lock:
            gen = self.bucket.objects.get(self.name, ("", 0))[1]
            if if_generation_match is not None and if_generation_match != gen:
                raise PreconditionFailed("generation")
            self.bucket.objects[self.name] = (text, gen + 1)
            self.generation = gen + 1


def seeded(n: int) -> str:
    """At least `n` stored lead lines shaped like production's: one for every moment of every match,
    as production has, so a judge over the live-replay cap hears the stored lines (core/guard.py)
    rather than a 429; the rest for a match no session replays."""
    from data.matches import list_matches, load_moments

    said = [
        (m["match_id"], mo["idx"]) for m in list_matches() for mo in load_moments(m["match_id"])
    ]
    said += [("seed", 0)] * max(0, n - len(said))
    row = {
        "speaker": "lead",
        "text": "Kane drives it low from the edge, and the keeper gets down well to his left.",
        "model": "claude-haiku-4-5",
        "tokens_in": 1800,
        "tokens_out": 40,
        "first_word_ms": 540,
        "latency_ms": 900,
        "checked": True,
        "mubit_request_ids": ["r"],
        "created_at": "2026-10-24T12:00:00+00:00",
    }
    return "".join(
        json.dumps({**row, "match_id": m, "moment_idx": idx, "line_id": f"seed{i}"}) + "\n"
        for i, (m, idx) in enumerate(said)
    )


def serve(port: int, kind: str, seed: int, gcs_ms: float) -> None:
    import uvicorn

    from core.app import create_app
    from core.store import GcsStore, Store

    if kind == "gcs":
        bucket = SlowBucket(gcs_ms, mbps=50)
        bucket.objects["load/lines.jsonl"] = (seeded(seed), 1)
        store = GcsStore("gs://b/load", client=type("C", (), {"bucket": lambda _s, _n: bucket})())
    else:
        root = Path(tempfile.mkdtemp(prefix="load-"))
        (root / "lines.jsonl").write_text(seeded(seed))
        store = Store(root)
    uvicorn.run(create_app(store=store), port=port, log_level="warning")


# --- the judges -------------------------------------------------------------------------------


class Tally:
    def __init__(self):
        self.statuses: list[tuple[str, int]] = []
        self.first_line: list[float] = []
        self.cached = 0  # sessions over the live cap, said from stored lines
        self.asks: list[float] = []
        self.health: list[float] = []
        self.errors: list[str] = []

    def bad(self) -> list[tuple[str, int]]:
        return [(what, s) for what, s in self.statuses if s == 429 or s >= 500]


async def judge(client: httpx.AsyncClient, n: int, match: dict, args, tally: Tally) -> None:
    head = {"x-forwarded-for": f"203.0.113.{n + 1}"}  # each judge is a different client
    started = time.monotonic()
    r = await client.post(
        "/replays", json={"match_id": match["match_id"], "speed": args.speed}, headers=head
    )
    tally.statuses.append(("POST /replays", r.status_code))
    if r.status_code != 200:
        tally.errors.append(f"judge {n} {match['match_id']}: {r.status_code} {r.text[:120]}")
        return
    rid, lines, name, asked = r.json()["replay_id"], 0, None, 0

    async def ask(q: str, after: asyncio.Task | None) -> None:
        if after:  # one question at a time, as the page asks them
            await after
        t = time.monotonic()
        a = await client.post(f"/replays/{rid}/ask", json={"question": q}, headers=head)
        tally.statuses.append(("POST ask", a.status_code))
        if a.status_code == 200:
            tally.asks.append(time.monotonic() - t)
        else:
            tally.errors.append(f"judge {n} ask: {a.status_code} {a.text[:120]}")

    pending: list[asyncio.Task] = []
    async with client.stream("GET", f"/replays/{rid}/stream", headers=head) as resp:
        tally.statuses.append(("GET stream", resp.status_code))
        async for row in resp.aiter_lines():
            if row.startswith("event: "):
                name = row.removeprefix("event: ")
            elif row.startswith("data: ") and name == "error":
                tally.errors.append(f"judge {n} stream error: {row[:160]}")
            elif row.startswith("data: ") and name == "line":
                lines += 1
                if lines == 1:
                    tally.first_line.append(time.monotonic() - started)
                    tally.cached += bool(json.loads(row.removeprefix("data: ")).get("cached"))
                # two questions, as a judge would: at the first line, then a few lines on
                if asked < len(QUESTIONS) and lines in (1, 1 + args.ask_gap):
                    after = pending[-1] if pending else None
                    pending.append(asyncio.create_task(ask(QUESTIONS[asked], after)))
                    asked += 1
                if lines >= args.lines:
                    break
    await asyncio.gather(*pending)


async def poll_health(client: httpx.AsyncClient, tally: Tally, done: asyncio.Event) -> None:
    while not done.is_set():
        t = time.monotonic()
        r = await client.get("/health")
        tally.health.append(time.monotonic() - t)
        tally.statuses.append(("GET /health", r.status_code))
        await asyncio.sleep(0.2)


def rss_mb(pid: int) -> float:
    for row in Path(f"/proc/{pid}/status").read_text().splitlines():
        if row.startswith("VmRSS:"):
            return int(row.split()[1]) / 1024
    return 0.0


async def run(base: str, pid: int, args) -> tuple[Tally, dict]:
    tally = Tally()
    limits = httpx.Limits(max_connections=50)
    async with httpx.AsyncClient(base_url=base, timeout=120, limits=limits) as client:
        matches = (await client.get("/matches")).json()
        # one of each sport first, so the five judges replay different matches
        by_sport: dict[str, list[dict]] = {}
        for m in matches:
            by_sport.setdefault(m["sport"], []).append(m)
        order = [m for i in range(9) for ms in by_sport.values() for m in ms[i : i + 1]]
        mem = {"before": rss_mb(pid), "peak": 0.0}
        done = asyncio.Event()

        async def watch_memory():
            while not done.is_set():
                mem["peak"] = max(mem["peak"], rss_mb(pid))
                await asyncio.sleep(0.2)

        side = [
            asyncio.create_task(poll_health(client, tally, done)),
            asyncio.create_task(watch_memory()),
        ]
        t = time.monotonic()
        await asyncio.gather(
            *(judge(client, n, order[n % len(order)], args, tally) for n in range(args.sessions))
        )
        mem["wall_s"] = time.monotonic() - t
        done.set()
        await asyncio.gather(*side)
        mem["after"] = rss_mb(pid)
    return tally, mem


def report(tally: Tally, mem: dict, args) -> int:
    def s(x):
        return "-" if x is None else f"{x:.2f} s"

    print(f"load check: {args.sessions} sessions, store {args.store}, {args.seed} seeded lines")
    print(
        f"  first line: p50 {s(pct(tally.first_line, 0.5))}, p95 {s(pct(tally.first_line, 0.95))}"
        f" over {len(tally.first_line)} sessions ({tally.cached} said from stored lines)"
    )
    print(f"  ask: p95 {s(pct(tally.asks, 0.95))} over {len(tally.asks)} answers")
    h = tally.health
    print(
        f"  /health during load: p50 {s(pct(h, 0.5))}, p95 {s(pct(h, 0.95))}, "
        f"max {s(max(h) if h else None)} over {len(h)} probes"
    )
    print(
        f"  memory: {mem['before']:.0f} MB before, {mem['peak']:.0f} MB peak, "
        f"{mem['after']:.0f} MB after (+{mem['after'] - mem['before']:.0f} MB)"
    )
    print(f"  wall time: {mem['wall_s']:.1f} s")
    bad = tally.bad()
    print(f"  429 or 5xx: {len(bad)}" + (f" {bad}" if bad else ""))
    for e in tally.errors:
        print(f"  ! {e}")
    return 1 if bad or len(tally.first_line) < args.sessions else 0


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sessions", type=int, default=5)
    p.add_argument("--store", choices=("local", "gcs"), default="local")
    p.add_argument("--seed", type=int, default=7000, help="stored lines before the run")
    p.add_argument("--gcs-ms", type=float, default=30.0, help="--store gcs: ms per GCS call")
    p.add_argument("--speed", type=float, default=60.0)
    p.add_argument("--lines", type=int, default=12, help="lines each judge watches")
    p.add_argument("--ask-gap", type=int, default=5, help="lines between the two questions")
    p.add_argument("--serve", type=int, help=argparse.SUPPRESS)  # the child process
    args = p.parse_args(argv)
    if args.serve:
        serve(args.serve, args.store, args.seed, args.gcs_ms)
        return 0
    port = free_port()
    cmd = [sys.executable, __file__, "--serve", str(port), "--store", args.store]
    cmd += ["--seed", str(args.seed), "--gcs-ms", str(args.gcs_ms)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("HUB_")} | OFFLINE
    env["PYTHONPATH"] = str(ROOT)
    server = subprocess.Popen(cmd, cwd=ROOT, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(300):
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if server.poll() is not None:
                print("load check: the server exited before it was ready")
                return 1
            time.sleep(0.1)
        tally, mem = asyncio.run(run(base, server.pid, args))
        return report(tally, mem, args)
    finally:
        server.terminate()
        server.wait(10)


if __name__ == "__main__":
    sys.exit(main())
