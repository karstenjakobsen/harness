"""A single batch job on the host client's Docker driver, supervised through Nomad's API."""

import asyncio
import time

import httpx

from harness.launch import ExecutionRef, LaunchRequest, Progress, Report, WorkerExit

TASK_NAME = "worker"


def batch_job(request: LaunchRequest) -> dict:
    task = {
        "Name": TASK_NAME,
        "Driver": "docker",
        "User": str(request.uid),
        "Env": request.worker_env(),
        "Resources": {"CPU": 200, "MemoryMB": 768},
        "Config": {
            "image": request.image,
            "args": [request.worker],
            "network_mode": request.network,
            "readonly_rootfs": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "pids_limit": 160,
            "mount": [{"type": "tmpfs", "target": path} for path in ["/tmp", "/home/worker"]],
        },
    }
    group = {
        "Name": TASK_NAME,
        "Count": 1,
        "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
        "ReschedulePolicy": {"Attempts": 0, "Unlimited": False},
        "Tasks": [task],
    }
    if request.auth_file:
        # The host client maps this fixed, read-only volume to its local sign-in file.
        group["Volumes"] = {
            "auth": {
                "Name": "auth",
                "Type": "host",
                "Source": "harness-codex-auth",
                "ReadOnly": True,
            }
        }
        task["VolumeMounts"] = [
            {"Volume": "auth", "Destination": "/run/secrets/codex-auth", "ReadOnly": True}
        ]
    return {
        "ID": request.ref.name,
        "Name": request.ref.name,
        "Type": "batch",
        "Datacenters": ["dc1"],
        "Meta": {"harness_run": request.ref.run_id},
        "TaskGroups": [group],
    }


class NomadBackend:
    name = "nomad"

    def __init__(self, address: str):
        self.api = httpx.AsyncClient(base_url=address, timeout=15, trust_env=False)

    async def close(self):
        await self.api.aclose()

    async def ensure_registered(self, request: LaunchRequest, report: Report):
        # A dropped submit response may mean the server already created the job.
        # Each retry first looks up the deterministic ID and checks its owner.
        for attempt in range(3):
            try:
                await self.register(request, report)
                return
            except httpx.TransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

    async def register(self, request: LaunchRequest, report: Report):
        job_id = request.ref.name
        report(Progress(details={"job_id": job_id}))
        existing = await self.api.get(f"/v1/job/{job_id}")
        if existing.status_code != 404:
            job = existing.raise_for_status().json()
            if (job.get("Meta") or {}).get("harness_run") != request.ref.run_id:
                raise RuntimeError("Nomad job ownership does not match the run")
            return
        if request.ref.ids.get("evaluation_id") or request.ref.ids.get("allocation_id"):
            raise RuntimeError("Recorded Nomad job is missing")
        response = await self.api.post(
            "/v1/jobs",
            json={"Job": batch_job(request), "EnforceIndex": True, "JobModifyIndex": 0},
        )
        report(Progress(details={"evaluation_id": response.raise_for_status().json()["EvalID"]}))

    async def wait(self, request: LaunchRequest, report: Report) -> WorkerExit:
        await self.ensure_registered(request, report)
        job_id = request.ref.name
        alloc_id = request.ref.ids.get("allocation_id")
        running = False
        # Repeat stop after recovery if the harness restarted between journaling and the API call.
        stopping = False
        while True:
            if alloc_id is None:
                response = await self.api.get(f"/v1/job/{job_id}/allocations")
                allocs = response.raise_for_status().json()
                if allocs:
                    alloc_id = allocs[0]["ID"]
                    report(
                        Progress(
                            details={"allocation_id": alloc_id, "node_id": allocs[0]["NodeID"]}
                        )
                    )
            if alloc_id:
                response = await self.api.get(f"/v1/allocation/{alloc_id}")
                alloc = response.raise_for_status().json()
                status = alloc["ClientStatus"]
                if status == "running" and not running:
                    running = True
                    report(Progress(running=True))
                if status in {"complete", "failed", "lost"}:
                    return self.terminal_state(alloc, report)
            if time.time() >= request.deadline and not stopping:
                report(Progress(timed_out=True))
                # Stop scheduling as well as running tasks; keep allocation logs for collection.
                (await self.api.delete(f"/v1/job/{job_id}")).raise_for_status()
                stopping = True
            if stopping and (alloc_id is None or time.time() >= request.deadline + 30):
                raise RuntimeError(f"Nomad job {job_id} timed out without a confirmed worker exit")
            await asyncio.sleep(0.5)

    @staticmethod
    def terminal_state(alloc: dict, report: Report) -> WorkerExit:
        task = (alloc.get("TaskStates") or {}).get(TASK_NAME) or {}
        events = task.get("Events") or []
        report(
            Progress(
                details={
                    "allocation_status": alloc["ClientStatus"],
                    "task_events": [
                        {
                            "type": e["Type"],
                            "time": e["Time"],
                            "message": e.get("DisplayMessage", ""),
                        }
                        for e in events
                    ],
                }
            )
        )
        exited = next((e for e in reversed(events) if e["Type"] == "Terminated"), None)
        if task.get("State") != "dead" or not exited or "ExitCode" not in exited:
            detail = events[-1].get("DisplayMessage") if events else alloc["ClientStatus"]
            raise RuntimeError(f"Nomad did not report a worker exit: {detail}")
        return WorkerExit(exited["ExitCode"], task["StartedAt"], task["FinishedAt"])

    async def logs(self, ref: ExecutionRef, stream: str) -> bytes:
        response = await self.api.get(
            f"/v1/client/fs/logs/{ref.ids['allocation_id']}",
            params={"task": TASK_NAME, "type": stream, "plain": "true", "follow": "false"},
        )
        return response.raise_for_status().content

    async def cleanup(self, ref: ExecutionRef):
        # A restart may replay either operation after it succeeded but before run.json was updated.
        response = await self.api.get(f"/v1/client/allocation/{ref.ids['allocation_id']}/gc")
        if response.status_code != 404:
            response.raise_for_status()
        response = await self.api.delete(f"/v1/job/{ref.ids['job_id']}", params={"purge": "true"})
        if response.status_code != 404:
            response.raise_for_status()
