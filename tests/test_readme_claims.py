"""Each README claim traced to its source: the keyboard table's links and every figure that
tests/test_readme_numbers.py leaves out, so a claim can't drift from its code or saved run."""

import json
import re
from pathlib import Path

from core.guard import Guard

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
SNAPSHOT = json.loads((ROOT / "eval" / "live_stats_2026-10-24.json").read_text())
CONSOLE = json.loads((ROOT / "data" / "mubit_console.json").read_text())


def readme() -> str:
    return " ".join(README.read_text().split())


# docs/evidence.md's keyboard and screen-reader table: each link, and what its line must say
KEYBOARD = {
    ("web/src/eyes.ts", 2): "export const eyesKey",
    ("web/src/components/Live.tsx", 211): "eyesKey(e)",
    ("web/src/live.test.ts", 251): "E toggles the cover",
    ("web/src/components/Controls.tsx", 63): 'aria-keyshortcuts="E"',
    ("web/src/components/Live.tsx", 256): 'className="eyes"',
    ("web/src/live.test.ts", 215): "Close your eyes covers the picture",
    ("web/src/live.test.ts", 231): "with no video, Close your eyes",
    ("web/src/components/Live.tsx", 198): "T opens the Teams panel",
    ("web/src/components/Live.tsx", 322): 'aria-keyshortcuts="T"',
    ("web/e2e/teams.spec.ts", 61): "the tab works with the keyboard alone",
    ("web/e2e/a11y.spec.ts", 107): "T opens the Teams panel",
    ("web/src/components/LineLog.tsx", 175): "'w'",
    ("web/src/components/LineLog.tsx", 185): 'aria-keyshortcuts="W"',
    ("web/e2e/keyboard.spec.ts", 41): 'W asks "Where are we?"',
    ("web/src/components/Converse.tsx", 45): "onPause()",
    ("web/src/components/Converse.tsx", 82): "'Escape'",
    ("web/e2e/talk.spec.ts", 49): "Talk pauses the match",
    ("web/e2e/talk.spec.ts", 77): "Escape ends it and resumes",
    ("web/e2e/talk.spec.ts", 118): "Escape while it is still connecting",
    ("web/src/converse.ts", 11): "SILENT_MS = 12_000",
    ("web/src/components/Converse.tsx", 62): "SILENT_MS",
    ("web/e2e/converse-lifecycle.spec.ts", 105): "a late SDK session is ended",
    ("web/src/components/Caption.tsx", 22): "aria-live={announce ? 'polite' : 'off'}",
    ("web/src/components/Live.tsx", 222): "const voiced",
    ("web/e2e/a11y.spec.ts", 155): "'aria-live', 'off'",
    ("web/e2e/keyboard.spec.ts", 89): "voice silent: the caption is a live region",
    ("web/src/components/LineLog.tsx", 67): "'Answer ready'",
    ("web/e2e/a11y.spec.ts", 164): "'Answer ready'",
    ("web/src/components/Live.tsx", 244): 'role="status"',
    ("web/src/components/Live.tsx", 415): 'role="status"',
    ("web/e2e/a11y.spec.ts", 153): "getByRole('status')",
    ("web/src/live.test.ts", 142): "announces OFF AIR",
    ("web/src/components/Wall.tsx", 141): 'className="tile"',
    ("web/src/components/LineLog.tsx", 192): 'id="ask-q"',
    ("web/e2e/a11y.spec.ts", 130): "keyboard only: Tab to Kobe",
    ("web/src/App.css", 21): ":focus-visible { outline",
    ("web/src/player.ts", 125): "'tabindex', '-1'",
    ("web/e2e/a11y.spec.ts", 149): "':focus-visible'",
    ("web/src/player.test.ts", 61): "Tab never walks into the embed",
    ("web/src/focus.ts", 5): "useSheetFocus",
    ("web/e2e/a11y.spec.ts", 168): "A sheet takes the focus",
    ("web/src/components/Live.tsx", 247): "<h1",
    ("web/src/live.test.ts", 317): "one h1",
    ("web/src/live.test.ts", 333): "never skip a level",
    ("web/src/components/FollowPicker.tsx", 39): 'role="combobox"',
    ("web/src/components/ProfileCard.tsx", 28): "Following ${name}",
    ("web/e2e/keyboard.spec.ts", 59): "Follow by keyboard alone",
    ("web/e2e/a11y.spec.ts", 90): "axe and 44 px targets",
    ("web/e2e/a11y.spec.ts", 116): "axe on the review queue",
}


