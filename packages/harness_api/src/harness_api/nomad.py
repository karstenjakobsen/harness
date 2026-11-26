"""Execute one Docker batch task on a caller-selected Nomad cluster."""

import hashlib
import json
import os
import re
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .execution import WORKER_EXECUTABLE, ExecutionState, WorkloadSpec, WorkloadStatus


def _allocation_guard(*, use_guard_volume: bool) -> dict:
    """Check Nomad's placement records before the workload is allowed to start."""
    script = "set -eu\nexport NOMAD_ADDR=unix:///secrets/api.sock\n"
    if use_guard_volume:
        script += 'export NOMAD_TOKEN="$(cat /secrets/guard-acl)"\n'
    script += """\
original=$(nomad alloc status -t '{{if not (or .PreviousAllocation .NextAllocation)}}{{.ID}}{{end}}' "$NOMAD_ALLOC_ID")
placements=$(nomad job allocs -t '{{range .}}{{println .ID}}{{end}}' "$NOMAD_JOB_ID")
if [ "$original" != "$NOMAD_ALLOC_ID" ] || [ "$placements" != "$NOMAD_ALLOC_ID" ]; then
    echo "Refusing to launch the workload in a replacement or ambiguous allocation." >&2
    exit 1
fi
"""
    guard = {
        "Name": "guard",
        "Driver": "docker",
        "Lifecycle": {"Hook": "prestart", "Sidecar": False},
        "Config": {
            "image": "hashicorp/nomad@sha256:1a9a0a9ab149a6dd05fd5219e11273a20507a108ab191db26360f0843359ddf7",
            "entrypoint": ["sh"],
            "args": ["-c", script],
        },
    }
    if use_guard_volume:
        guard["VolumeMounts"] = [
            {
                "Volume": "guard-acl",
                "Destination": "/secrets/guard-acl",
                "ReadOnly": True,
            }
        ]
    else:
        guard["Identity"] = {"Env": True}
    return guard


class WorkloadConflictError(ValueError):
    """A retained job already uses this run ID with another specification."""


class StartOutcomeUnknown(RuntimeError):
    """Registration may have committed. Retry with the original ID and spec."""


