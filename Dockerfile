FROM node:24-bookworm-slim@sha256:190bcf5115694c9d3c4d654a1aa88177d77600a06d67972fd7bf4cf224f7692c AS codex-cli
RUN npm install --global @openai/codex@0.166.0 \
    && mv /usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-*/vendor/* /opt/codex \
    && /opt/codex/bin/codex --version

FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv
FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS app
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
ENV PATH="/app/.venv/bin:${PATH}" PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY harness/ harness/
CMD ["uvicorn", "harness.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM app AS worker
COPY --from=codex-cli /opt/codex /opt/codex
ENV PATH="/opt/codex/bin:/opt/codex/codex-path:${PATH}" CODEX_MANAGED_PACKAGE_ROOT=/opt/codex
ENV HOME=/home/worker CODEX_HOME=/home/worker/.codex
WORKDIR /workspace
USER 1000:1000
ENTRYPOINT ["python", "-m", "harness.worker"]
CMD ["codex"]
