"""Trusted, local Docker launcher for an immutable worker attempt."""

import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from harness_api import WorkAPI, WorkConflictError
from harness_mcp.worker import create_worker_app


class WorkerLaunchError(RuntimeError):
    pass


class WorkerTimeoutError(WorkerLaunchError):
    pass


class _WorkerServer:
    def __init__(self, api, port=0):
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", port))
        self.listener.listen(128)
        self.port = self.listener.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(create_worker_app(api), log_level="warning")
        )
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.listener]}, daemon=True
        )

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                self.__exit__(None, None, None)
                raise WorkerLaunchError("Worker MCP could not start.")
            time.sleep(0.01)
        return self

    def __exit__(self, *_):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.listener.close()


def _run_docker(*arguments, timeout=30, **kwargs):
    try:
        return subprocess.run(
            ["docker", *map(str, arguments)],
            timeout=timeout,
            check=False,
            **kwargs,
        )
    except subprocess.TimeoutExpired as error:
        raise WorkerTimeoutError("Docker operation timed out.") from error


def _docker(*arguments, timeout=30, **kwargs):
    result = _run_docker(
        *arguments, timeout=timeout, capture_output=True, text=True, **kwargs
    )
    if result.returncode:
        raise WorkerLaunchError(
            f"Docker operation failed: {result.stderr.strip()[:500]}"
        )
    return result.stdout.strip()


