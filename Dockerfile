FROM node:24-bookworm-slim AS codex-cli
RUN npm install --global @openai/codex@0.166.0 \
    && cp /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-*/vendor/*/bin/codex /usr/local/bin/codex-native \
    && /usr/local/bin/codex-native --version

FROM ghcr.io/astral-sh/uv:0.12.5 AS uv
FROM python:3.14-slim-bookworm AS app
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
ENV PATH="/app/.venv/bin:${PATH}" PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY harness/ harness/
CMD ["uvicorn", "harness.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM app AS worker
COPY --from=codex-cli /usr/local/bin/codex-native /usr/local/bin/codex
ENV HOME=/tmp/worker CODEX_HOME=/tmp/worker/.codex
WORKDIR /workspace
USER 1000:1000
ENTRYPOINT ["python", "-m", "harness.worker"]
CMD ["codex"]