def test_the_keyboard_table_points_at_its_code_and_tests():
    doc = (ROOT / "docs" / "evidence.md").read_text()
    table = doc[doc.index("## Keyboard and screen reader") :]
    table = table[: table.index("\n## ", 1)]
    links = {(f, int(n)) for f, n in re.findall(r"\]\(\.\./(web/[^)#]+)#L(\d+)\)", table)}
    assert links == set(KEYBOARD)
    for (f, n), want in KEYBOARD.items():
        assert want in (ROOT / f).read_text().splitlines()[n - 1], (f, n)
    assert "not tested" not in table


def test_the_fixes_breakdown_and_console_counts_are_the_saved_reads():
    kinds, text = SNAPSHOT["scorecheck"]["from_fixes_by_kind"], readme()
    assert sum(kinds.values()) == SNAPSHOT["scorecheck"]["by_source"]["human"]
    want = f"({kinds['matched']} the model already matched, {kinds['corrected']} corrected, "
    assert want + f"{kinds['uncorrected']} not corrected)" in text
    c, check = CONSOLE, CONSOLE["listed"]["Check one line of…"]
    assert f"{c['tasks']} tasks, {c['adapters']} adapters and {c['serving']} serving" in text
    best = max(t["quality"] for n, t in c["listed"].items() if n != "Check one line of…")
    assert f"scored {check['quality']}% against a {c['target']}% target" in text
    assert f"on {check['test_cases']} test cases; the best commentary task scores {best}%" in text


def test_the_ask_figures_are_the_saved_keyed_run():
    run = (ROOT / "eval" / "ask_eval_keyed_20261025.txt").read_text()
    got = re.search(r"(\d+) correct, (\d+) wrong, (\d+) refused of (\d+)", run)
    assert got, "the run's summary line"
    right, wrong, refused, n = got.groups()
    text = readme()
    assert f"{right} of {n} answers were right, {wrong} wrong and {refused} refused" in text
    # the one wrong answer the README explains: row 24, "What just happened?" at Lakers 120-102
    rows = [r for r in run.splitlines() if r.startswith("| ") and r.rstrip().endswith("| wrong |")]
    assert len(rows) == int(wrong) and rows[0].startswith("| 24 |") and "120-102" in rows[0]
    assert 'row 24, "What just happened?" at Lakers 120-102' in text


def test_the_terland_run_names_the_later_moments_saying_the_seagulls():
    run = (ROOT / "eval" / "fix_then_later_live_20261024.txt").read_text()
    later = run[run.index("The next lines on this match") :].split("\nMoment ")[1:]
    carried = [m.split()[0] for m in later if "Seagulls" in m.split("after the fix:")[1]]
    assert len(later) == 6 and carried == ["18", "34", "35"]
    assert 'Moments 18, 34 and 35 took up "the Seagulls"; the other three' in readme()
    assert "The Seagulls go three-two up" in run


def test_one_more_catch_is_about_seventeen_points_and_the_first_word_about_half_a_second():
    text = readme()
    row = r"\| Held-out, every line \| Number check \(rules\) \| \d+ \| (\d+) \|"
    wrong = int(re.search(row, text)[1])
    assert f"about {round(100 / wrong)} points" in text
    assert 400 <= SNAPSHOT["by_speaker"]["lead"]["first_word_ms_p50"] <= 600
    assert "first word is out in about half a second" in text


def test_the_budget_table_is_the_guards_defaults():
    rows = dict(re.findall(r"\| `([A-Z_]+)` \| (\d+) \|", README.read_text()))
    g = Guard(env={})
    assert rows == {
        "MAX_LIVE_REPLAYS": str(g.max_live),
        "REPLAYS_PER_HOUR": str(g.replays.per_hour),
        "ASKS_PER_HOUR": str(g.asks.per_hour),
        "DAILY_BUDGET_USD": f"{g.budget:g}",
    }


def test_the_files_over_the_line_rule_are_the_two_the_readme_names():
    over = sorted(
        str(p.relative_to(ROOT))
        for d in ("core", "agent", "eval", "scripts", "tests", "web/src", "web/e2e")
        for p in (ROOT / d).rglob("*")
        if p.suffix in {".py", ".ts", ".tsx"} and len(p.read_text().splitlines()) > 1000
    )
    assert over == ["core/insight.py", "tests/test_core_voice.py"]
    assert "Two files break the repo's 1,000-line rule" in readme()
    assert all(f"`{f}`" in readme() for f in over)


def test_the_graph_holds_the_football_matches_the_readme_counts(monkeypatch):
    from core import graph

    monkeypatch.setattr(graph, "_kv", None)
    graph._open_store()
    sql = "SELECT count() AS n FROM fixture WHERE sport = 'football' GROUP ALL"
    n = graph._rows(sql, {})[0]["n"]
    assert f"in football ({n} matches)" in readme()
