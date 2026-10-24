"""The README's numbers come from the eval output and the console read, so they can't drift."""

import json
import re
from pathlib import Path

from eval import checker_eval, readme_numbers

ROOT = Path(__file__).resolve().parent.parent
CONSOLE = json.loads((ROOT / "data" / "mubit_console.json").read_text())


def test_the_readme_check_table_is_todays_checker_eval_output():
    text = readme_numbers.README.read_text()
    assert readme_numbers.START in text and readme_numbers.END in text
    assert readme_numbers.written(text) == text, "run: uv run python -m eval.readme_numbers --write"


def test_the_stored_held_out_rules_count_is_todays_rules():
    stored = json.loads(readme_numbers.LINECHECK.read_text())
    held = checker_eval.load(checker_eval.HELDOUT)
    s = checker_eval.evaluate(readme_numbers.lead(held))["overall"]
    assert stored["lines"] == s["lines"] and stored["wrong"] == s["tp"] + s["fn"]
    assert stored["rules"] == {"caught": s["tp"], "false_alarms": s["fp"]}


def test_the_side_by_side_panel_and_readme_match_the_console_read():
    best = max(t["quality"] for t in CONSOLE["listed"].values())
    adapter = json.loads((ROOT / "data" / "side_by_side.json").read_text())["adapter"]
    assert (adapter["adapters"], adapter["best_match_pct"]) == (CONSOLE["adapters"], best)
    text = readme_numbers.README.read_text()
    assert f"{CONSOLE['adapters']} adapters" in text and f"{best}%" in text
    # no other adapter count or best score anywhere in the README
    assert set(re.findall(r"(\d+) adapters", text)) == {str(CONSOLE["adapters"])}


def test_the_readme_live_figures_are_the_saved_stats_read():
    snap = json.loads((ROOT / "eval" / "live_stats_2026-10-24.json").read_text())
    sc, text = snap["scorecheck"], " ".join(readme_numbers.README.read_text().split())
    (held,) = sc["held_out"].values()
    assert f"${snap['cost_per_match_usd']:.2f} a replay" in text
    assert f"over {snap['matches_measured']} replays" in text
    sent, fixes = sc["examples_sent"], sc["by_source"]["human"]
    assert f"{sent:,} examples sent to training, {fixes} of them from producer" in text
    assert f"{held['agree']} of {held['scored']} held-out" in text


# What each "Where Mubit is called" link must land on; a moved line turns this red.
CALLS = {
    ("agent/commentator.py", 36): "MUBIT_URL =",
    ("agent/commentator.py", 806): "base_url=MUBIT_URL",
    ("agent/commentator.py", 321): "def commentate(",
    ("agent/commentator.py", 741): "provider.call(request)",
    ("agent/commentator.py", 390): "def correct(",
    ("agent/commentator.py", 434): "ask(trainer)",
    ("core/app.py", 432): "d.correct,",
    ("core/app.py", 70): "match_fixes(",
    ("agent/scorecheck.py", 83): "def teach(",
    ("eval/seed_scorecheck.py", 82): "def send(",
    ("core/ledger.py", 43): "def ledger(",
    ("core/app.py", 615): '@app.get("/ledger")',
}


def test_the_readme_mubit_call_sites_point_at_the_calls():
    text = readme_numbers.README.read_text()
    links = {(f, int(n)) for f, n in re.findall(r"\]\(([\w/]+\.py)#L(\d+)\)", text)}
    assert links == set(CALLS)
    for (f, n), want in CALLS.items():
        assert want in (ROOT / f).read_text().splitlines()[n - 1], (f, n)
