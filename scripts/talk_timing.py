"""Time to the first spoken sentence of live Talk, for one plain and one tool question.

    CONVERSE_LLM_SECRET=... uv run python scripts/talk_timing.py [--url URL] [--runs 3]

Uses the public replay and token routes, then posts the question to the custom-LLM route as
ElevenLabs does (that route needs the shared secret, which only the deploy holds). Reports the
seconds to the first SSE content chunk and to [DONE]. One replay per run, so it costs one
model call per question.
"""

import argparse
import json
import os
import statistics
import time

import httpx

URL = "https://night-shift-5zvig7nbvq-ew.a.run.app"
MATCH, SPORT = "3754092", "football"
QUESTIONS = {"plain": "Where are we?", "tool": "How many shots has each side had so far?"}


def once(client: httpx.Client, secret: str, question: str) -> tuple[float, float]:
    replay = client.post("/replays", json={"match_id": MATCH, "speed": 4}).json()["replay_id"]
    for _ in range(20):  # 409 until the first moment has happened
        tok = client.get(f"/converse/{SPORT}/{MATCH}/token", params={"replay_id": replay})
        if tok.status_code != 409:
            break
        time.sleep(0.5)
    tok.raise_for_status()
    ctx = tok.json()["ctx"]
    body = {
        "stream": True,
        "messages": [
            {"role": "system", "content": f"You are the commentator. ctx={ctx}"},
            {"role": "user", "content": question},
        ],
    }
    start, first = time.perf_counter(), None
    with client.stream(
        "POST",
        "/converse/v1/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {secret}"},
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]" and first is None:
                delta = json.loads(line[6:])["choices"][0].get("delta", {})
                if delta.get("content"):
                    first = time.perf_counter() - start
    return first or float("nan"), time.perf_counter() - start


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    secret = os.environ["CONVERSE_LLM_SECRET"]
    with httpx.Client(base_url=args.url, timeout=60) as client:
        for name, question in QUESTIONS.items():
            runs = [once(client, secret, question) for _ in range(args.runs)]
            first = statistics.median(r[0] for r in runs)
            whole = statistics.median(r[1] for r in runs)
            print(f"{name}: first sentence {first:.2f}s, whole reply {whole:.2f}s (median)")


if __name__ == "__main__":
    main()
