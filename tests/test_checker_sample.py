"""Sampling a short store export should return its eligible lines, not a 300-line target."""

import hashlib
import json

import pytest

from eval import checker_eval


@pytest.fixture
def synthetic_matches(monkeypatch):
    monkeypatch.setattr(checker_eval, "bundled", lambda: {"a": {}, "b": {}})
    monkeypatch.setattr(
        checker_eval,
        "load_moments",
        lambda _match_id: [{"idx": 0}, {"idx": 1}],
    )


def write_lines(tmp_path, rows):
    path = tmp_path / "lines.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def line(match_id, i, **extra):
    return {
        "line_id": f"{match_id}-{i:03d}",
        "match_id": match_id,
        "moment_idx": 0,
        "text": f"line {i}",
        **extra,
    }


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [line("a", 0, fallback=True)],
        [line("a", 0, text="")],
        [line("not-bundled", 0)],
    ],
    ids=["empty", "all-fallback", "all-blank", "all-unbundled"],
)
def test_empty_eligible_pool_returns_no_lines(tmp_path, synthetic_matches, rows):
    assert checker_eval.sample(write_lines(tmp_path, rows)) == []


@pytest.mark.parametrize("count", [1, 30, 31])
def test_short_pool_returns_every_eligible_line_once(tmp_path, synthetic_matches, count):
    rows = [line("a", i) for i in range(count)]
    selected = checker_eval.sample(write_lines(tmp_path, rows))
    assert len(selected) == count
    assert {row["line_id"] for row in selected} == {row["line_id"] for row in rows}


@pytest.mark.parametrize("size", [0, 1, 10, 59, 60, 75])
def test_requested_size_is_exact_and_repeatable(tmp_path, synthetic_matches, size):
    rows = [line("a", i) for i in range(30)] + [line("b", i) for i in range(30)]
    path = write_lines(tmp_path, rows)
    first = checker_eval.sample(path, size=size, seed=19)
    second = checker_eval.sample(path, size=size, seed=19)
    assert len(first) == min(size, len(rows))
    assert len({row["line_id"] for row in first}) == len(first)
    assert first == second


def test_negative_requested_size_is_rejected(tmp_path, synthetic_matches):
    with pytest.raises(ValueError):
        checker_eval.sample(write_lines(tmp_path, [line("a", 0)]), size=-1)


def test_dedup_skip_analyst_and_fallback_filters_are_preserved(tmp_path, synthetic_matches):
    rows = [
        line("a", 0, text="keep this"),
        line("a", 1, text=" keep this "),  # duplicate after whitespace trimming
        line("a", 2, text="skip this"),
        line("a", 3, text="analyst line", speaker="analyst"),
        line("a", 4, text="fallback line", fallback=True),
    ]
    path = write_lines(tmp_path, rows)
    skip = frozenset({("a", 0, "skip this")})
    ordinary = checker_eval.sample(path, size=10, skip=skip)
    with_analyst = checker_eval.sample(path, size=10, analyst=True, skip=skip)
    assert [row["text"] for row in ordinary] == ["keep this"]
    assert {row["text"] for row in with_analyst} == {"keep this", "analyst line"}
    assert all(
        row.get("speaker") == "analyst" for row in with_analyst if row["text"] == "analyst line"
    )


def test_full_pool_seeded_selection_stays_unchanged(tmp_path, synthetic_matches):
    rows = [line(mid, i) for mid in ("a", "b") for i in range(200)]
    selected = checker_eval.sample(write_lines(tmp_path, rows))
    ids = [row["line_id"] for row in selected]
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    assert len(ids) == 300
    assert digest == "0aa909f341b15cb029e6b0064b7567a67bc604f629da113cfe9c79c762c43b79"
