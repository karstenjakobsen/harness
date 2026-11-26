FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
RUN npm install --global @openai/codex@0.166.0 && test "$(codex --version)" = 'codex-cli 0.166.0'
ENV HOME=/worker CODEX_HOME=/worker/.codex
RUN mkdir -p /worker/.codex /worker/task
WORKDIR /worker/task
COPY --chmod=755 harness-worker /usr/local/bin/harness-worker
COPY worker-mcp.mjs /usr/local/lib/worker-mcp.mjs
ENTRYPOINT ["/usr/local/bin/harness-worker"]
