FROM ghcr.io/icoretech/codex-docker:0.166.0@sha256:c0568397f66fb8cc22c541fbafe26948da5000d24770b0ac2e918517dfc02615

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY dev/worker/worker_runtime.py /usr/local/bin/worker_runtime.py
COPY --chmod=0755 dev/worker/codex_worker.py /usr/local/bin/harness-worker
USER codex
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/harness-worker"]
