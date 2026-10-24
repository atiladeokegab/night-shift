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
