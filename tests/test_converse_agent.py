"""scripts/converse_agent.py against a mocked ElevenLabs: no key, no network."""

import json

import httpx

from scripts import converse_agent as agent


def api(voices, shared, secrets):
    calls = []

    def handle(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, json.loads(req.content or b"null")))
        path = req.url.path
        if path == "/v1/voices":
            return httpx.Response(200, json={"voices": [{"voice_id": v} for v in voices]})
        if path == "/v1/shared-voices":
            return httpx.Response(200, json={"voices": shared})
        if path == "/v1/convai/secrets" and req.method == "GET":
            return httpx.Response(200, json={"secrets": secrets})
        return httpx.Response(200, json={"secret_id": "new_id"})

    client = httpx.Client(base_url=agent.API, transport=httpx.MockTransport(handle))
    return client, calls


def test_a_library_voice_missing_from_the_workspace_is_added_first():
    shared = [{"voice_id": "v1", "public_owner_id": "own", "name": "Connor"}]
    http, calls = api([], shared, [])
    agent.ensure_voice(http, "v1")
    assert calls[-1] == ("POST", "/v1/voices/add/own/v1", {"new_name": "Connor"})


def test_a_voice_already_in_the_workspace_is_left_alone():
    http, calls = api(["v1"], [], [])
    agent.ensure_voice(http, "v1")
    assert [c[0] for c in calls] == ["GET"]


def test_a_rerun_updates_the_secret_instead_of_making_a_second():
    http, calls = api([], [], [{"name": "touchline_converse", "secret_id": "old_id"}])
    assert agent.ensure_secret(http, "s") == "old_id"
    assert calls[-1][:2] == ("PATCH", "/v1/convai/secrets/old_id")
    assert not any(c[0] == "POST" for c in calls)


def test_the_first_run_creates_the_secret():
    http, calls = api([], [], [])
    assert agent.ensure_secret(http, "s") == "new_id"
    assert calls[-1][0] == "POST"
