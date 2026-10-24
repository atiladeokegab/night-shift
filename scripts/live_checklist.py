"""Post-deploy checks on the live site, public routes only, no keys. PASS or FAIL per line.

    uv run python scripts/live_checklist.py [--url URL]

The two browser checks (F1 has no Teams tab, a dropped replay says it has ended) are in
web/postdeploy/live.spec.ts: `cd web && LIVE_URL=... npx playwright test -c playwright.postdeploy.config.ts`.
"""

import argparse
import sys

import httpx

URL = "https://night-shift-5zvig7nbvq-ew.a.run.app"
MEN_ONLY = {"B de Leede"}  # a men's Netherlands player: must not be in a women's squad (#466)


def teams(c: httpx.Client, sport: str, match: str) -> dict:
    r = c.get(f"/teams/{sport}/{match}")
    r.raise_for_status()
    return r.json()


def orlando(c):
    t = {x["team"]: x for x in teams(c, "football", "7457")["teams"]}["Orlando Pride"]["form"]
    dates = [g["date"] for g in t]
    return len(t) == 5 and dates[0] == "2018-05-12", f"{len(t)} games, newest {dates[:1]}"


def cricket_women(c):
    squad = [p["name"] for x in teams(c, "cricket", "1515217")["teams"] for p in x["squad"]]
    return bool(squad) and not MEN_ONLY & set(
        squad
    ), f"{len(squad)} players, men's in it: {MEN_ONLY & set(squad) or 'none'}"


def cricket_men(c):
    squad = [p["name"] for x in teams(c, "cricket", "1298150")["teams"] for p in x["squad"]]
    return bool(squad), f"{len(squad)} players"


def heldout(c):
    h = c.get("/stats").json()["linecheck"]["heldout"]
    got = (h["rules"]["caught"], h["wrong"])
    return got == (2, 5), f"rules {got[0]} of {got[1]}"


def dropped(c):
    codes = (
        c.get("/replays/nope123/stream").status_code,
        c.post("/replays/nope123/ask", json={"question": "Score?"}).status_code,
    )
    return codes == (404, 404), f"stream/ask on an unknown replay: {codes}"


CHECKS = {
    "#468 Orlando form of 5, newest 12 May": orlando,
    "#466 women's cricket squad has no men's players": cricket_women,
    "#466 men's cricket squad still has players": cricket_men,
    "#472 Proof card held-out rules row reads 2 of 5": heldout,
    "#463 a dropped replay answers 404 (the page then says it ended)": dropped,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    failed = 0
    with httpx.Client(base_url=ap.parse_args().url, timeout=30) as c:
        for name, check in CHECKS.items():
            try:
                ok, note = check(c)
            except Exception as exc:
                ok, note = False, f"{type(exc).__name__}: {exc}"
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {name}  ({note})")
    return failed > 0


if __name__ == "__main__":
    sys.exit(main())
