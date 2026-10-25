"""Ingest hardening: a flaky network, a crashed cache write and malformed upstream records. No
network: httpx.get and the feed's fetches are replaced."""

from pathlib import Path

import httpx
import pytest

from agent import feed
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
