"""Submit a fixed Docker container and collect the evidence before removing it."""

import asyncio
import hmac
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import docker
from docker.errors import NotFound
from docker.types import LogConfig, Mount

from harness.evidence import ACTIVE, Run, Worker

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, root: Path, operator_key: str):
        self.root = root
        self.key = operator_key
        self.image = os.environ["WORKER_IMAGE"]
        self.network = os.environ["WORKER_NETWORK"]
        self.docker = docker.from_env(timeout=15)
        self.active: dict[str, Run] = {}
        self.jobs: set[asyncio.Task] = set()

    def submit(self, worker: Worker) -> str:
        run = Run.create(self.root, worker, self.image, self.network)
        self.watch(run)
        return run.path.name

    def watch(self, run: Run):
        token = hmac.digest(self.key.encode(), run.path.name.encode(), "sha256").hex()
        self.active[token] = run
        job = asyncio.create_task(self.execute(run, token))
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)

    def recover(self):
        for record in self.root.glob("*/run.json"):
            run = Run(self.root, record.parent.name)
            data = run.read()
            if data["status"] in ACTIVE or data.get("cleanup") == "pending":
                self.watch(run)

    def create_container(self, data: dict, token: str):
        worker = data["worker"]
        env = {"RUN_TOKEN": token, "WORKER_MCP_URL": "http://harness:8000/worker/mcp"}
        mounts = []
        uid = int(os.getenv("WORKER_UID", "1000"))
        if worker == "codex":
            auth_file = os.getenv("CODEX_AUTH_FILE")
            if auth_file:
                mounts.append(
                    Mount("/run/secrets/codex-auth", auth_file, type="bind", read_only=True)
                )
            elif key := os.getenv("CODEX_API_KEY"):
                env["CODEX_API_KEY"] = key
            else:
                raise ValueError("Set CODEX_AUTH_FILE or CODEX_API_KEY for the Codex worker")
        launch = data["launch"]
        return self.docker.containers.create(
            launch["image"],
            command=[worker],
            name=launch["name"],
            network=launch["network"],
            labels={"harness.run": data["run_id"]},
            environment=env,
            mounts=mounts,
            user=f"{uid}:{uid}",
            read_only=True,
            tmpfs={"/tmp": "rw,nosuid,nodev,mode=1777"},
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            init=True,
            pids_limit=160,
            mem_limit="768m",
            log_config=LogConfig(type="json-file"),
        )

    def locate(self, data: dict):
        try:
            container = self.docker.containers.get(
                data.get("container_id") or data["launch"]["name"]
            )
        except NotFound:
            return None
        if container.labels.get("harness.run") != data["run_id"]:
            raise RuntimeError("Container ownership label does not match the run")
        return container

    async def execute(self, run: Run, token: str):
        data = run.read()
        terminal = data["status"] not in ACTIVE
        try:
            container = await asyncio.to_thread(self.locate, data)
            if not terminal:
                if container is None:
                    if data.get("container_id"):
                        raise RuntimeError("Recorded worker container is missing")
                    container = await asyncio.to_thread(self.create_container, data, token)
                run.update(container_id=container.id, image_id=container.attrs["Image"])
                if container.status == "created":
                    await asyncio.to_thread(container.start)
                run.update(status="running")
                deadline = datetime.fromisoformat(data["created_at"]).timestamp() + 240
                timed_out = data.get("timed_out", False)
                while True:
                    await asyncio.to_thread(container.reload)
                    if container.status in {"exited", "dead"}:
                        break
                    if datetime.now(UTC).timestamp() >= deadline:
                        timed_out = True
                        run.update(timed_out=True)
                        await asyncio.to_thread(container.kill)
                    else:
                        await asyncio.sleep(0.5)
                self.active.pop(token, None)
                for filename, stdout in [("stdout.jsonl", True), ("stderr.log", False)]:
                    raw = await asyncio.to_thread(container.logs, stdout=stdout, stderr=not stdout)
                    (run.path / filename).write_bytes(raw)
                run.finish(container.attrs["State"], timed_out)
                terminal = True
            if container is not None:
                await asyncio.to_thread(container.remove)
            run.update(cleanup="removed")
        except Exception as exc:
            log.exception("Docker lifecycle failed for run %s", run.path.name)
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
