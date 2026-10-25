"""The offline data audit passes on every bundled match, and each kind of check can go red."""

import copy
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "data_audit", Path(__file__).parent.parent / "scripts" / "data_audit.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
SAMPLE = audit.DATA / "sample"


def _match(name: str) -> tuple[dict, list[dict]]:
    data = json.loads((SAMPLE / name).read_text(encoding="utf-8"))
    return data["header"], data["moments"]


def test_every_bundled_match_passes_for_all_four_sports():
    rows = audit.audit()
    assert {r["sport"] for r in rows} == {"football", "cricket", "basketball", "f1"}
    assert [(r["match_id"], r["fails"]) for r in rows if r["fails"]] == []
    assert all(r["checks"][0] == "sample" and r["moments"] for r in rows)


def test_a_score_going_backwards_fails():
    header, moments = _match("football-3869685.json")
    bad = copy.deepcopy(moments)
    bad[-1]["score"]["home"] -= 1
    assert audit.check_match(header, moments) == []
    assert any(f.startswith("home falls") for f in audit.check_match(header, bad))


def test_moments_out_of_clock_order_fail():
    for name in ("cricket-1298150.json", "basketball-0049700088.json", "f1-9636.json"):
        header, moments = _match(name)
        bad = copy.deepcopy(moments)
        bad[3]["clock"], bad[4]["clock"] = bad[4]["clock"], bad[3]["clock"]
        if bad[3]["clock"] == bad[4]["clock"]:
            continue
        assert any("is before moment" in f for f in audit.check_match(header, bad)), name


def test_a_missing_field_or_wrong_idx_fails():
    header, moments = _match("f1-9636.json")
    bad = copy.deepcopy(moments)
    del bad[2]["score"]
    assert audit.check_match(header, bad) == ["moment 2 lacks ['score']"]
    bad = copy.deepcopy(moments)
    bad[2]["idx"] = 7
    assert "moment 2 has idx 7" in audit.check_match(header, bad)


def test_an_orphan_pack_or_a_pack_reaching_match_day_fails(tmp_path):
    for folder in ("sample", "packs", "video"):
        (tmp_path / folder).mkdir()
    (tmp_path / "sample" / "f1-9636.json").write_bytes((SAMPLE / "f1-9636.json").read_bytes())
    pack = json.loads((audit.DATA / "packs" / "f1-9636.json").read_text(encoding="utf-8"))
    pack["window"]["to"] = "2024-11-03"
    (tmp_path / "packs" / "f1-9636.json").write_text(json.dumps(pack), encoding="utf-8")
    (tmp_path / "packs" / "football-1.json").write_text("{}", encoding="utf-8")
    rows = {r["match_id"]: r["fails"] for r in audit.audit(tmp_path)}
    assert "pack f1-9636.json reaches the match day" in rows["9636"]
    assert rows["1"]
