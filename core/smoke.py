"""Offline smoke: replay every sample match through the real app and check the stream and store."""

import json
import os
import sys
import tempfile

import httpx
from fastapi.testclient import TestClient

from core.app import create_app, default_deps
from core.store import Store


def read_stream(client: TestClient | httpx.Client, replay_id: str) -> list[tuple[str, dict]]:
    events, name = [], None
    with client.stream("GET", f"/replays/{replay_id}/stream") as resp:
        resp.raise_for_status()
        for row in resp.iter_lines():
            if row.startswith("event: "):
                name = row.removeprefix("event: ")
            elif row.startswith("data: "):
                events.append((name, json.loads(row.removeprefix("data: "))))
    return events


def replay_match(client: TestClient, store: Store, match_id: str) -> int:
    replay_id = client.post("/replays", json={"match_id": match_id, "speed": 1e6}).json()[
        "replay_id"
    ]
    events = read_stream(client, replay_id)
    names = [n for n, _ in events]
    assert "error" not in names, events
    assert names[-1] == "end" and names.count("moment") >= 1, names
    assert names[:-1] == ["moment", "line", "stats"] * names.count("moment"), names
    stored = {ln["line_id"] for ln in store.all("lines")}
    lines = [d for n, d in events if n == "line"]
    assert all(ln["line_id"] in stored for ln in lines), "a streamed line is missing from the store"
    return len(lines)


def live(base_url: str, sport: str = "football") -> int:
    """The live smoke on a deployed URL: health, then one sample replay streams moments and lines,
    and each line it streamed is in the service's own store."""
    with httpx.Client(base_url=base_url, timeout=httpx.Timeout(30, read=300)) as client:
        assert client.get("/health").json()["status"] == "ok"
        match = next(m for m in client.get("/matches").json() if m["sport"] == sport)
        body = {"match_id": match["match_id"], "speed": 1e6, "smoke": True}
        # without the token the smoke plays stored lines, so the model is not exercised
        token = {"X-Producer-Token": os.environ.get("PRODUCER_TOKEN", "")}
        rid = client.post("/replays", json=body, headers=token)
        events = read_stream(client, rid.raise_for_status().json()["replay_id"])
        names = [n for n, _ in events]
        lines = names.count("line")
        assert "error" not in names and names[-1] == "end" and lines >= 1, names
        # by id, not a /stats count: a video replay streams its stored insight lines again
        for line_id in {d["line_id"] for n, d in events if n == "line"}:
            assert client.get(f"/lines/{line_id}").status_code == 200, f"{line_id} not in store"
    moments = names.count("moment")
    print(f"live smoke: {base_url} {match['match_id']}: {moments} moments, {lines} lines")
    return 0


def main() -> int:
    if os.environ.get("BASE_URL"):
        return live(os.environ["BASE_URL"].rstrip("/"))
    deps = default_deps()
    if deps is None:
        print("smoke: no commentator (agent/ or data/ failed to import)")
        return 1
    os.environ.pop("ELEVENLABS_API_KEY", None)  # offline: no line is voiced
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(tmp)
        with TestClient(create_app(store=store, deps=deps)) as client:
            samples = [m for m in client.get("/matches").json() if m.get("sample")]
            if not samples:
                print("smoke: no sample matches")
                return 1
            for m in samples:
                print(f"smoke: {m['match_id']}: {replay_match(client, store, m['match_id'])} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
