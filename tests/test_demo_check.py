"""scripts/demo_check.py against a fake server (httpx MockTransport): no network, no spend."""

import httpx
import pytest

from scripts import demo_check

READY = {
    "voice": {"provider": "elevenlabs", "last_error": None, "since": None},
    "budget": {"daily_budget_usd": 50.0, "spent_today_usd": 3.21, "off_air": False},
    "linecheck": {"checked": 800, "flags": 12, "rules_missed": 12, "fixes_sent": 3},
}
LINE = 'event: moment\ndata: {"idx": 0}\n\nevent: line\ndata: {"line_id": "L1"}\n\n'


def fake(stats=READY, stream=LINE, audio=(200, "audio/mpeg"), seen=None):
    def handle(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((req.method, req.url.path, req.content, dict(req.headers)))
        match req.method, req.url.path:
            case "GET", "/health":
                return httpx.Response(200, json={"status": "ok"})
            case "GET", "/matches":
                return httpx.Response(200, json=[{"match_id": "9636", "sport": "football"}])
            case "POST", "/replays":
                return httpx.Response(200, json={"replay_id": "r1"})
            case "GET", "/replays/r1/stream":
                return httpx.Response(
                    200, text=stream, headers={"content-type": "text/event-stream"}
                )
            case "GET", "/lines/L1/audio":
                status, kind = audio
                return httpx.Response(
                    status,
                    content=b"ID3" if status == 200 else b'{"detail":"x"}',
                    headers={"content-type": kind},
                )
            case "GET", "/stats":
                return httpx.Response(200, json=stats)
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def run(transport):
    return {
        line.split(":")[0]: (ok, line) for ok, line in demo_check.check("http://t", 5, transport)
    }


def test_a_ready_site_passes_and_only_one_replay_is_written():
    seen = []
    got = run(fake(seen=seen))
    assert list(got) == ["health", "replay", "audio", "stats", "voice", "budget", "linecheck"]
    assert all(ok for ok, _ in got.values()), got
    writes = [(m, p, c) for m, p, c, _ in seen if m != "GET"]
    assert writes == [("POST", "/replays", b'{"match_id":"9636","speed":1000000.0,"smoke":true}')]
    assert not any("x-producer-token" in h for *_, h in seen)


@pytest.mark.parametrize(
    "transport, failed",
    [
        (
            fake(stats={**READY, "voice": {"provider": "browser", "last_error": "quota_exceeded"}}),
            "voice",
        ),
        (fake(audio=(503, "application/json")), "audio"),
        (fake(stats={**READY, "budget": {**READY["budget"], "spent_today_usd": 50.0}}), "budget"),
        (fake(stats={k: v for k, v in READY.items() if k != "linecheck"}), "linecheck"),
        (
            fake(stream='event: error\ndata: {"message": "boom"}\n\nevent: end\ndata: {}\n\n'),
            "replay",
        ),
    ],
)
def test_each_failure_is_named(transport, failed):
    got = run(transport)
    assert [name for name, (ok, _) in got.items() if not ok] == (
        ["replay", "audio"] if failed == "replay" else [failed]
    )


def test_main_exits_non_zero_on_a_fail(monkeypatch, capsys):
    real = demo_check.check
    monkeypatch.setattr(demo_check, "check", lambda url, s: real(url, s, fake(audio=(503, "x"))))
    assert demo_check.main(["http://t"]) == 1
    out = capsys.readouterr().out
    assert "FAIL audio" in out and "PASS health" in out
    monkeypatch.setattr(demo_check, "check", lambda url, s: real(url, s, fake()))
    assert demo_check.main(["http://t"]) == 0
