"""Ingest hardening: a flaky network, a crashed cache write and malformed upstream records. No
network: httpx.get and the feed's fetches are replaced."""

import csv
import io
import json
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from agent import feed, packs
from scripts import build_graph


class _Resp:
    content = b'{"ok": 1}'

    def raise_for_status(self):
        pass


def test_fetch_retries_a_transient_network_error(tmp_path, monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise httpx.ConnectError("reset")
        return _Resp()

    monkeypatch.setattr(feed, "CACHE", tmp_path)
    monkeypatch.setattr(feed.httpx, "get", get)
    monkeypatch.setattr(feed.time, "sleep", lambda s: None)
    assert feed._fetch("https://x/y.json", "y.json") == b'{"ok": 1}'
    assert len(calls) == 2


def test_fetch_never_caches_a_half_written_file(tmp_path, monkeypatch):
    monkeypatch.setattr(feed, "CACHE", tmp_path)
    monkeypatch.setattr(feed.httpx, "get", lambda url, **kw: _Resp())
    real = Path.write_bytes

    def crash(self, data):  # the disk fills or the process dies mid-write
        real(self, data[:3])
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", crash)
    with pytest.raises(OSError):
        feed._fetch("https://x/y.json", "y.json")
    monkeypatch.setattr(Path, "write_bytes", real)
    assert feed._fetch("https://x/y.json", "y.json") == b'{"ok": 1}'  # fetched again, not '{"o'


def test_football_float_clock_and_junk_event_do_not_crash_the_match():
    header = {"sport": "football", "match_id": "1", "home": "Reds", "away": "Blues"}
    shot = {
        "id": "s1",
        "type": {"name": "Shot"},
        "team": {"name": "Reds"},
        "player": {"name": "Ann"},
        "period": 1,
        "minute": 10.0,  # a float clock from a re-serialised feed
        "second": 5.0,
        "shot": {"outcome": {"name": "Goal"}},
    }
    moments = feed.football_moments(header, [None, "junk", shot])
    assert [(m["type"], m["clock"], m["score"]) for m in moments] == [
        ("Shot", "10:05", {"home": 1, "away": 0})
    ]


def test_build_graph_skips_and_counts_a_malformed_match(monkeypatch, capsys):
    good = {"match_id": 1}
    bad = {"match_id": 2}
    monkeypatch.setattr(build_graph, "MATCHES", {("football", "1"): (9, 9)})
    monkeypatch.setattr(feed, "statsbomb_matches", lambda c, s: [good, bad])

    def match(m):
        if m is bad:
            raise KeyError("home_score")  # a partial upstream record
        return {"mid": "1"}, [{"player": "Ann"}]

    monkeypatch.setattr(build_graph, "football_match", match)
    fixtures, apps = build_graph.football()
    assert fixtures == [{"mid": "1"}] and apps == [{"player": "Ann"}]
    assert "skipped 1 malformed" in capsys.readouterr().out


def test_build_graph_never_skips_a_network_failure(monkeypatch):
    monkeypatch.setattr(build_graph, "MATCHES", {("football", "1"): (9, 9)})
    monkeypatch.setattr(feed, "statsbomb_matches", lambda c, s: [{"match_id": 1}])

    def match(m):
        raise httpx.ConnectError("down")  # a missing match is data loss, not a bad record

    monkeypatch.setattr(build_graph, "football_match", match)
    with pytest.raises(httpx.ConnectError):
        build_graph.football()


def _rows_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def _tar_xz(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(text.encode())
        tar.addfile(info, io.BytesIO(text.encode()))
    return buf.getvalue()


def test_an_archive_without_a_csv_is_a_clear_error(monkeypatch):
    data = _tar_xz("README.txt", "moved")
    monkeypatch.setattr(feed, "_fetch", lambda *a, **kw: data)
    with pytest.raises(ValueError, match="no CSV"):
        feed.nba_rows("0020500591")
    with pytest.raises(ValueError, match="no CSV"):
        packs.nba_shots("shotdetail_2005")
    monkeypatch.setattr(
        build_graph.httpx, "get", lambda *a, **kw: type("R", (_Resp,), {"content": data})()
    )
    with pytest.raises(ValueError, match="no CSV"):
        list(build_graph._archive("nbastats_2005"))


def test_football_goalkeeper_that_is_not_a_dict_is_ignored():
    header = {"sport": "football", "match_id": "1", "home": "Reds", "away": "Blues"}
    keeper = {"type": {"name": "Goal Keeper"}, "goalkeeper": "Saved", "period": 1}
    shot = {"id": "s1", "type": {"name": "Shot"}, "team": {"name": "Reds"}, "period": 1}
    moments = feed.football_moments(header, [keeper, shot])
    assert [m["type"] for m in moments] == ["Shot"]


def test_cricket_junk_innings_over_and_delivery_are_skipped():
    ball = {"batter": "A", "bowler": "B", "runs": {"batter": 4, "total": 4}}
    match = {
        "innings": ["junk", {"team": "X", "overs": [7, {"over": 0, "deliveries": [None, ball]}]}]
    }
    moments = feed.cricket_moments({"match_id": "1"}, match)
    assert [(m["type"], m["score"]["runs"]) for m in moments] == [("Four", 4)]
    assert [d for *_, d in packs._balls(match)] == [
        ball
    ]  # the pack's balls stay the moments' balls


def test_build_graph_cricket_skips_and_counts_a_malformed_file(monkeypatch, capsys):
    good = {
        "info": {"teams": ["X", "Y"], "dates": ["2022-01-01"], "players": {"X": ["A"], "Y": ["B"]}},
        "innings": [
            {
                "team": "X",
                "overs": [
                    {
                        "deliveries": [
                            {"batter": "A", "bowler": "B", "runs": {"batter": 1, "total": 1}}
                        ]
                    }
                ],
            }
        ],
    }
    bad = {"info": {"dates": ["2022-02-01"]}}  # no teams: a partial upstream record
    files = {"1.json": good, "2.json": bad, "3.json": {"info": {"dates": ["1999-01-01"]}}}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for n, m in files.items():
            z.writestr(n, json.dumps(m))
    monkeypatch.setattr(build_graph, "MATCHES", {("cricket", "1"): ("2022",)})
    monkeypatch.setattr(feed, "cricsheet_zip", lambda: zipfile.ZipFile(archive))
    fixtures, apps = build_graph.cricket()
    assert [f["mid"] for f in fixtures] == ["1"] and [a["player"] for a in apps] == ["A", "B"]
    assert "skipped 1 malformed" in capsys.readouterr().out


def test_build_graph_basketball_skips_and_counts_malformed_rows(monkeypatch, capsys):
    shot = {"GAME_ID": "1", "GAME_DATE": "20051201", "HTM": "LAL", "VTM": "TOR"}
    pbp = {
        "GAME_ID": "1",
        "EVENTMSGTYPE": "1",
        "HOMEDESCRIPTION": "Bryant 2' Layup",
        "VISITORDESCRIPTION": "",
        "SCORE": "0 - 2",
        **{
            f"PLAYER{n}_{k}": v
            for n in (1, 2, 3)
            for k, v in (
                ("TEAM_ABBREVIATION", "LAL" if n == 1 else ""),
                ("NAME", "Kobe Bryant" if n == 1 else ""),
                ("ID", "977" if n == 1 else ""),
                ("TEAM_CITY", "Los Angeles" if n == 1 else ""),
                ("TEAM_NICKNAME", "Lakers" if n == 1 else ""),
            )
        },
    }
    tor = {**pbp, "SCORE": "2 - 2", "VISITORDESCRIPTION": "x", "HOMEDESCRIPTION": ""}
    tor |= {"PLAYER1_TEAM_ABBREVIATION": "TOR", "PLAYER1_NAME": "Mo Pete", "PLAYER1_ID": "9"}
    tor |= {"PLAYER1_TEAM_CITY": "Toronto", "PLAYER1_TEAM_NICKNAME": "Raptors"}
    archives = {
        "shotdetail_2005": [shot, {**shot, "GAME_ID": "2", "GAME_DATE": None}],
        "nbastats_2005": [pbp, tor, {**pbp, "SCORE": "two - 4"}],
    }
    monkeypatch.setattr(build_graph, "_archive", lambda name: iter(archives.get(name, [])))
    fixtures, apps = build_graph.basketball_season(2005)
    assert [(f["home"], f["away"], f["hg"], f["ag"]) for f in fixtures] == [
        ("Los Angeles Lakers", "Toronto Raptors", 2, 2)
    ]
    assert "skipped 2 malformed" in capsys.readouterr().out
