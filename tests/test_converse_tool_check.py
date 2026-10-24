"""A tool-backed Talk answer must check lead changes against the current moment."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agent import commentator
from agent.commentator import answer
from core import app as app_module
from core import converse
from core.app import Deps
from core.guard import Guard
from core.replay import Replay
from core.store import Store
from data.matches import load_moments, match_header

MATCH = "0020500591"
IDX = 21
QUESTION = "What just happened?"
BAD = "The Lakers extend their lead to eighteen points, 120 to 102."
CORRECT = "The score stays 120 to 102; the Lakers remain ahead."


class SDKStream:
    def __init__(self, call, text):
        self.call, self.text = call, text
        self.response = SimpleNamespace(headers={"x-middleware-request-id": f"mubit-{call}"})

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def __iter__(self):
        if self.call == 1:
            yield SimpleNamespace(
                type="content_block_start", content_block=SimpleNamespace(type="tool_use")
            )
        else:
            yield SimpleNamespace(type="text", text=self.text)

    def get_final_message(self):
        if self.call == 1:
            content = [SimpleNamespace(type="tool_use", id="tool-1", name="get_score", input={})]
        else:
            content = [SimpleNamespace(type="text", text=self.text)]
        return SimpleNamespace(
            content=content,
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )


class SDKToolClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0
        self.client = SimpleNamespace(messages=self)

    def stream(self, **_):
        self.calls += 1
        text = self.answers[self.calls - 2] if self.calls > 1 else None
        return SDKStream(self.calls, text)

    def call(self, request):
        return converse.Tap(self, lambda _: None, lambda: None).call(request)


def context():
    moments = load_moments(MATCH)
    current = next(i for i, moment in enumerate(moments) if moment["idx"] == IDX)
    return match_header(MATCH), moments, moments[: current + 1]


def client_for(tmp_path, monkeypatch, sdk):
    header, moments, past = context()
    replay = Replay(MATCH, 1)
    replay.events = [{"event": "moment", "data": moment} for moment in past]

    def viewed(replay_id):
        if replay_id != replay.id:
            raise HTTPException(404, "no replay")
        return replay

    def line(moment, _history):
        return {
            "line_id": f"line-{moment['idx']}",
            "match_id": MATCH,
            "moment_idx": moment["idx"],
            "text": "A stored line.",
        }

    def ask(question, before, lines, provider=None, **kwargs):
        return answer(
            question,
            before,
            lines,
            header=header,
            provider=provider or sdk,
            **kwargs,
        )

    deps = Deps(lambda: [header], lambda _match_id: moments, line, ask=ask)
    store = Store(tmp_path)
    env = {
        "ELEVENLABS_API_KEY": "dummy-elevenlabs-key",
        "CONVERSE_AGENT_ID": "dummy-agent",
        "CONVERSE_LLM_SECRET": "dummy-llm-secret",
    }

    async def signed_url(*_):
        return "wss://example.test/conversation"

    monkeypatch.setattr(converse, "signed_url", signed_url)
    monkeypatch.setattr(commentator, "unrecorded_provider", lambda: sdk)
    app = FastAPI()
    app.include_router(
        converse.converse_router(
            need_deps=lambda: deps,
            viewed=viewed,
            asked_so_far=app_module.asked_so_far,
            guard=Guard(env={"DAILY_BUDGET_USD": "50"}),
            store=store,
            env=env,
        )
    )
    return TestClient(app), replay, store, past


def said(response):
    return "".join(
        json.loads(row[6:])["choices"][0]["delta"].get("content", "")
        for row in response.text.splitlines()
        if row.startswith("data: {")
    )


@pytest.mark.parametrize(
    ("answer_text", "expected", "calls"),
    [
        (BAD, CORRECT, 3),
        (CORRECT, CORRECT, 2),
    ],
)
def test_tool_sdk_answer_checks_lead_move_and_keeps_usage(
    tmp_path, monkeypatch, answer_text, expected, calls
):
    sdk = SDKToolClient([answer_text, CORRECT])
    client, replay, store, _past = client_for(tmp_path, monkeypatch, sdk)
    with client:
        token = client.get(
            f"/converse/basketball/{MATCH}/token?replay_id={replay.id}&moment_idx={IDX}"
        )
        ctx = token.json()["ctx"]
        response = client.post(
            "/converse/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": f"ctx={ctx}"},
                    {"role": "user", "content": QUESTION},
                ],
                "stream": True,
            },
            headers={"Authorization": "Bearer dummy-llm-secret"},
        )

    assert token.status_code == 200
    assert response.status_code == 200
    assert BAD not in said(response)
    assert expected in said(response)
    assert sdk.calls == calls
    rows = store.all("answers")
    assert len(rows) == (2 if answer_text == BAD else 1)
    assert rows[0]["tokens_in"] == 22
    assert rows[0]["tokens_out"] == 14
    assert rows[0]["mubit_request_ids"] == ["mubit-1", "mubit-2"]
    if answer_text == BAD:
        assert rows[1]["mubit_request_ids"] == ["mubit-3"]


def test_whole_answer_checker_keeps_unchanged_hypothetical_and_history_controls():
    _header, _moments, past = context()
    tool_context = {"tool_calls": [{"name": "get_score", "output": "Lakers 120, Raptors 102"}]}
    for text in (
        "The Lakers still lead by eighteen points at 120 to 102.",
        "The Lakers could extend their lead to eighteen points.",
        "Earlier the Lakers extended their lead to eighteen points.",
    ):
        assert converse.checked({"text": text, **tool_context}, QUESTION, past, [])
    assert not converse.checked({"text": BAD, **tool_context}, QUESTION, past, [])
