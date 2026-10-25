"""Stored and bundled data that a crash or a bad file left malformed must not take a request down."""

import json
import shutil

import data.matches as matches
from core.store import Store


def test_store_survives_a_half_written_row(tmp_path):
    store = Store(tmp_path)
    store.append("lines", {"line_id": "a"})
    with (tmp_path / "lines.jsonl").open("a") as f:
        f.write('{"line_id": "b", "te')  # a process killed mid-append
    store.append("lines", {"line_id": "c"})
    # the torn row is dropped; the rows either side of it are kept
    assert [r["line_id"] for r in Store(tmp_path).all("lines")] == ["a", "c"]
    assert [r["line_id"] for r in store.all("lines")] == ["a", "c"]


def test_a_malformed_match_file_leaves_the_others_listed(tmp_path, monkeypatch):
    good = next(matches.SAMPLE.glob("f1-*.json"))
    shutil.copy(good, tmp_path / good.name)
    (tmp_path / "football-1.json").write_text('{"moments": []}', encoding="utf-8")  # no header
    (tmp_path / "football-2.json").write_text('{"header": ', encoding="utf-8")  # cut short
    monkeypatch.setattr(matches, "SAMPLE", tmp_path)
    got = matches.list_matches()
    assert [m["match_id"] for m in got] == [json.loads(good.read_text())["header"]["match_id"]]
