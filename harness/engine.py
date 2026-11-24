"""Supervise one worker and retain its evidence before backend cleanup."""

import asyncio
import base64
import hmac
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from harness.docker_backend import DockerBackend
from harness.evidence import ACTIVE, Run, Workspace, execution_ref
from harness.launch import ExecutionBackend, LaunchRequest, Worker
from harness.nomad_backend import NomadBackend
from harness.tasks import TaskInput, legacy_statuses, recorded_task, resolve_task

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, root: Path, operator_key: str):
        self.root = root
        self.key = operator_key
        self.image = os.environ["WORKER_IMAGE"]
        self.network = os.environ["WORKER_NETWORK"]
        address = os.getenv("NOMAD_ADDR")
        self.backend: ExecutionBackend = NomadBackend(address) if address else DockerBackend()
        self.active: dict[str, Workspace] = {}
        self.jobs: set[asyncio.Task] = set()

    def submit(self, task: TaskInput, worker: Worker) -> str:
        plan = resolve_task(task)
        run = Run.create(
            self.root,
            worker,
            self.image,
            self.network,
            self.backend.name,
            prompt=plan.prompt,
            outcome=plan.model_dump(),
        )
        self.watch(run)
        return run.path.name

    def get_run(self, run_id: str, trace: bool) -> dict:
        run = Run(self.root, run_id)
        if not run.record.exists():
            raise ValueError("Unknown run ID")
        data = run.read(trace)
        if "execution_status" not in data:
            data.update(legacy_statuses(data))
        return data

    def watch(self, run: Run):
        token = hmac.digest(self.key.encode(), run.path.name.encode(), "sha256").hex()
        data = run.read()
        if data["status"] in ACTIVE and "exit_code" not in data:
            self.active[token] = Workspace(run.workspace, run.calls, recorded_task(data).files)
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

    def launch_request(self, data: dict, token: str) -> LaunchRequest:
        task = {"prompt": data["task"], "outcome": recorded_task(data).model_dump()}
        env = {
            "RUN_TOKEN": token,
            # Preserve literal Nomad variable expressions in the worker's task.
            "RUN_TASK_B64": base64.b64encode(json.dumps(task).encode()).decode("ascii"),
            "WORKER_MCP_URL": "http://harness:8000/worker/mcp",
        }
        auth_file = None
        if data["worker"] == "codex":
            auth_file = os.getenv("CODEX_AUTH_FILE")
            if not auth_file and (key := os.getenv("CODEX_API_KEY")):
                env["CODEX_API_KEY"] = key
        return LaunchRequest(
            ref=execution_ref(data),
            image=data["launch"]["image"],
            network=data["launch"]["network"],
            worker=data["worker"],
            uid=int(os.getenv("WORKER_UID", "1000")),
            deadline=datetime.fromisoformat(data["created_at"]).timestamp() + 240,
            env=env,
            auth_file=auth_file,
        )

    async def execute(self, run: Run, token: str):
        data = run.read()
        terminal = data["status"] not in ACTIVE
        verifying = False
        try:
            if not terminal:
                if "exit_code" not in data:
                    exit_info = await self.backend.wait(
                        self.launch_request(data, token), run.progress
                    )
                    self.active.pop(token, None)
                    run.exited(exit_info)
                data = run.read()
                ref = execution_ref(data)
                for stream, filename in [("stdout", "stdout.jsonl"), ("stderr", "stderr.log")]:
                    (run.path / filename).write_bytes(await self.backend.logs(ref, stream))
                verifying = True
                plan = recorded_task(data)
                run.finish(plan.verify(run.workspace, run.tool_calls()))
                terminal = True
            await self.backend.cleanup(execution_ref(run.read()))
            run.update(cleanup="removed")
        except Exception as exc:
            log.exception("%s lifecycle failed for run %s", self.backend.name, run.path.name)
            if terminal:
                run.update(cleanup="pending", cleanup_error=str(exc))
            else:
                data = run.read()
                execution = data.get("execution_status", "unknown")
                if execution in ACTIVE:
                    execution = "timed out" if data.get("timed_out") else "unknown"
                run.update(
                    status="harness failed",
                    execution_status=execution,
                    verification_status="error" if verifying else "not run",
                    error=str(exc),
                    summary=f"{run.path.name} | harness failed | {type(exc).__name__}",
                )
        finally:
            self.active.pop(token, None)
