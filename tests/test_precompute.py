"""scripts/precompute.py against a fake server (httpx MockTransport): no network, no spend."""

import json

import httpx

from scripts import precompute

TOKEN = "s3cret-producer-token"


def fake_site(seen: list[httpx.Request]):
    lines = [
        {"line_id": "L1", "speaker": "lead", "text": "Goal!"},
        {"line_id": "L2", "speaker": "analyst", "text": "Lovely move."},
    ]
    sse = "".join(f"event: line\ndata: {json.dumps(ln)}\n\n" for ln in lines)
    sse += "event: end\ndata: {}\n\n"

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        if path == "/matches":
            return httpx.Response(200, json=[{"match_id": "m1", "sport": "football"}])
        if path == "/voices":
            return httpx.Response(200, json=[{"id": "brit", "default_for": "football"}])
        if path == "/stats":
            budget = {"daily_budget_usd": 50, "spent_today_usd": 2, "off_air": False}
            return httpx.Response(200, json={"budget": budget})
        if path == "/replays":
            return httpx.Response(200, json={"replay_id": "r1"})
        if path == "/replays/r1/stream":
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        if path.endswith("/audio"):
            return httpx.Response(200, content=b"mp3")
        return httpx.Response(404)

    return handler


def test_one_match_fresh_with_token_and_both_clips(monkeypatch, capsys):
    monkeypatch.setenv("PRODUCER_TOKEN", TOKEN)
    seen: list[httpx.Request] = []
    site = httpx.MockTransport(fake_site(seen))
    code = precompute.main(["--base", "http://site"], transport=site)
    out = capsys.readouterr()

    assert code == 0
    post = next(r for r in seen if r.url.path == "/replays")
    assert json.loads(post.content)["fresh"] is True
    assert post.headers["x-producer-token"] == TOKEN
    audio = [str(r.url) for r in seen if r.url.path.endswith("/audio")]
    assert audio == ["http://site/lines/L1/audio?voice=brit", "http://site/lines/L2/audio"]
    assert "m1 lines=2 audio_ok=2 audio_failed=0" in out.out
    assert TOKEN not in out.out + out.err


def test_a_failed_clip_fails_the_run_and_never_prints_the_token(monkeypatch, capsys):
    monkeypatch.setenv("PRODUCER_TOKEN", TOKEN)
    site = fake_site([])

    def handler(req):
        return httpx.Response(503) if req.url.path == "/lines/L2/audio" else site(req)

    assert precompute.main(["--base", "http://site"], transport=httpx.MockTransport(handler)) == 1
    out = capsys.readouterr()
    assert "audio_ok=1 audio_failed=1" in out.out
    assert TOKEN not in out.out + out.err
