"""Direct Docker execution for the original harness test."""

import asyncio
import time

import docker
from docker.errors import NotFound
from docker.types import LogConfig, Mount

from harness.launch import ExecutionRef, LaunchRequest, Progress, Report, WorkerExit


class DockerBackend:
    name = "docker"

    def __init__(self):
        self.docker = docker.from_env(timeout=15)

    async def close(self):
        self.docker.close()

    def create_container(self, request: LaunchRequest):
        auth_file = request.auth_file
        mounts = (
            [Mount("/run/secrets/codex-auth", auth_file, type="bind", read_only=True)]
            if auth_file
            else []
        )
        uid = request.uid
        return self.docker.containers.create(
            request.image,
            command=[request.worker],
            name=request.ref.name,
            network=request.network,
            labels={"harness.run": request.ref.run_id},
            environment=request.worker_env(),
            mounts=mounts,
            user=f"{uid}:{uid}",
            read_only=True,
            tmpfs={
                "/tmp": "rw,nosuid,nodev,mode=1777",
                "/home/worker": f"rw,nosuid,nodev,mode=0700,uid={uid},gid={uid}",
            },
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            init=True,
            pids_limit=160,
            mem_limit="768m",
            log_config=LogConfig(type="json-file"),
        )

    def locate(self, ref: ExecutionRef):
        try:
            container = self.docker.containers.get(ref.ids.get("container_id") or ref.name)
        except NotFound:
            return None
        if container.labels.get("harness.run") != ref.run_id:
            raise RuntimeError("Container ownership label does not match the run")
        return container

    async def wait(self, request: LaunchRequest, report: Report) -> WorkerExit:
        container = await asyncio.to_thread(self.locate, request.ref)
        if container is None:
            if request.ref.ids.get("container_id"):
                raise RuntimeError("Recorded worker container is missing")
            container = await asyncio.to_thread(self.create_container, request)
        report(
            Progress(details={"container_id": container.id, "image_id": container.attrs["Image"]})
        )
        if container.status == "created":
            await asyncio.to_thread(container.start)
        report(Progress(running=True))
        while True:
            await asyncio.to_thread(container.reload)
            if container.status in {"exited", "dead"}:
                state = container.attrs["State"]
                return WorkerExit(state["ExitCode"], state["StartedAt"], state["FinishedAt"])
            if time.time() >= request.deadline:
                report(Progress(timed_out=True))
                await asyncio.to_thread(container.kill)
            await asyncio.sleep(0.5)

    async def logs(self, ref: ExecutionRef, stream: str) -> bytes:
        container = await asyncio.to_thread(self.locate, ref)
        return await asyncio.to_thread(
            container.logs, stdout=stream == "stdout", stderr=stream == "stderr"
        )

    async def cleanup(self, ref: ExecutionRef):
        container = await asyncio.to_thread(self.locate, ref)
        if container is not None:
            await asyncio.to_thread(container.remove)
