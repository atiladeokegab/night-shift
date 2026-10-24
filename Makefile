.PHONY: dev check smoke load demo-check bootstrap deploy

PROJECT ?= hackathon-starter-ao

dev:
	uv run uvicorn core.main:app --reload

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q

# The merge gate: offline even when .env holds a real key. Replays each sample with FakeProvider.
smoke: check
	MUBIT_API_KEY= MUBIT_FALLBACK_KEY= ANTHROPIC_API_KEY= ELEVENLABS_API_KEY= \
		MAX_LIVE_REPLAYS=0 REPLAYS_PER_HOUR=0 ASKS_PER_HOUR=0 DAILY_BUDGET_USD=0 uv run python -m core.smoke

# Five judges at once on a local server, offline: first-line p95, 429s and 5xx, /health, memory.
# STORE=gcs runs GcsStore over a bucket with GCS-like latency, as production stores.
load:
	uv run python scripts/load_check.py --store $(or $(STORE),local)

# Before a live demo: the live site (or URL=...) is healthy, voiced by ElevenLabs and under budget.
# Starts one short smoke replay; nothing else is written.
demo-check:
	uv run python scripts/demo_check.py $(URL)

# One-time GCP setup: secrets from MUBIT_API_KEY and ELEVENLABS_API_KEY, the state bucket, IAM.
bootstrap:
	PROJECT=$(PROJECT) scripts/bootstrap.sh

# Cloud Run from this checkout; prints the URL and runs the live smoke on it. Only the deploy
# owner runs it, from main (IDEA.md); SERVICE=night-shift-staging for a rehearsal.
deploy:
	PROJECT=$(PROJECT) scripts/deploy.sh
