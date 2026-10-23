# The page: web/ (React + Vite, #18) built to web/dist; an image without web/ still builds.
FROM node:22-slim AS web
WORKDIR /src
COPY . .
RUN if [ -f web/package.json ]; then cd web && npm ci && npm run build; else mkdir -p web/dist; fi

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.0 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Dependencies first, so a code change doesn't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
COPY --from=web /src/web/dist web/dist
RUN uv sync --locked --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
USER 10001
CMD ["sh", "-c", "uvicorn core.main:app --host 0.0.0.0 --port ${PORT}"]
