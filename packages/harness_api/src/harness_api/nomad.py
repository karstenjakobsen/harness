"""Execute one Docker batch task on a caller-selected Nomad cluster."""

import hashlib
import json
import re
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .execution import ExecutionState, WorkloadSpec, WorkloadStatus


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

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(
            f"{self.address}/v1/{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    @staticmethod
    def _job_path(handle: str) -> str:
        if not re.fullmatch(r"harness-[0-9a-f]{64}", handle):
            raise ValueError("Invalid Nomad workload handle.")
        return f"job/{handle}"

    def start(self, run_id: str, spec: WorkloadSpec) -> str:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Supply a nonempty execution run ID.")
        handle = "harness-" + hashlib.sha256(run_id.encode()).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps([spec.image, spec.argv]).encode()
        ).hexdigest()
        meta = {"harness_run_id": run_id, "harness_spec_sha256": fingerprint}
        job = {
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
                    "Tasks": [
                        {
                            "Name": "workload",
                            "Driver": "docker",
                            "Config": {
                                "image": spec.image,
                                "entrypoint": spec.argv[:1],
                                "args": spec.argv[1:],
                            },
                        }
                    ],
                }
            ],
        }
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
        allocations = self._request("GET", f"{path}/allocations") or []
        state: ExecutionState
        if not allocations:
            state = "stopped" if job["Stop"] else "pending"
            if job.get("Status") == "dead" and not job["Stop"]:
                state = "unknown"
            return WorkloadStatus(state, handle)
        latest = max(allocations, key=lambda alloc: alloc["CreateIndex"])
        alloc = self._request("GET", f"allocation/{latest['ID']}")
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