class NomadBackend:
    def __init__(self, address: str, *, timeout: float = 5):
        self.address = address.rstrip("/")
        url = urlsplit(self.address)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.query
            or url.fragment
        ):
            raise ValueError("Supply the HTTP API address of a running Nomad cluster.")
        self.timeout = timeout
        token_file = os.environ.get("HARNESS_NOMAD_TOKEN_FILE")
        self._token = Path(token_file).read_text().strip() if token_file else None

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(
            f"{self.address}/v1/{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        if self._token:
            request.add_unredirected_header("X-Nomad-Token", self._token)
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    @staticmethod
    def _job_path(handle: str) -> str:
        if not re.fullmatch(r"harness-[0-9a-f]{64}", handle):
            raise ValueError("Invalid Nomad workload handle.")
        return f"job/{handle}"

    @staticmethod
    def handle(run_id: str) -> str:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Supply a nonempty execution run ID.")
        return "harness-" + hashlib.sha256(run_id.encode()).hexdigest()

    def _metadata(self, run_id, spec):
        return {
            "harness_run_id": run_id,
            "harness_spec_sha256": hashlib.sha256(
                json.dumps([spec.image, spec.argv]).encode()
            ).hexdigest(),
            "harness_execution_version": "3" if self._token else "2",
        }

    def _configure_job(self, job):
        """Ordinary workloads receive the image and argument vector only."""

    def start(self, run_id: str, spec: WorkloadSpec) -> str:
        handle = self.handle(run_id)
        meta = self._metadata(run_id, spec)
        # The Docker driver's config is decoded as HCL templates even in JSON jobs.
        argv = [arg.replace("${", "$${").replace("%{", "%%{") for arg in spec.argv]
        job: dict[str, Any] = {
            "ID": handle,
            "Name": handle,
            "Type": "batch",
            "Datacenters": ["*"],
            "Meta": meta,
            "TaskGroups": [
                {
                    "Name": "workload",
                    "Count": 1,
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "ReschedulePolicy": {"Attempts": 0, "Unlimited": False},
                    "Disconnect": {
                        "Replace": False,
                        "LostAfter": 3_600_000_000_000,  # one hour, in nanoseconds
                        "Reconcile": "keep_original",
                    },
                    "Tasks": [
                        _allocation_guard(use_guard_volume=bool(self._token)),
                        {
                            "Name": "workload",
                            "Driver": "docker",
                            "Config": {
                                "image": spec.image,
                                "entrypoint": argv[:1],
                                "args": argv[1:],
                            },
                        },
                    ],
                }
            ],
        }
        groups: list[dict[str, Any]] = job["TaskGroups"]
        if self._token:
            groups[0]["Volumes"] = {
                "guard-acl": {
                    "Name": "guard-acl",
                    "Type": "host",
                    "Source": "harness-guard",
                    "ReadOnly": True,
                }
            }
        self._configure_job(job)
        try:
            self._request(
                "POST", "jobs", {"Job": job, "EnforceIndex": True, "JobModifyIndex": 0}
            )
            return handle
        except HTTPError as error:
            # Nomad reports a failed create-only check as an HTTP error.
            with error:
                detail = error.read().decode(errors="replace")
            if (
                error.code < 500
                and error.code != 409
                and "job already exists" not in detail
            ):
                raise RuntimeError(
                    f"Nomad rejected registration ({error.code}): {detail}"
                ) from error
            cause = f"HTTP {error.code}: {detail}"
        except (OSError, HTTPException, ValueError) as error:
            cause = str(error)

        try:
            existing = self._request("GET", self._job_path(handle))
        except (OSError, HTTPException, ValueError) as error:
            raise StartOutcomeUnknown(
                f"Could not confirm registration of {handle} at {self.address} ({cause}). "
                "Retry with the same run ID and spec."
            ) from error
        if existing.get("Meta") != meta:
            raise WorkloadConflictError(
                f"Job {handle} already exists with different metadata."
            )
        return handle

    def inspect(self, handle: str) -> WorkloadStatus:
        path = self._job_path(handle)
        job = self._request("GET", path)
        return self._inspect_allocations(handle, path, job)

    def lookup(self, run_id: str, spec: WorkloadSpec) -> WorkloadStatus:
        """Inspect a retained registration without submitting or recreating a job."""
        handle = self.handle(run_id)
        path = self._job_path(handle)
        try:
            job = self._request("GET", path)
            if job.get("Meta") != self._metadata(run_id, spec):
                raise WorkloadConflictError(
                    "The retained job does not match the saved attempt."
                )
            return self._inspect_allocations(handle, path, job)
        except (OSError, HTTPException) as error:
            raise StartOutcomeUnknown(
                "The retained Nomad job or allocations could not be read."
            ) from error

    def _inspect_allocations(self, handle, path, job):
        # The default includes replacements and excludes older, purged job instances.
        allocations = self._request("GET", f"{path}/allocations") or []
        state: ExecutionState
        if not allocations:
            state = "stopped" if job["Stop"] else "pending"
            if job.get("Status") == "dead" and not job["Stop"]:
                state = "unknown"
            return WorkloadStatus(state, handle)
        ordered = sorted(allocations, key=lambda a: (a["CreateIndex"], a["ID"]))
        alloc = self._request("GET", f"allocation/{ordered[0]['ID']}")
        replacements = [a["ID"] for a in ordered[1:]]
        original_id = alloc["ID"]
        if alloc.get("PreviousAllocation"):
            # GC may have removed one or more predecessors.
            original_id = None
            replacements.insert(0, alloc["ID"])
        successor = alloc.get("NextAllocation")
        if successor and successor not in replacements:
            replacements.append(successor)
        if replacements:
            return WorkloadStatus(
                "unknown", handle, original_id, None, tuple(replacements)
            )
        if alloc["ClientStatus"] in ("unknown", "lost"):
            return WorkloadStatus("unknown", handle, original_id)
        task = (alloc.get("TaskStates") or {}).get("workload") or {}
        events = task.get("Events") or []
        exit_code = next(
            (e.get("ExitCode") for e in reversed(events) if e["Type"] == "Terminated"),
            None,
        )
        client = alloc["ClientStatus"]
        if client in ("complete", "failed"):
            killed = any(e["Type"] in ("Killing", "Killed") for e in events)
            stopped_before_launch = (
                client == "complete" and exit_code is None and not task.get("Failed")
            )
            if (
                job["Stop"]
                and alloc["DesiredStatus"] == "stop"
                and (killed or stopped_before_launch)
            ):
                state = "stopped"
            elif client == "failed" or task.get("Failed") or exit_code not in (0, None):
                state = "failed"
            else:
                state = "succeeded" if exit_code == 0 else "unknown"
        elif client in ("pending", "running"):
            state = "running" if task.get("State") == "running" else "pending"
        else:
            state = "unknown"
        return WorkloadStatus(state, handle, alloc["ID"], exit_code)

    def stop(self, handle: str) -> None:
        path = self._job_path(handle)
        if not self._request("GET", path)["Stop"]:
            self._request("DELETE", f"{path}?purge=false")


class WorkerNomadBackend(NomadBackend):
    """The trusted development launcher selects the one credential-bearing task."""

    def __init__(self, address, image, endpoint):
        super().__init__(address)
        self.spec = WorkloadSpec(image, (WORKER_EXECUTABLE,))
        self.endpoint = endpoint

    def _metadata(self, run_id, spec):
        if spec != self.spec:
            raise WorkloadConflictError(
                "The attempt requires a different worker image or executable."
            )
        return {
            **super()._metadata(run_id, spec),
            "harness_worker_endpoint": self.endpoint,
            "harness_worker_profile": "1",
        }

    def _configure_job(self, job):
        group = job["TaskGroups"][0]
        group.setdefault("Volumes", {}).update(
            {
                "codex-login": {
                    "Name": "codex-login",
                    "Type": "host",
                    "Source": "harness-codex-login",
                    "ReadOnly": True,
                }
            }
        )
        task = group["Tasks"][1]
        task["VolumeMounts"] = [
            {
                "Volume": "codex-login",
                "Destination": "/worker/.codex/auth.json",
                "ReadOnly": True,
            }
        ]
        task["Identities"] = [
            {
                "Name": "harness",
                "Audience": ["harness-worker"],
                "TTL": 3600_000_000_000,
                "File": True,
                "Filepath": "secrets/harness.jwt",
            }
        ]
        task["Env"] = {"HARNESS_WORKER_MCP_URL": self.endpoint}
        task["Resources"] = {"CPU": 500, "MemoryMB": 512}
