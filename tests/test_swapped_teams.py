"""#378: a score said against the wrong teams ("Lakers 88, Raptors 95" at 95-88, "88-95 to the
Lakers") fails the number check, for football and basketball, beyond the "<team> lead a to b" case
of #407. Only an exact swap fails: tallies that share the score's digits pass."""

import json
from pathlib import Path

from core import insight
from data.matches import load_moments, match_header

LABELS = Path(__file__).parent.parent / "eval" / "checker_labels.jsonl"
KOBE, FINAL = "0020500591", "3869685"


def at(match_id: str, idx: int):
    i = next(i for i, m in enumerate(load_moments(match_id)) if m["idx"] == idx)
    return load_moments(match_id)[i], load_moments(match_id)[:i], match_header(match_id)


def wrong(match_id: str, idx: int, text: str) -> list[str]:
    m, past, header = at(match_id, idx)
    return insight.wrong_numbers(text, m, header, past)


def test_basketball_scores_on_the_wrong_teams_fail():
    m, _, h = at(KOBE, 11)  # Lakers 95, Raptors 88
    assert (m["score"]["home"], m["score"]["away"]) in ((95, 88), (88, 95))
    home, away = (h["home"].split()[-1], h["away"].split()[-1])
    hi, lo = max(m["score"].values()), min(m["score"].values())
    lead, trail = (home, away) if m["score"]["home"] > m["score"]["away"] else (away, home)
    bad = [
        f"Fifty-seven tonight! {lead} {lo}, {trail} {hi}.",
        f"Fifty-seven tonight! {lo} to {hi} to the {lead}.",
        f"Fifty-seven tonight! {lo}-{hi} to {lead}.",
    ]
    for line in bad:
        assert any("wrong" in w or "puts their score last" in w for w in wrong(KOBE, 11, line)), (
            line
        )
    for line in (
        f"Fifty-seven tonight! {lead} {hi}, {trail} {lo}.",
        f"Fifty-seven tonight! {hi} to {lo} to the {lead}.",
        f"Fifty-seven tonight! {lead} {hi} {trail} {lo}.",
    ):
        assert wrong(KOBE, 11, line) == [], line


def test_football_scores_on_the_wrong_teams_fail():
    i = next(
        i for i, m in enumerate(load_moments(FINAL)) if m["score"]["home"] != m["score"]["away"]
    )
    m = load_moments(FINAL)[i]
    h = match_header(FINAL)
    hm, aw = m["score"]["home"], m["score"]["away"]
    home, away = h["home"].split()[-1], h["away"].split()[-1]
    assert insight._swapped_teams(f"{home} {aw}, {away} {hm}.", m, h)
    assert not insight._swapped_teams(f"{home} {hm}, {away} {aw}.", m, h)
    assert insight._swapped_teams(f"{aw}-{hm} to {home}.", m, h)


def test_a_tally_that_shares_the_scores_digits_still_passes():
    m, _, h = at(KOBE, 11)
    hi, lo = max(m["score"].values()), min(m["score"].values())
    for line in (
        f"Lakers {lo} rebounds, Raptors {hi} points.",
        f"Lakers took {lo} shots and Raptors {hi}.",
        f"Raptors {hi} fouls, Lakers {lo} fouls.",
    ):
        assert insight._swapped_teams(line, m, h) == [], line


def test_twenty_true_stored_lines_that_name_both_teams_stay_green():
    rows = [json.loads(line) for line in LABELS.read_text().splitlines()]
    kept = 0
    for r in rows:
        if r["label"] != "right" or r["match_id"] not in (KOBE, FINAL):
            continue
        m, _, h = at(r["match_id"], r["moment_idx"])
        side, _ = insight._sides(h)
        words = {w.lower().strip(".,!?") for w in r["text"].split()}
        if len({v for k, v in side.items() if " " not in k and k in words}) < 2:
            continue
        assert insight._swapped_teams(r["text"], m, h) == [], r["text"]
        kept += 1
    assert kept >= 20, kept
