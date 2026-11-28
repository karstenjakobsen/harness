"""Watch one Slice 11 worker attempt live and replay its activity by attempt ID."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import experiment
import httpx

TASK = "workload"
SUBSTANTIVE = ("command_execution", "mcp_tool_call", "tool_call")
SHOWN = SUBSTANTIVE + ("agent_message", "reasoning")
SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),
    re.compile(r"sk-[\w-]{20,}"),
    re.compile(r"ksk_[\w-]{12,}"),
)


def now():
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def activity_directory(workspace, attempt_id):
    if Path(attempt_id).name != attempt_id or attempt_id in ("", ".", ".."):
        raise ValueError("The attempt ID must be a single path component.")
    return Path(workspace) / "phase2/activity" / attempt_id


def read_events(path):
    """Return complete JSONL events with line numbers and any partial last line."""
    data = path.read_bytes() if path.exists() else b""
    lines = data.split(b"\n")
    partial = lines.pop()
    events = []
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append((number, event, hashlib.sha256(line).hexdigest()))
    return events, partial.decode(errors="replace") or None


def redact(text, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text if len(text) <= 240 else text[:240] + "…"


def summary(event, secrets=()):
    """Select credential-free fields for display; return None for other events."""
    data = experiment.kiro_event_data(event)
    if data:
        update = data.get("update") or {}
        update_type = update.get("sessionUpdate")
        if update_type not in ("tool_call", "tool_call_update"):
            return None
        return {
            "event": update_type,
            "kind": "tool_call",
            "item_id": redact(update.get("toolCallId"), secrets),
            "title": redact(update.get("title", ""), secrets),
            "status": redact(update.get("status", ""), secrets),
        }
    item = event.get("item") or {}
    kind = item.get("type")
    if not event.get("type", "").startswith("item.") or kind not in SHOWN:
        return None
    selected = {"event": event["type"], "item_id": item.get("id"), "kind": kind}
    if kind == "command_execution":
        selected.update(
            command=redact(item.get("command", ""), secrets),
            status=item.get("status"),
            exit_code=item.get("exit_code"),
        )
    elif kind == "mcp_tool_call":
        selected.update(
            server=item.get("server"),
            tool=item.get("tool"),
            status=item.get("status"),
            argument_names=sorted((item.get("arguments") or {}).keys()),
            error=redact(item["error"], secrets) if item.get("error") else None,
        )
    else:
        selected["text"] = redact(item.get("text", ""), secrets)
    return selected


class Capture:
    """Follow one task stream from the beginning into a file under the attempt."""

    def __init__(self, watcher, stream, path):
        self.watcher = watcher
        self.stream = stream
        self.path = path
        self.offset = 0
        self.interruptions = []
        self.ended = False
        self.thread = threading.Thread(target=self.follow, daemon=True)

    def append(self, chunk):
        with self.path.open("ab") as file:
            file.write(chunk)
        self.offset += len(chunk)
        if self.stream == "stdout":
            self.watcher.inspect_new_events()

    def follow(self):
        try:
            self.follow_stream()
        except Exception as error:  # noqa: BLE001
            # Keep what was read; the capture is labelled at the end.
            self.interruptions.append({"at": now(), "error": str(error)})

    def follow_stream(self):
        watcher = self.watcher
        with watcher.client() as client:
            while not watcher.allocation_id:
                if watcher.stopping.is_set():
                    return
                placed = client.get(f"job/{watcher.receipt['job_id']}/allocations")
                if placed.status_code == 200 and placed.json():
                    watcher.allocation_id = placed.json()[0]["ID"]
                    watcher.save()
                else:
                    time.sleep(0.2)
            while not watcher.stopping.is_set():
                try:
                    with client.stream(
                        "GET",
                        f"client/fs/logs/{watcher.allocation_id}",
                        params={
                            "task": TASK,
                            "type": self.stream,
                            "follow": "true",
                            "origin": "start",
                            "offset": str(self.offset),
                            "plain": "true",
                        },
                        timeout=httpx.Timeout(5, read=10),
                    ) as response:
                        if response.status_code != 200:
                            # The task may not have started yet.
                            time.sleep(0.5)
                            continue
                        for chunk in response.iter_bytes():
                            self.append(chunk)
                    if watcher.task_terminal(client):
                        self.ended = True
                        return
                except httpx.ReadTimeout:
                    if watcher.task_terminal(client):
                        self.ended = True
                        return
                except httpx.TransportError as error:
                    self.interruptions.append({"at": now(), "error": str(error)})
                    time.sleep(0.5)

    def drain(self, client):
        """Read any bytes the follower had not yet received, without following."""
        if not self.watcher.allocation_id:
            return False
        while True:
            response = client.get(
                f"client/fs/logs/{self.watcher.allocation_id}",
                params={
                    "task": TASK,
                    "type": self.stream,
                    "origin": "start",
                    "offset": str(self.offset),
                    "plain": "true",
                },
            )
            response.raise_for_status()
            if not response.content:
                return True
            self.append(response.content)


class Watcher:
    def __init__(self, receipt, receipt_path, nomad_address):
        self.receipt = receipt
        self.nomad_address = nomad_address
        self.directory = activity_directory(receipt["workspace"], receipt["attempt_id"])
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.runtime = receipt_path.parent / "runtime"
        self.allocation_id = None
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.seen_lines = 0
        self.capture = {
            "attempt_id": receipt["attempt_id"],
            "job_id": receipt["job_id"],
            "task": TASK,
            "allocation_id": None,
            "nomad_address": nomad_address,
            "started_at": now(),
            "status": "capturing",
            "live_event": None,
            "running_observations": [],
            "task_outcome": None,
            "submission": None,
            "streams": {},
        }
        self.streams = {
            name: Capture(self, name, self.directory / filename)
            for name, filename in (("stdout", "stdout.jsonl"), ("stderr", "stderr.log"))
        }
        for capture in self.streams.values():
            capture.path.touch(mode=0o600)
        self.save()

    def client(self):
        headers = (
            {"X-Nomad-Token": os.environ["NOMAD_TOKEN"]}
            if os.environ.get("NOMAD_TOKEN")
            else {}
        )
        return httpx.Client(
            base_url=self.nomad_address.rstrip("/") + "/v1/",
            headers=headers,
            timeout=5,
            trust_env=False,
        )

    def save(self):
        with self.lock:
            self.capture["allocation_id"] = self.allocation_id
            experiment.save_json(self.directory / "capture.json", self.capture)

    def secrets(self):
        secrets = []
        for name in ("credential", "provider-key"):
            try:
                secrets.append((self.runtime / name).read_text().strip())
            except OSError:
                pass
        return tuple(secrets)

    def task_state(self, client):
        allocation = client.get(f"allocation/{self.allocation_id}")
        allocation.raise_for_status()
        allocation = allocation.json()
        task = (allocation.get("TaskStates") or {}).get(TASK) or {}
        return allocation, task

    def task_terminal(self, client):
        try:
            allocation, task = self.task_state(client)
        except httpx.HTTPError:
            return False
        return task.get("State") == "dead" or allocation["ClientStatus"] in (
            "complete",
            "failed",
        )

    def inspect_new_events(self):
        events, _ = read_events(self.streams["stdout"].path)
        fresh = [entry for entry in events if entry[0] > self.seen_lines]
        if events:
            self.seen_lines = events[-1][0]
        for number, event, digest in fresh:
            selected = summary(event, self.secrets())
            if selected is None:
                continue
            print("live:", json.dumps(selected, ensure_ascii=False), flush=True)
            confirmed = self.capture["live_event"]
            if selected["kind"] not in SUBSTANTIVE or (
                confirmed and confirmed["running_confirmed"]
            ):
                continue
            displayed = {
                "line": number,
                "sha256": digest,
                "displayed_at": now(),
                "summary": selected,
                "running_confirmed": False,
            }
            # Ask Nomad independently, after the event was displayed and saved.
            self.capture["live_event"] = displayed
            self.save()
            with self.client() as client:
                try:
                    allocation, task = self.task_state(client)
                    observation = {
                        "line": number,
                        "observed_at": now(),
                        "client_status": allocation["ClientStatus"],
                        "task_state": task.get("State"),
                        "task_started_at": task.get("StartedAt"),
                        "allocation_modify_time": allocation.get("ModifyTime"),
                    }
                except httpx.HTTPError as error:
                    observation = {
                        "line": number,
                        "observed_at": now(),
                        "error": str(error),
                    }
            self.capture["running_observations"].append(observation)
            displayed["running_confirmed"] = (
                observation.get("task_state") == "running"
                and observation.get("client_status") == "running"
            )
            print("nomad:", json.dumps(observation), flush=True)
            self.save()

    def start(self):
        for capture in self.streams.values():
            capture.thread.start()

    def finish(self):
        """Record Nomad's outcome and drain both streams before cleanup."""
        self.stopping.set()
        for capture in self.streams.values():
            capture.thread.join(timeout=30)
            if capture.thread.is_alive():
                raise RuntimeError(f"The {capture.stream} follower did not stop.")
        drained = True
        with self.client() as client:
            for capture in self.streams.values():
                try:
                    drained &= capture.drain(client)
                except httpx.HTTPError as error:
                    capture.interruptions.append({"at": now(), "error": str(error)})
                    drained = False
            if self.allocation_id:
                allocation, task = self.task_state(client)
                terminated = next(
                    (
                        event
                        for event in reversed(task.get("Events") or [])
                        if event.get("Type") == "Terminated"
                    ),
                    {},
                )
                self.capture["task_outcome"] = {
                    "observed_at": now(),
                    "client_status": allocation["ClientStatus"],
                    "task_state": task.get("State"),
                    "failed": task.get("Failed"),
                    "restarts": task.get("Restarts"),
                    "exit_code": terminated.get("ExitCode"),
                    "finished_at": task.get("FinishedAt"),
                }
        self.close(drained)

    def close(self, drained):
        events, partial = read_events(self.streams["stdout"].path)
        for name, capture in self.streams.items():
            self.capture["streams"][name] = {
                "path": capture.path.name,
                "bytes": capture.offset,
                "follow_ended": capture.ended,
                "interruptions": capture.interruptions,
            }
        self.capture["streams"]["stdout"].update(
            events=len(events), partial_last_line=partial is not None
        )
        complete = (
            drained
            and partial is None
            and self.capture["task_outcome"] is not None
            and self.capture["task_outcome"]["task_state"] == "dead"
        )
        self.capture["status"] = "complete" if complete else "incomplete"
        self.capture["finished_at"] = now()
        self.save()


