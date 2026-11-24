"""Supervise one worker and retain its evidence before backend cleanup."""

import asyncio
import hmac
import logging
import os
from datetime import datetime
from pathlib import Path

from harness.docker_backend import DockerBackend
from harness.evidence import ACTIVE, Run, Worker
from harness.nomad_backend import NomadBackend

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, root: Path, operator_key: str):
        self.root = root
        self.key = operator_key
        self.image = os.environ["WORKER_IMAGE"]
        self.network = os.environ["WORKER_NETWORK"]
        address = os.getenv("NOMAD_ADDR")
        self.backend = NomadBackend(address) if address else DockerBackend()
        self.active: dict[str, Run] = {}
        self.jobs: set[asyncio.Task] = set()

    def submit(self, worker: Worker) -> str:
        run = Run.create(self.root, worker, self.image, self.network, self.backend.name)
        self.watch(run)
        return run.path.name

    def watch(self, run: Run):
        token = hmac.digest(self.key.encode(), run.path.name.encode(), "sha256").hex()
        if run.read()["status"] in ACTIVE:
            self.active[token] = run
        job = asyncio.create_task(self.execute(run, token))
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)

    def recover(self):
        for record in self.root.glob("*/run.json"):
            run = Run(self.root, record.parent.name)
            data = run.read()
            if data.get("backend", "docker") != self.backend.name:
                continue
            if data["status"] in ACTIVE or data.get("cleanup") == "pending":
                self.watch(run)

    async def execute(self, run: Run, token: str):
        data = run.read()
        terminal = data["status"] not in ACTIVE
        try:
            if not terminal:
                deadline = datetime.fromisoformat(data["created_at"]).timestamp() + 240
                state = await self.backend.wait(run, token, deadline)
                self.active.pop(token, None)
                data = run.read()
                for stream, filename in [("stdout", "stdout.jsonl"), ("stderr", "stderr.log")]:
                    (run.path / filename).write_bytes(await self.backend.logs(data, stream))
                run.finish(state, data.get("timed_out", False))
                terminal = True
            await self.backend.cleanup(run.read())
            run.update(cleanup="removed")
        except Exception as exc:
            log.exception("%s lifecycle failed for run %s", self.backend.name, run.path.name)
            if terminal:
                run.update(cleanup="pending", cleanup_error=str(exc))
            else:
                run.update(
                    status="harness failed",
                    error=str(exc),
                    summary=f"{run.path.name} | harness failed | {type(exc).__name__}",
                )
        finally:
            self.active.pop(token, None)
