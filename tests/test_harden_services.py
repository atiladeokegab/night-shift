"""A provider that fails on the second try, or answers with a body we can't read, gets the
documented fallback instead of an error: the data's line, the status line, a 502."""

import httpx
import pytest

from core import converse, insight
from core.store import Store
from data.matches import load_moments, match_header
from tests.test_converse import mint, started, talk

KOBE = "0020500591"
WRONG = "Fifty-eight for Bryant!"  # 58 is in none of Kobe's first moments
BAD = "What just happened? The Lakers extend their lead to eighteen points, 120 to 102!"


def test_a_moment_whose_retry_errors_says_the_data_line():
    m = load_moments(KOBE)[0]
    tries = iter([{"text": WRONG}])

    def commentate(moment, history):
        try:
            return next(tries)
        except StopIteration:
            raise httpx.ReadTimeout("provider timed out") from None

    got = insight.checked(commentate, m, [])
    assert got["fallback"] and got["text"] == insight.fallback_text(match_header(KOBE), m)
    assert got["tried"] == WRONG


def test_an_answer_whose_retry_errors_says_the_status_line():
    past = load_moments(KOBE)[:22]
    tries = iter([{"text": BAD}])

    def ask(question, past, lines, wrong=()):
        try:
            return next(tries)
        except StopIteration:
            raise httpx.ReadTimeout("provider timed out") from None

    got = insight.checked_answer(ask, "What just happened?", past, [])
    assert got["fallback"] and got["tried"] == BAD


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b"[]"])
def test_an_unreadable_signed_url_is_a_502_not_a_500(tmp_path, monkeypatch, body):
    real_signed, real_client = converse.signed_url, httpx.AsyncClient
    client, _, _ = talk(tmp_path, monkeypatch)
    monkeypatch.setattr(converse, "signed_url", real_signed)
    reply = httpx.MockTransport(lambda req: httpx.Response(200, content=body))
    monkeypatch.setattr(converse.httpx, "AsyncClient", lambda **kw: real_client(transport=reply))
    with client:
        resp = mint(client, started(client))
    assert resp.status_code == 502 and "sk-secret-key" not in resp.text


@pytest.mark.parametrize(
    "send",
    [
        {"content": b"not json"},
        {"json": [{"role": "user", "content": "hi"}]},
        {"json": {"messages": "hi"}},
        {"json": {"messages": ["hi"]}},
    ],
)
def test_a_chat_body_that_is_not_a_json_object_of_messages_is_a_400(tmp_path, monkeypatch, send):
    client, _, _ = talk(tmp_path, monkeypatch)
    with client:
        resp = client.post(
            "/converse/v1/chat/completions",
            headers={"Authorization": "Bearer llm-secret"},
            **send,
        )
    assert resp.status_code == 400


def test_a_stat_line_outage_logs_the_error_type_not_its_text(tmp_path, caplog):
    moments = load_moments("3869685")
    gaps = insight.Gaps("3869685", Store(tmp_path))

    def down(moment, history):
        raise RuntimeError("403 for url https://api.example/v1?key=sk-secret-key")

    with caplog.at_level("WARNING"):
        gaps.line(moments[:5], 2, 100.0, down, "Jim said it", [], 200.0)
    assert "RuntimeError" in caplog.text and "sk-secret-key" not in caplog.text