def submission_check(receipt, events):
    """Compare the worker's claimed submission with the worker MCP audit."""
    claimed = [
        event["item"]
        for _, event, _ in events
        if event.get("type") == "item.completed"
        and (event.get("item") or {}).get("type") == "mcp_tool_call"
        and event["item"].get("tool") == "submit_work_result"
    ]
    inspection = experiment.owner_cli(receipt, "work", "show", receipt["attempt_id"])
    audited = [
        call for call in inspection["calls"] if call["tool"] == "submit_work_result"
    ]
    artifact = inspection["artifact"]
    is_kiro = (receipt.get("launch") or {}).get("worker") == "kiro"
    claimed_success = (
        None
        if is_kiro
        else any(
            item.get("status") == "completed" and not item.get("error")
            for item in claimed
        )
    )
    returned = any(
        call["outcome"] == "returned"
        and artifact is not None
        and call.get("artifact_id") == artifact["id"]
        for call in audited
    )
    return {
        "claimed_calls": None if is_kiro else len(claimed),
        "claimed_success": claimed_success,
        "audited_calls": [
            {
                key: call.get(key)
                for key in ("tool", "outcome", "artifact_id", "finished_at")
            }
            for call in audited
        ],
        "artifact": None
        if artifact is None
        else {
            key: artifact.get(key)
            for key in ("id", "sha256", "attempt_id", "goal_revision", "grant_id")
        },
        "consistent": None if is_kiro else claimed_success == returned,
    }


