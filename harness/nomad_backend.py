"""A single batch job on the host client's Docker driver, supervised through Nomad's API."""

import asyncio
import os
import time

import httpx

from harness.evidence import Run
from harness.launch import worker_env

TASK_NAME = "worker"


def batch_job(data: dict, token: str) -> dict:
    env, auth_file = worker_env(data["worker"], token)
    launch = data["launch"]
    task = {
        "Name": TASK_NAME,
        "Driver": "docker",
        "User": os.getenv("WORKER_UID", "1000"),
        "Env": env,
        "Resources": {"CPU": 200, "MemoryMB": 768},
        "Config": {
            "image": launch["image"],
            "args": [data["worker"]],
            "network_mode": launch["network"],
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
    if auth_file:
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
        "ID": launch["name"],
        "Name": launch["name"],
        "Type": "batch",
        "Datacenters": ["dc1"],
        "Meta": {"harness_run": data["run_id"]},
        "TaskGroups": [group],
    }


class NomadBackend:
    name = "nomad"

    def __init__(self, address: str):
        self.api = httpx.AsyncClient(base_url=address, timeout=15, trust_env=False)

    async def close(self):
        await self.api.aclose()

    async def ensure_registered(self, run: Run, token: str):
        # A dropped submit response may mean the server already created the job.
        # Each retry first looks up the deterministic ID and checks its owner.
        for attempt in range(3):
            try:
                await self.register(run, token)
                return
            except httpx.TransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

    async def register(self, run: Run, token: str):
        data = run.read()
        job_id = data["launch"]["name"]
        run.update(job_id=job_id)
        existing = await self.api.get(f"/v1/job/{job_id}")
        if existing.status_code != 404:
            job = existing.raise_for_status().json()
            if (job.get("Meta") or {}).get("harness_run") != data["run_id"]:
                raise RuntimeError("Nomad job ownership does not match the run")
            return
        if data.get("evaluation_id") or data.get("allocation_id"):
            raise RuntimeError("Recorded Nomad job is missing")
        response = await self.api.post(
            "/v1/jobs",
            json={"Job": batch_job(data, token), "EnforceIndex": True, "JobModifyIndex": 0},
        )
        run.update(evaluation_id=response.raise_for_status().json()["EvalID"])

    async def wait(self, run: Run, token: str, deadline: float) -> dict:
        await self.ensure_registered(run, token)
        data = run.read()
        job_id = data["job_id"]
        alloc_id = data.get("allocation_id")
        # Repeat stop after recovery if the harness restarted between journaling and the API call.
        stopping = False
        while True:
            if alloc_id is None:
                response = await self.api.get(f"/v1/job/{job_id}/allocations")
                allocs = response.raise_for_status().json()
                if allocs:
                    alloc_id = allocs[0]["ID"]
                    run.update(allocation_id=alloc_id, node_id=allocs[0]["NodeID"])
            if alloc_id:
                response = await self.api.get(f"/v1/allocation/{alloc_id}")
                alloc = response.raise_for_status().json()
                status = alloc["ClientStatus"]
                if status == "running" and data["status"] != "running":
                    data["status"] = "running"
                    run.update(status="running")
                if status in {"complete", "failed", "lost"}:
                    return self.terminal_state(run, alloc)
            if time.time() >= deadline and not stopping:
                run.update(timed_out=True)
                # Stop scheduling as well as running tasks; keep allocation logs for collection.
                (await self.api.delete(f"/v1/job/{job_id}")).raise_for_status()
                stopping = True
            if stopping and (alloc_id is None or time.time() >= deadline + 30):
                raise RuntimeError(f"Nomad job {job_id} timed out without a confirmed worker exit")
            await asyncio.sleep(0.5)

    @staticmethod
    def terminal_state(run: Run, alloc: dict) -> dict:
        task = (alloc.get("TaskStates") or {}).get(TASK_NAME) or {}
        events = task.get("Events") or []
        run.update(
            allocation_status=alloc["ClientStatus"],
            task_events=[
                {"type": e["Type"], "time": e["Time"], "message": e.get("DisplayMessage", "")}
                for e in events
            ],
        )
        exited = next((e for e in reversed(events) if e["Type"] == "Terminated"), None)
        if task.get("State") != "dead" or not exited or "ExitCode" not in exited:
            detail = events[-1].get("DisplayMessage") if events else alloc["ClientStatus"]
            raise RuntimeError(f"Nomad did not report a worker exit: {detail}")
        return {
            "ExitCode": exited["ExitCode"],
            "StartedAt": task["StartedAt"],
            "FinishedAt": task["FinishedAt"],
        }

    async def logs(self, data: dict, stream: str) -> bytes:
        response = await self.api.get(
            f"/v1/client/fs/logs/{data['allocation_id']}",
            params={"task": TASK_NAME, "type": stream, "plain": "true", "follow": "false"},
        )
        return response.raise_for_status().content

    async def cleanup(self, data: dict):
        # A restart may replay either operation after it succeeded but before run.json was updated.
        response = await self.api.get(f"/v1/client/allocation/{data['allocation_id']}/gc")
        if response.status_code != 404:
            response.raise_for_status()
        response = await self.api.delete(f"/v1/job/{data['job_id']}", params={"purge": "true"})
        if response.status_code != 404:
            response.raise_for_status()
