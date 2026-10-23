.PHONY: dev check smoke

dev:
	uv run uvicorn core.main:app --reload

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q

# The merge gate: offline even when .env holds a real key. Replays each sample with FakeProvider.
smoke: check
	MUBIT_API_KEY= ANTHROPIC_API_KEY= uv run python -m core.smoke
