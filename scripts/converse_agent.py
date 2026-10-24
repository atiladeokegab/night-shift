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
        made = http.post(
            "/secrets", json={"type": "new", "name": "touchline_converse", "value": secret}
        )
        made.raise_for_status()
        config = build_config(args.url, made.json()["secret_id"], voice_id)
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
