"""Demo preflight (#309): is the live site ready to demo? One PASS or FAIL line per check, and a
non-zero exit on any FAIL.

    uv run python scripts/demo_check.py [BASE_URL]      # or: make demo-check [URL=...]

Read-only apart from one short replay, on the deploy's live smoke path (core/smoke.py): no producer
token and no fix saved. The stream is closed after its first line, so the service stops the replay.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable

import httpx

LIVE = "https://night-shift-5zvig7nbvq-ew.a.run.app"
FIRST_LINE_S = 30.0


def first_line(client: httpx.Client, within: float) -> tuple[dict, float]:
    """Start a smoke replay of the first football match and return its first streamed line and
    how long it took from the start."""
    match = next(
        m for m in client.get("/matches").raise_for_status().json() if m["sport"] == "football"
    )
    started = time.monotonic()
    rid = client.post(
        "/replays", json={"match_id": match["match_id"], "speed": 1e6, "smoke": True}
    ).raise_for_status()
    name = None
    with client.stream("GET", f"/replays/{rid.json()['replay_id']}/stream", timeout=within) as resp:
        resp.raise_for_status()
        for row in resp.iter_lines():
            if row.startswith("event: "):
                name = row.removeprefix("event: ")
            elif row.startswith("data: ") and name in ("line", "error"):
                data = json.loads(row.removeprefix("data: "))
                if name == "error":
                    raise RuntimeError(f"stream error: {data}")
                return {**data, "match_id": match["match_id"]}, time.monotonic() - started
    raise RuntimeError("the stream ended with no line")


def check(base_url: str, within: float = FIRST_LINE_S, transport=None) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []
    got: dict = {}

    def run(name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        try:
            ok, detail = fn()
        except Exception as exc:  # any failure is a FAIL line, and the other checks still run
            ok, detail = False, f"{type(exc).__name__}: {(str(exc) or repr(exc)).splitlines()[0]}"
        results.append((ok, f"{name}: {detail}"))

    with httpx.Client(base_url=base_url, timeout=60, transport=transport) as client:

        def health():
            r = client.get("/health")
            return r.status_code == 200 and r.json() == {"status": "ok"}, r.text[:80]

        def replay():
            got["line"], took = first_line(client, within)
            line = got["line"]
            return (
                took <= within,
                f"{line['match_id']} first line in {took:.1f}s (limit {within:g}s)",
            )

        def audio():
            if "line" not in got:
                return False, "no line to voice"
            r = client.get(f"/lines/{got['line']['line_id']}/audio")
            kind = r.headers.get("content-type", "")
            ok = r.status_code == 200 and kind.startswith("audio/mpeg")
            return ok, f"{r.status_code} {kind}, {len(r.content)} bytes" if ok else r.text[:120]

        def stats():
            # after the audio, so the voice reads what that line just met
            got["stats"] = client.get("/stats").raise_for_status().json()
            return True, "read"

        def voice():
            v = got["stats"].get("voice") or {}
            ok = v.get("provider") == "elevenlabs" and not v.get("last_error")
            return ok, f"provider {v.get('provider')}, last_error {v.get('last_error')}"

        def budget():
            b = got["stats"]["budget"]
            cap, spent = b["daily_budget_usd"], b["spent_today_usd"]
            ok = not b["off_air"] and (cap is None or spent < cap)
            return ok, f"${spent:.2f} spent today of " + (f"${cap:g}" if cap else "no cap")

        def linecheck():
            lc = got["stats"].get("linecheck")
            return (
                lc is not None,
                f"{lc['checked']} checked, {lc['flags']} flags" if lc else "missing",
            )

        run("health", health)
        run("replay", replay)
        run("audio", audio)
        run("stats", stats)
        if "stats" in got:
            run("voice", voice)
            run("budget", budget)
            run("linecheck", linecheck)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("base_url", nargs="?", default=LIVE)
    p.add_argument("--first-line-s", type=float, default=FIRST_LINE_S)
    args = p.parse_args(argv)
    print(f"demo check: {args.base_url}")
    results = check(args.base_url.rstrip("/"), args.first_line_s)
    for ok, line in results:
        print(f"{'PASS' if ok else 'FAIL'} {line}")
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