def watch(receipt, receipt_path, args):
    if receipt["mode"] != "worker" or receipt["phase"] != "rendered":
        raise ValueError("Watch requires a rendered worker attempt not yet submitted.")
    watcher = Watcher(receipt, receipt_path, args.nomad_addr)
    watcher.start()
    finished = experiment.run(
        receipt, receipt_path, args, before_cleanup=watcher.finish
    )
    if watcher.capture["status"] == "capturing":
        # The runner stopped before the drain hook; keep what was read.
        watcher.stopping.set()
        watcher.close(False)
    events, _ = read_events(watcher.streams["stdout"].path)
    watcher.capture["worker_outcome"] = {
        key: finished["execution"].get(key)
        for key in ("state", "exit_code", "task_restarts", "verified", "error")
    }
    watcher.capture["submission"] = submission_check(receipt, events)
    watcher.save()
    return watcher.capture


def replay(workspace, attempt_id):
    directory = activity_directory(workspace, attempt_id)
    capture = json.loads((directory / "capture.json").read_text())
    if capture["attempt_id"] != attempt_id:
        raise ValueError("The saved capture belongs to another attempt.")
    events, partial = read_events(directory / "stdout.jsonl")
    if capture["status"] != "complete":
        # A capture left at "capturing" was interrupted before it was closed.
        capture["status"] = "incomplete"
        print("replay: capture incomplete", flush=True)
    shown = []
    for number, event, _ in events:
        selected = summary(event)
        if selected is not None:
            shown.append({"line": number, **selected})
            print("replay:", json.dumps(shown[-1], ensure_ascii=False))
    live = capture["live_event"]
    located = None
    if live is not None:
        located = next(
            (
                {"line": number, "sha256": digest}
                for number, _, digest in events
                if number == live["line"] and digest == live["sha256"]
            ),
            None,
        )
    return {
        "attempt_id": attempt_id,
        "job_id": capture["job_id"],
        "allocation_id": capture["allocation_id"],
        "task": capture["task"],
        "capture_status": capture["status"],
        "events": len(events),
        "displayed_events": len(shown),
        "partial_last_line": partial is not None,
        "live_event": live,
        "live_event_located": located,
        "task_outcome": capture["task_outcome"],
        "worker_outcome": capture.get("worker_outcome"),
        "submission": capture["submission"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="step", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--receipt", type=Path, required=True)
    run_parser.add_argument("--nomad-addr", default="http://127.0.0.1:14646")
    run_parser.add_argument(
        "--auth-file",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        / "auth.json",
    )
    run_parser.add_argument("--timeout", type=float, default=600)
    run_parser.add_argument("--api-key-file", type=Path)
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("--workspace", type=Path, required=True)
    replay_parser.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    try:
        if args.step == "replay":
            result = replay(args.workspace.resolve(), args.attempt_id)
        else:
            receipt_path = args.receipt.resolve()
            with receipt_path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                receipt = json.loads(receipt_path.read_text())
                result = watch(receipt, receipt_path, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (
        ValueError,
        OSError,
        experiment.subprocess.SubprocessError,
        httpx.HTTPError,
    ) as error:
        print(f"phase2: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
