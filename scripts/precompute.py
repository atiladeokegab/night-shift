"""Make and keep every match's lines and ElevenLabs audio on the live site, so later replays play
them from the store at no cost.

    export PRODUCER_TOKEN=...  # read from the environment only, never printed
    uv run python scripts/precompute.py --base https://night-shift-5zvig7nbvq-ew.a.run.app \
        [--match ID ...]

Each match: a fresh replay (the producer token lets it make new lines), its stream read to the
end, then each line's audio fetched in the voice the page asks for, so the clip is made and saved.
At most two matches at once; stops starting new ones near the daily budget. Exits 1 if any failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import httpx

SPEED = 50.0  # ReplayRequest sets no upper bound; video matches are paced by the video anyway
AT_ONCE = 2  # the site's MAX_LIVE_REPLAYS is 4: leave room for viewers
RETRIES = 3
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
STREAM_TIMEOUT = httpx.Timeout(60.0, connect=10.0, read=300.0)  # a fresh line can take a while
BUDGET_MARGIN_USD = 1.0


class Failed(Exception):
    """A request that failed: its method, path and status only, never its headers."""


async def call(client: httpx.AsyncClient, method: str, path: str, **kw) -> httpx.Response:
    """The response, waiting out a 429's Retry-After up to RETRIES times; Failed on any other
    error status or transport error."""
    for attempt in range(RETRIES + 1):
        try:
            res = await client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise Failed(f"{method} {path}: {type(exc).__name__}") from None
        if res.status_code == 429 and attempt < RETRIES:
            await asyncio.sleep(float(res.headers.get("retry-after") or 60))
            continue
        if res.status_code >= 400:
            raise Failed(f"{method} {path}: {res.status_code}")
        return res
    raise AssertionError("unreachable")


async def over_budget(client: httpx.AsyncClient) -> bool:
    budget = (await call(client, "GET", "/stats")).json().get("budget") or {}
    cap = budget.get("daily_budget_usd")
    spent = budget.get("spent_today_usd") or 0.0
    return bool(budget.get("off_air")) or (cap is not None and spent >= cap - BUDGET_MARGIN_USD)


async def stream_lines(client: httpx.AsyncClient, replay_id: str) -> list[dict]:
    """Every `line` event's data until `end`; Failed on an `error` event."""
    lines, event = [], ""
    path = f"/replays/{replay_id}/stream"
    async with client.stream("GET", path, timeout=STREAM_TIMEOUT) as res:
        if res.status_code >= 400:
            raise Failed(f"GET {path}: {res.status_code}")
        async for row in res.aiter_lines():
            if row.startswith("event:"):
                event = row[6:].strip()
            elif row.startswith("data:"):
                if event == "line":
                    lines.append(json.loads(row[5:]))
                elif event == "error":
                    raise Failed(f"GET {path}: error event {row[5:].strip()}")
                elif event == "end":
                    return lines
    raise Failed(f"GET {path}: stream closed before end")


def audio_path(line: dict, lead_voice: str | None) -> str:
    """As the page's lineAudioUrl(voiceOf(...)): the lead in the sport's default voice, the analyst
    with no ?voice= (the server picks the analyst's)."""
    path = f"/lines/{line['line_id']}/audio"
    if line.get("speaker", "lead") != "analyst" and lead_voice:
        path += f"?voice={lead_voice}"
    return path


async def precompute(client, match: dict, token: str, lead_voice: str | None) -> dict:
    out = {"match_id": match["match_id"], "lines": 0, "audio_ok": 0, "audio_failed": 0}
    started = time.monotonic()
    try:
        body = {"match_id": match["match_id"], "speed": SPEED, "fresh": True}
        res = await call(client, "POST", "/replays", json=body, headers={"X-Producer-Token": token})
        lines = await stream_lines(client, res.json()["replay_id"])
        out["lines"] = len(lines)
        for line in lines:
            try:
                await call(client, "GET", audio_path(line, lead_voice))
                out["audio_ok"] += 1
            except Failed as exc:
                out["audio_failed"] += 1
                print(f"  {match['match_id']}: {exc}", file=sys.stderr)
    except (Failed, KeyError, ValueError) as exc:
        out["error"] = str(exc) if isinstance(exc, Failed) else type(exc).__name__
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


async def run(base: str, ids: list[str], token: str, transport=None) -> int:
    async with httpx.AsyncClient(base_url=base, timeout=TIMEOUT, transport=transport) as client:
        matches = (await call(client, "GET", "/matches")).json()
        if ids:
            known = {m["match_id"]: m for m in matches}
            matches = [known.get(i, {"match_id": i}) for i in ids]
        voices = (await call(client, "GET", "/voices")).json()
        lead = {v["default_for"]: v["id"] for v in voices if v.get("default_for")}
        gate, failed, skipped = asyncio.Semaphore(AT_ONCE), False, []

        async def one(match: dict) -> None:
            nonlocal failed
            async with gate:
                if await over_budget(client):
                    skipped.append(match["match_id"])
                    return
                r = await precompute(client, match, token, lead.get(match.get("sport")))
            bad = "error" in r or r["audio_failed"] or not r["lines"]
            failed = failed or bool(bad)
            print(
                f"{r['match_id']} lines={r['lines']} audio_ok={r['audio_ok']} "
                f"audio_failed={r['audio_failed']} seconds={r['seconds']}"
                + (f" FAILED {r.get('error', '')}".rstrip() if bad else ""),
                flush=True,
            )

        await asyncio.gather(*(one(m) for m in matches))
        for match_id in skipped:
            print(f"{match_id} skipped: near the daily budget")
        return 1 if failed or skipped else 0


def main(argv: list[str] | None = None, transport=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="the site's URL")
    ap.add_argument("--match", action="append", default=[], help="only this match id (repeatable)")
    args = ap.parse_args(argv)
    token = os.environ.get("PRODUCER_TOKEN", "")
    if not token:
        print("PRODUCER_TOKEN is not set", file=sys.stderr)
        return 2
    try:
        return asyncio.run(run(args.base.rstrip("/"), args.match, token, transport))
    except Failed as exc:
        print(f"precompute: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