def _inspect_container(name):
    result = _run_docker(
        "inspect",
        "--type",
        "container",
        name,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if "No such" in result.stderr:
            return None
        raise WorkerLaunchError("Docker container inspection failed.")
    return json.loads(result.stdout)[0]


def _git(*arguments, environment):
    try:
        subprocess.run(
            ["git", *map(str, arguments)],
            check=True,
            capture_output=True,
            timeout=30,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise WorkerLaunchError("Git workspace preparation timed out.") from error
    except subprocess.CalledProcessError as error:
        raise WorkerLaunchError("Git workspace preparation failed.") from error


def _save_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream)
    temporary.replace(path)


def _auth_source():
    directory = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = directory / "auth.json"
    if not path.is_file():
        raise WorkerLaunchError("Sign in with Codex before starting a worker.")
    return path


class DockerEngine:
    """The external Docker command boundary; no workspace authority lives here."""

    def image_id(self, reference):
        return _docker("image", "inspect", "--format", "{{.Id}}", reference)

    def inspect(self, name):
        return _inspect_container(name)

    def create(self, arguments, environment):
        return _docker(*arguments, env=environment)

    def start(self, container_id):
        return _docker("start", container_id)

    def wait(self, container_id, timeout):
        return int(_docker("wait", container_id, timeout=timeout))

    def stop(self, container_id):
        _docker("stop", "--time", "5", container_id)

    def write_logs(self, container_id, stdout, stderr):
        result = _run_docker(
            "logs",
            container_id,
            stdout=stdout,
            stderr=stderr,
        )
        if result.returncode:
            raise WorkerLaunchError("Docker logs could not be retrieved.")


class DockerWorkerLauncher:
    """Serialize launch and reconcile Docker before ever creating another process."""

    def __init__(self, api: WorkAPI, *, engine=None, auth_path=None):
        self.api = api
        self.engine = engine if engine is not None else DockerEngine()
        self.auth_path = Path(auth_path) if auth_path is not None else None
        database_path = api.database_path.resolve()
        self.namespace = hashlib.sha256(str(database_path).encode()).hexdigest()
        self.root = database_path.parent / "worker-attempts" / self.namespace

    def directory(self, attempt_id):
        # Validate before using an identifier as a path component.
        self.api.get_attempt(attempt_id)
        return self.root / attempt_id

    @contextmanager
    def _locked(self, attempt_id):
        directory = self.directory(attempt_id)
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        with (directory / "launch.lock").open("a") as lock:
            os.chmod(directory / "launch.lock", 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory

    def show(self, attempt_id):
        attempt = self.api.get_attempt(attempt_id)
        return {
            "attempt": attempt,
            "work_item": self.api.get_work_item(attempt["work_item_id"]),
            "calls": self.api.list_worker_calls(attempt_id),
            "artifact": (
                self.api.get_artifact(attempt["artifact_id"])
                if attempt["artifact_id"] is not None
                else None
            ),
            "trace_path": str(self.directory(attempt_id) / "codex.jsonl"),
        }

    def _prepare(self, attempt, item, directory):
        scratch = directory / "scratch"
        if attempt["scratch_cleaned_at"] is not None:
            raise WorkerLaunchError("A cleaned attempt cannot be launched again.")
        if attempt["scratch_path"] is None:
            if scratch.exists():
                shutil.rmtree(scratch)
            if item["source_path"] is None:
                scratch.mkdir(mode=0o700)
            else:
                # Hooks and worktree callers can export repository selectors.
                # The recorded source and scratch arguments must select Git's
                # repository, index and object storage for every preparation call.
                git_environment = {
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("GIT_")
                }
                # No shared objects, credentials, or writable original checkout.
                _git(
                    "--no-replace-objects",
                    "-C",
                    item["source_path"],
                    "cat-file",
                    "-e",
                    f"{item['base_sha']}^{{commit}}",
                    environment=git_environment,
                )
                _git(
                    "clone",
                    "--no-hardlinks",
                    "--dissociate",
                    "--no-checkout",
                    "--",
                    item["source_path"],
                    scratch,
                    environment=git_environment,
                )
                _git(
                    "--no-replace-objects",
                    "-C",
                    scratch,
                    "checkout",
                    "--detach",
                    item["base_sha"],
                    environment=git_environment,
                )
                _git(
                    "-C",
                    scratch,
                    "remote",
                    "remove",
                    "origin",
                    environment=git_environment,
                )
            self.api.set_scratch(attempt["id"], scratch)
        elif Path(attempt["scratch_path"]) != scratch or not scratch.is_dir():
            raise WorkerLaunchError("The recorded scratch workspace is unavailable.")
        uid, gid = os.getuid() or 1000, os.getgid() or 1000
        if os.getuid() == 0:
            for path in [scratch, *scratch.rglob("*")]:
                os.chown(path, uid, gid, follow_symlinks=False)
        return scratch, uid, gid

    def _prepare_auth(self, directory, uid, gid):
        auth = directory / "codex-home"
        auth.mkdir(mode=0o700, exist_ok=True)
        login_file = auth / "auth.json"
        if not login_file.is_file():
            shutil.copyfile(self.auth_path or _auth_source(), login_file)
            os.chmod(login_file, 0o600)
        if os.getuid() == 0:
            for path in [auth, *auth.rglob("*")]:
                os.chown(path, uid, gid, follow_symlinks=False)
        return auth

    def _cleanup(self, attempt, directory):
        scratch = directory / "scratch"
        if attempt["scratch_path"] is not None:
            if Path(attempt["scratch_path"]) != scratch:
                raise WorkerLaunchError("Refusing cleanup of an unexpected workspace.")
            if scratch.exists():
                shutil.rmtree(scratch)
            if attempt["scratch_cleaned_at"] is None:
                self.api.mark_scratch_cleaned(attempt["id"])
        auth = directory / "codex-home"
        if auth.exists():
            shutil.rmtree(auth)

    def start(self, work_item_id, attempt_id, image, *, timeout=600):
        if not re.fullmatch(r"(?:[^@\s]+@)?sha256:[a-f0-9]{64}", image):
            raise WorkerLaunchError("Select an immutable worker image digest.")
        attempt = self.api.create_attempt(attempt_id, work_item_id)
        with self._locked(attempt_id) as directory:
            # Another launcher may have finished while this one waited.
            attempt = self.api.get_attempt(attempt_id)
            item = self.api.get_work_item(work_item_id)
            manifest_path = directory / "launch.json"
            manifest = (
                json.loads(manifest_path.read_text())
                if manifest_path.exists()
                else None
            )
            if manifest and manifest["image_reference"] != image:
                raise WorkConflictError(
                    "This attempt already selected a different image."
                )
            if attempt["exit_code"] is not None:
                self._cleanup(attempt, directory)
                return self.show(attempt_id)
            if attempt["scratch_cleaned_at"] is not None:
                raise WorkerLaunchError("This attempt was already cleaned.")
            image_id = manifest["image_id"] if manifest else self.engine.image_id(image)
            credential_path = directory / "credential"
            if not credential_path.exists():
                if attempt["grant_id"] is not None:
                    raise WorkerLaunchError(
                        "The original attempt credential is unavailable."
                    )
                descriptor = os.open(
                    credential_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "w") as credential_file:
                    credential_file.write(secrets.token_urlsafe(32))
            credential = credential_path.read_text()
            if attempt["grant_id"] is None:
                self.api.grant_attempt(attempt_id, credential)
            else:
                self.api.authorize_attempt(attempt_id, credential)
            scratch, uid, gid = self._prepare(attempt, item, directory)
            identity = hashlib.sha256(attempt_id.encode()).hexdigest()[:20]
            name = f"harness-worker-{self.namespace[:12]}-{identity}"
            labels = {
                "io.harness.workspace": self.namespace,
                "io.harness.attempt": attempt_id,
                "io.harness.work-item": str(work_item_id),
            }
            with _WorkerServer(self.api, manifest["port"] if manifest else 0) as server:
                if manifest is None:
                    manifest = {
                        "image_reference": image,
                        "image_id": image_id,
                        "port": server.port,
                        "container_name": name,
                    }
                    _save_json(manifest_path, manifest)
                container = self.engine.inspect(name)
                if container is None:
                    if attempt["container_id"] is not None:
                        raise WorkerLaunchError(
                            "The original container is missing; refusing a replacement."
                        )
                    auth = self._prepare_auth(directory, uid, gid)
                    environment = os.environ.copy()
                    environment.update(
                        CODEX_HOME="/harness-codex-home",
                        HARNESS_WORKER_TOKEN=credential,
                        HARNESS_WORKER_MCP_URL=f"http://127.0.0.1:{server.port}/mcp",
                        HARNESS_WORKER_ATTEMPT_ID=attempt_id,
                    )
                    arguments = [
                        "create",
                        "--name",
                        name,
                        "--restart",
                        "no",
                        "--network",
                        "host",
                        "--user",
                        f"{uid}:{gid}",
                        "--mount",
                        f"type=bind,src={scratch},dst=/workspace",
                        "--mount",
                        f"type=bind,src={auth},dst=/harness-codex-home",
                    ]
                    for key, value in labels.items():
                        arguments += ["--label", f"{key}={value}"]
                    for key in (
                        "CODEX_HOME",
                        "HARNESS_WORKER_TOKEN",
                        "HARNESS_WORKER_MCP_URL",
                        "HARNESS_WORKER_ATTEMPT_ID",
                    ):
                        arguments += ["--env", key]
                    self.engine.create(
                        [*arguments, image_id, "run", "--attempt-id", attempt_id],
                        environment,
                    )
                    container = self.engine.inspect(name)
                if (
                    container is None
                    or container["Image"] != image_id
                    or any(
                        container["Config"]["Labels"].get(k) != v
                        for k, v in labels.items()
                    )
                    or container["HostConfig"]["RestartPolicy"]["Name"] != "no"
                ):
                    raise WorkConflictError(
                        "The existing Docker container does not match this attempt."
                    )
                self.api.record_launch(attempt_id, container["Id"], image_id)
                if container["State"]["Status"] == "created":
                    self._prepare_auth(directory, uid, gid)
                    try:
                        self.engine.start(container["Id"])
                    except WorkerLaunchError:
                        observed = self.engine.inspect(name)
                        if observed is None or observed["State"]["Status"] == "created":
                            raise
                try:
                    exit_code = self.engine.wait(container["Id"], timeout)
                except WorkerTimeoutError:
                    self.engine.stop(container["Id"])
                    exit_code = self.engine.wait(container["Id"], 30)
                with (
                    (directory / "codex.jsonl").open("w") as stdout,
                    (directory / "codex.stderr.log").open("w") as stderr,
                ):
                    os.chmod(directory / "codex.jsonl", 0o600)
                    os.chmod(directory / "codex.stderr.log", 0o600)
                    self.engine.write_logs(container["Id"], stdout, stderr)
                self.api.record_exit(attempt_id, exit_code)
                self._cleanup(self.api.get_attempt(attempt_id), directory)
            return self.show(attempt_id)
