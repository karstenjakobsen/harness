"""Direct Docker execution for the original harness test."""

import asyncio
import os
import time

import docker
from docker.errors import NotFound
from docker.types import LogConfig, Mount

from harness.evidence import Run
from harness.launch import worker_env


class DockerBackend:
    name = "docker"

    def __init__(self):
        self.docker = docker.from_env(timeout=15)

    async def close(self):
        self.docker.close()

    def create_container(self, data: dict, token: str):
        worker = data["worker"]
        env, auth_file = worker_env(worker, token)
        mounts = (
            [Mount("/run/secrets/codex-auth", auth_file, type="bind", read_only=True)]
            if auth_file
            else []
        )
        uid = int(os.getenv("WORKER_UID", "1000"))
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

    async def wait(self, run: Run, token: str, deadline: float) -> dict:
        data = run.read()
        container = await asyncio.to_thread(self.locate, data)
        if container is None:
            if data.get("container_id"):
                raise RuntimeError("Recorded worker container is missing")
            container = await asyncio.to_thread(self.create_container, data, token)
        run.update(container_id=container.id, image_id=container.attrs["Image"])
        if container.status == "created":
            await asyncio.to_thread(container.start)
        run.update(status="running")
        while True:
            await asyncio.to_thread(container.reload)
            if container.status in {"exited", "dead"}:
                return container.attrs["State"]
            if time.time() >= deadline:
                run.update(timed_out=True)
                await asyncio.to_thread(container.kill)
            await asyncio.sleep(0.5)

    async def logs(self, data: dict, stream: str) -> bytes:
        container = await asyncio.to_thread(self.locate, data)
        return await asyncio.to_thread(
            container.logs, stdout=stream == "stdout", stderr=stream == "stderr"
        )

    async def cleanup(self, data: dict):
        container = await asyncio.to_thread(self.locate, data)
        if container is not None:
            await asyncio.to_thread(container.remove)
