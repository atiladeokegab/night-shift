"""Create or update the ElevenLabs agent for Talk to the commentator (#380). A keyed step: Zeus
runs it, builders do not.

    ELEVENLABS_API_KEY=... CONVERSE_LLM_SECRET=<a long random string> \\
        uv run python scripts/converse_agent.py --url https://<service>/converse/v1 [--agent-id ID]

It stores CONVERSE_LLM_SECRET as a workspace secret, points the agent's custom LLM at --url (the
agent calls <url>/chat/completions) and prints CONVERSE_AGENT_ID. Deploy with CONVERSE_AGENT_ID and
CONVERSE_LLM_SECRET set (scripts/deploy.sh). --dry-run prints the agent's config and calls nothing.
"""

import argparse
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API = "https://api.elevenlabs.io/v1/convai"

# {{ctx}} is a dynamic variable the page fills in at the start; core/converse.py finds the
# conversation by it. The words themselves come from the Ask prompt behind the custom LLM.
PROMPT = (
    "You are the Touchline commentator, chatting with a fan while the match is paused. "
    "Conversation ctx={{ctx}}. Everything you say comes from the server behind this agent."
)
FIRST_MESSAGE = "Match paused. What do you want to know?"


def build_config(url: str, secret_id: str, voice_id: str) -> dict:
    return {
        "name": "Touchline commentator",
        "conversation_config": {
            "agent": {
                "first_message": FIRST_MESSAGE,
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": {"ctx": "none"}},
                "prompt": {
                    "prompt": PROMPT,
                    "llm": "custom-llm",
                    "custom_llm": {
                        "url": url,
                        "model_id": "touchline",
                        "api_key": {"secret_id": secret_id},
                    },
                },
            },
            "tts": {"voice_id": voice_id},
            "turn": {"turn_timeout": 8},
            "conversation": {"max_duration_seconds": 600},
        },
        "platform_settings": {"auth": {"enable_auth": True}},
    }


ROOT = "https://api.elevenlabs.io/v1"
SECRET_NAME = "touchline_converse"


def ensure_voice(http: httpx.Client, voice_id: str) -> None:
    """agents/create refuses a library voice the workspace lacks (400 voice_not_found): add it."""
    have = http.get(f"{ROOT}/voices")
    have.raise_for_status()
    if any(v["voice_id"] == voice_id for v in have.json()["voices"]):
        return
    found = http.get(f"{ROOT}/shared-voices", params={"search": voice_id})
    found.raise_for_status()
    shared = next((v for v in found.json()["voices"] if v["voice_id"] == voice_id), None)
    if shared is None:
        raise SystemExit(f"voice {voice_id} is neither in the workspace nor in the voice library")
    owner = shared["public_owner_id"]
    http.post(
        f"{ROOT}/voices/add/{owner}/{voice_id}", json={"new_name": shared["name"]}
    ).raise_for_status()


def ensure_secret(http: httpx.Client, value: str) -> str:
    """The workspace secret's id: the existing one, updated, so a rerun makes no duplicate."""
    listed = http.get("/secrets")
    listed.raise_for_status()
    old = next((s for s in listed.json()["secrets"] if s["name"] == SECRET_NAME), None)
    body = {"name": SECRET_NAME, "value": value}
    if old:
        http.patch(
            f"/secrets/{old['secret_id']}", json={"type": "update", **body}
        ).raise_for_status()
        return old["secret_id"]
    made = http.post("/secrets", json={"type": "new", **body})
    made.raise_for_status()
    return made.json()["secret_id"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", required=True, help="https://<service>/converse/v1")
    ap.add_argument("--agent-id", help="update this agent instead of creating one")
    ap.add_argument("--voice-id", help="an ElevenLabs voice id; default: football's commentator")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    voice_id = args.voice_id
    if not voice_id:
        from core.voice import default_voice

        voice_id = default_voice("football")["eleven_id"]
    if args.dry_run:
        print(json.dumps(build_config(args.url, "<secret_id>", voice_id), indent=2))
        return 0
    key, secret = os.environ.get("ELEVENLABS_API_KEY"), os.environ.get("CONVERSE_LLM_SECRET")
    if not (key and secret):
        print("set ELEVENLABS_API_KEY and CONVERSE_LLM_SECRET", file=sys.stderr)
        return 1
    with httpx.Client(base_url=API, headers={"xi-api-key": key}, timeout=30) as http:
        ensure_voice(http, voice_id)
        config = build_config(args.url, ensure_secret(http, secret), voice_id)
        if args.agent_id:
            http.patch(f"/agents/{args.agent_id}", json=config).raise_for_status()
            agent_id = args.agent_id
        else:
            created = http.post("/agents/create", json=config)
            created.raise_for_status()
            agent_id = created.json()["agent_id"]
    print(f"CONVERSE_AGENT_ID={agent_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
