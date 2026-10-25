import json

import httpx

from scripts import fix_then_later


def stream(lines):
    rows = []
    for ln in lines:
        rows += ["event: line", f"data: {json.dumps(ln)}", ""]
    return "\n".join(rows + ["event: end", "data: {}", ""])


def fake(seen):
    said = {
        8: [{"line_id": "a8", "moment_idx": 8, "text": "Brighton score!", "speaker": "lead"}],
        9: [
            {"moment_idx": 8, "text": "Brighton score!", "history": True},
            {"moment_idx": 19, "text": "The Seagulls lead two-one!", "mubit_request_ids": ["r19"]},
            {"moment_idx": 19, "text": "Stat, orientation", "speaker": "analyst"},
        ],
    }
    started = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, dict(req.headers), req.content))
        if req.url.path == "/replays":
            started.append(json.loads(req.content)["start_idx"])
            return httpx.Response(200, json={"replay_id": f"r{len(started)}"})
        if req.url.path.endswith("/stream"):
            at = started[-1]
            lines = (
                said[at]
                if at == 9
                else said[at] + [{"moment_idx": 19, "text": "Brighton lead two-one!"}]
            )
            return httpx.Response(200, text=stream(lines))
        if req.url.path == "/lines/a8/fix":
            return httpx.Response(200, json={"said": "Brighton score!", "mubit_request_id": "c1"})
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def test_the_fix_is_posted_with_the_token_and_later_lines_compared(monkeypatch, capsys):
    seen = []
    real = httpx.Client
    monkeypatch.setattr(
        fix_then_later.httpx, "Client", lambda **kw: real(transport=fake(seen), **kw)
    )
    monkeypatch.setenv("PRODUCER_TOKEN", "secret")
    monkeypatch.setattr("sys.argv", ["fix_then_later.py", "http://test"])
    fix_then_later.main()
    out = capsys.readouterr().out
    fixes = [s for s in seen if s[1] == "/lines/a8/fix"]
    assert fixes[0][2]["x-producer-token"] == "secret"
    assert "secret" not in out
    assert 'the producer\'s line: "Elisabeth Terland scores! The Seagulls lead one-nil."' in out
    assert "before the fix: Brighton lead two-one!" in out
    assert "after the fix:  The Seagulls lead two-one!" in out
    assert "CHANGED" in out and "requests: r19" in out
    assert "Stat, orientation" not in out  # the analyst's lines are left out
