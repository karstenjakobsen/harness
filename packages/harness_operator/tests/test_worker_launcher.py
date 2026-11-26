import json
import runpy
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from harness_api import GoalAPI, OperatorAPI, WorkAPI, WorkConflictError
from harness_operator.worker import (
    DockerEngine,
    DockerWorkerLauncher,
    WorkerLaunchError,
    WorkerTimeoutError,
)

IMAGE = "sha256:" + "a" * 64
OTHER_IMAGE = "sha256:" + "b" * 64
ENTRYPOINT = Path(__file__).resolve().parents[3] / "dev/worker/harness-worker.py"


class FakeDockerEngine:
    """Replace only Docker; workspace files, authority and HTTP remain real."""

    def __init__(self, *, on_wait=None, exit_code=0):
        self.on_wait = on_wait
        self.exit_code = exit_code
        self.calls = []
        self.containers = {}
        self.arguments = None
        self.environment = None
        self.create_count = 0
        self.start_count = 0
        self.lose_create_response = False
        self.lose_start_response = False
        self.fail_wait = False
        self.wait_timeout_once = False
        self.forbid_calls = False

    def _call(self, name):
        assert not self.forbid_calls, f"Unexpected Docker operation: {name}"
        self.calls.append(name)

    def image_id(self, reference):
        self._call("image_id")
        assert reference == IMAGE
        return reference

    def inspect(self, name):
        self._call("inspect")
        return self.containers.get(name)

    def create(self, arguments, environment):
        self._call("create")
        self.create_count += 1
        self.arguments = arguments
        self.environment = environment
        name = arguments[arguments.index("--name") + 1]
        labels = {
            arguments[i + 1].partition("=")[0]: arguments[i + 1].partition("=")[2]
            for i, argument in enumerate(arguments)
            if argument == "--label"
        }
        assert name not in self.containers
        self.containers[name] = {
            "Id": f"container-{self.create_count}",
            "Image": arguments[-4],
            "Config": {"Labels": labels},
            "HostConfig": {"RestartPolicy": {"Name": "no"}},
            "State": {"Status": "created"},
        }
        if self.lose_create_response:
            self.lose_create_response = False
            raise WorkerLaunchError("The Docker create response was lost.")
        return self.containers[name]["Id"]

    def _container(self, container_id):
        return next(c for c in self.containers.values() if c["Id"] == container_id)

    def start(self, container_id):
        self._call("start")
        self.start_count += 1
        self._container(container_id)["State"]["Status"] = "running"
        if self.lose_start_response:
            self.lose_start_response = False
            raise WorkerLaunchError("The Docker start response was lost.")

    def wait(self, container_id, timeout):
        self._call("wait")
        assert timeout > 0
        if self.wait_timeout_once:
            self.wait_timeout_once = False
            raise WorkerTimeoutError("Docker wait timed out.")
        if self.fail_wait:
            raise WorkerLaunchError("The launcher lost contact while waiting.")
        if self.on_wait is not None:
            self.on_wait(self)
        self._container(container_id)["State"]["Status"] = "exited"
        return self.exit_code

    def stop(self, container_id):
        self._call("stop")
        self._container(container_id)["State"]["Status"] = "exited"

    def write_logs(self, container_id, stdout, stderr):
        self._call("write_logs")
        stdout.write(json.dumps({"container_id": container_id}) + "\n")
        stderr.write("")

    @property
    def workspace(self):
        mount = next(
            self.arguments[i + 1]
            for i, argument in enumerate(self.arguments)
            if argument == "--mount"
            and self.arguments[i + 1].endswith(",dst=/workspace")
        )
        return Path(
            mount.removeprefix("type=bind,src=").removesuffix(",dst=/workspace")
        )

    def submit(self, relative_path):
        """Use the actual worker MCP endpoint supplied to this container."""
        with httpx.Client(
            headers={
                "Authorization": f"Bearer {self.environment['HARNESS_WORKER_TOKEN']}",
                "Accept": "application/json, text/event-stream",
            },
            timeout=5,
            trust_env=False,
        ) as http:
            endpoint = self.environment["HARNESS_WORKER_MCP_URL"]
            initialized = http.post(
                endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "worker-fixture", "version": "1"},
                    },
                },
            )
            initialized.raise_for_status()
            response = http.post(
                endpoint,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "submit_work_result",
                        "arguments": {"relative_path": relative_path},
                    },
                },
            )
            response.raise_for_status()
            result = response.json()["result"]
            assert not result.get("isError"), result
            return result["structuredContent"]


@pytest.fixture
def launch_workspace(tmp_path):
    database = tmp_path / "selected-workspace.db"
    goals = GoalAPI(database)
    goal = goals.create_goal("Produce a deliverable", status="active")
    operator = OperatorAPI(database).register_operator("Builder")
    work = WorkAPI(database)
    item = work.create_work_item(
        goal["id"], goal["revision"], operator["id"], "Do the assigned work."
    )
    auth = tmp_path / "development-auth.json"
    auth.write_text('{"fixture": "development login"}')
    return work, goals, item, auth


def submit_file(engine):
    (engine.workspace / "result.txt").write_text("Saved deliverable")
    engine.submit("result.txt")


def test_lost_create_response_and_cleaned_replay_never_create_a_second_container(
    launch_workspace,
):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine(on_wait=submit_file)
    engine.lose_create_response = True
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    with pytest.raises(WorkerLaunchError, match="create response"):
        launcher.start(item["id"], "lost-response", IMAGE)
    assert engine.create_count == 1 and engine.start_count == 0
    result = launcher.start(item["id"], "lost-response", IMAGE)
    assert result["attempt"]["exit_code"] == 0
    assert engine.create_count == engine.start_count == 1
    assert work.read_artifact_bytes(result["artifact"]["id"]) == b"Saved deliverable"
    assert result["attempt"]["scratch_cleaned_at"] is not None
    assert not Path(result["attempt"]["scratch_path"]).exists()
    assert not (launcher.directory("lost-response") / "codex-home").exists()
    auth.unlink()
    engine.forbid_calls = True
    assert launcher.start(item["id"], "lost-response", IMAGE) == result


def test_lost_start_response_reconciles_running_container(launch_workspace):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine(on_wait=submit_file)
    engine.lose_start_response = True
    result = DockerWorkerLauncher(work, engine=engine, auth_path=auth).start(
        item["id"], "lost-start", IMAGE
    )
    assert result["artifact"] is not None
    assert engine.create_count == engine.start_count == 1
    assert result["attempt"]["exit_code"] == 0


def test_concurrent_requests_for_one_attempt_start_one_container(launch_workspace):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine(on_wait=submit_file)
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    barrier = threading.Barrier(2)

    def launch():
        barrier.wait(timeout=5)
        return launcher.start(item["id"], "concurrent", IMAGE)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(launch)
        second = executor.submit(launch)
        assert first.result(timeout=20) == second.result(timeout=20)
    assert engine.create_count == engine.start_count == 1
    assert engine.calls.count("wait") == 1


def test_completed_attempt_rejects_changed_image_or_work_item(launch_workspace):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine()
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    launcher.start(item["id"], "immutable", IMAGE)
    changed = work.create_work_item(
        item["goal_id"], item["goal_revision"], item["operator_id"], "A changed brief."
    )
    engine.forbid_calls = True
    with pytest.raises(WorkConflictError, match="different image"):
        launcher.start(item["id"], "immutable", OTHER_IMAGE)
    with pytest.raises(WorkConflictError):
        launcher.start(changed["id"], "immutable", IMAGE)


def git(directory, *arguments):
    return subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize("borrowed_objects", [False, True])
def test_checkout_is_a_writable_isolated_copy_without_source_remote_credentials(
    launch_workspace, tmp_path, borrowed_objects
):
    work, goals, original_item, auth = launch_workspace
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    (source / "value.py").write_text("VALUE = 1\n")
    git(source, "add", "value.py")
    git(
        source,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Initial",
    )
    base = git(source, "rev-parse", "HEAD")
    original_objects = source / ".git/objects"
    if borrowed_objects:
        borrowed_source = tmp_path / "borrowed-source"
        subprocess.run(
            ["git", "clone", "--shared", str(source), str(borrowed_source)],
            check=True,
            capture_output=True,
        )
        source = borrowed_source
        git(source, "remote", "remove", "origin")
    git(
        source,
        "remote",
        "add",
        "origin",
        "https://credential-marker@example.invalid/private",
    )
    item = work.create_work_item(
        original_item["goal_id"],
        1,
        original_item["operator_id"],
        "Change VALUE to two and submit a patch.",
        source_path=source,
        base_sha=base,
    )
    observed = {}

    def edit_checkout(engine):
        scratch = engine.workspace
        observed["base"] = git(scratch, "rev-parse", "HEAD")
        observed["remotes"] = git(scratch, "remote", "-v")
        observed["config"] = (scratch / ".git/config").read_text()
        copied_objects = scratch / ".git/objects"
        assert not (copied_objects / "info/alternates").exists()
        observed["independent_object"] = all(
            not (copied_objects / path.relative_to(original_objects)).is_file()
            or path.stat().st_ino
            != (copied_objects / path.relative_to(original_objects)).stat().st_ino
            for path in original_objects.rglob("*")
            if path.is_file()
        )
        (scratch / "value.py").write_text("VALUE = 2\n")
        subprocess.run(
            [sys.executable, "-c", "from value import VALUE; assert VALUE == 2"],
            cwd=scratch,
            check=True,
        )
        (scratch / "changes.patch").write_text(git(scratch, "diff", "--binary") + "\n")
        engine.submit("changes.patch")

    engine = FakeDockerEngine(on_wait=edit_checkout)
    result = DockerWorkerLauncher(work, engine=engine, auth_path=auth).start(
        item["id"], "checkout", IMAGE
    )
    assert observed["base"] == base
    assert observed["remotes"] == ""
    assert "credential-marker" not in observed["config"]
    assert observed["independent_object"]
    assert (source / "value.py").read_text() == "VALUE = 1\n"
    assert git(source, "status", "--porcelain") == ""
    assert result["artifact"]["base_sha"] == base
    assert b"+VALUE = 2" in work.read_artifact_bytes(result["artifact"]["id"])
    assert goals.get_goal(item["goal_id"])["status"] == "active"
    arguments = engine.arguments
    assert arguments[arguments.index("--restart") + 1] == "no"
    assert arguments[arguments.index("--network") + 1] == "host"
    assert arguments[-4:] == [IMAGE, "run", "--attempt-id", "checkout"]
    assert engine.environment["HARNESS_WORKER_ATTEMPT_ID"] == "checkout"
    assert engine.environment["CODEX_HOME"] == "/harness-codex-home"
    assert any(argument.endswith(",dst=/harness-codex-home") for argument in arguments)
    assert "CODEX_HOME" in [
        arguments[index + 1]
        for index, argument in enumerate(arguments)
        if argument == "--env"
    ]


def test_process_failure_preserves_submission_and_leaves_goal_open(launch_workspace):
    work, goals, item, auth = launch_workspace
    engine = FakeDockerEngine(on_wait=submit_file, exit_code=23)
    result = DockerWorkerLauncher(work, engine=engine, auth_path=auth).start(
        item["id"], "failed-process", IMAGE
    )
    assert result["attempt"]["exit_code"] == 23
    assert result["artifact"]["relative_path"] == "result.txt"
    assert work.read_artifact_bytes(result["artifact"]["id"]) == b"Saved deliverable"
    goal = goals.get_goal(item["goal_id"])
    assert goal["status"] == "active" and goal["revision"] == 1


@pytest.mark.parametrize("inherited_git_environment", ["directory", "all"])
def test_checkout_ignores_inherited_git_environment_and_preserves_source(
    launch_workspace, tmp_path, monkeypatch, inherited_git_environment
):
    work, _, original_item, auth = launch_workspace
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    (source / "value.py").write_text("VALUE = 1\n")
    git(source, "add", "value.py")
    git(
        source,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Initial",
    )
    base = git(source, "rev-parse", "HEAD")
    git(source, "remote", "add", "origin", "https://owner@example.invalid/project")
    head = (source / ".git/HEAD").read_bytes()
    index = (source / ".git/index").read_bytes()
    config = (source / ".git/config").read_bytes()
    (source / "value.py").write_text("VALUE = 99  # Owner's uncommitted edit\n")
    item = work.create_work_item(
        original_item["goal_id"],
        1,
        original_item["operator_id"],
        "Read the base checkout.",
        source_path=source,
        base_sha=base,
    )
    with monkeypatch.context() as inherited:
        inherited.setenv("GIT_DIR", str(source / ".git"))
        if inherited_git_environment == "all":
            for key, value in {
                "GIT_WORK_TREE": source,
                "GIT_COMMON_DIR": source / ".git",
                "GIT_INDEX_FILE": source / ".git/index",
                "GIT_OBJECT_DIRECTORY": source / ".git/objects",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": source / ".git/objects",
                "GIT_NAMESPACE": "inherited-hook",
            }.items():
                inherited.setenv(key, str(value))

        def inspect_checkout(engine):
            assert (engine.workspace / "value.py").read_text() == "VALUE = 1\n"
            assert (engine.workspace / ".git/HEAD").read_text().strip() == base
            submit_file(engine)

        result = DockerWorkerLauncher(
            work,
            engine=FakeDockerEngine(on_wait=inspect_checkout),
            auth_path=auth,
        ).start(item["id"], "inherited-environment", IMAGE)
    assert result["attempt"]["exit_code"] == 0
    assert (source / ".git/HEAD").read_bytes() == head
    assert (source / ".git/index").read_bytes() == index
    assert (source / ".git/config").read_bytes() == config
    assert (
        source / "value.py"
    ).read_text() == "VALUE = 99  # Owner's uncommitted edit\n"


def test_missing_recorded_container_is_not_replaced(launch_workspace):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine()
    engine.fail_wait = True
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    with pytest.raises(WorkerLaunchError, match="lost contact"):
        launcher.start(item["id"], "missing-container", IMAGE)
    assert work.get_attempt("missing-container")["container_id"] == "container-1"
    engine.containers.clear()
    engine.fail_wait = False
    with pytest.raises(WorkerLaunchError, match="missing; refusing a replacement"):
        launcher.start(item["id"], "missing-container", IMAGE)
    assert engine.create_count == engine.start_count == 1


@pytest.mark.parametrize("remove_private_auth", [False, True])
def test_interrupted_launch_recovery_does_not_require_original_login(
    launch_workspace, remove_private_auth
):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine()
    engine.fail_wait = True
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    with pytest.raises(WorkerLaunchError, match="lost contact"):
        launcher.start(item["id"], "recovery", IMAGE)
    private_auth = launcher.directory("recovery") / "codex-home/auth.json"
    private_auth.write_text('{"fixture": "refreshed by the running session"}')
    if remove_private_auth:
        private_auth.unlink()
    auth.unlink()
    engine.fail_wait = False

    def finish(engine):
        if not remove_private_auth:
            assert "refreshed" in private_auth.read_text()
        submit_file(engine)

    engine.on_wait = finish
    result = launcher.start(item["id"], "recovery", IMAGE)
    assert result["attempt"]["exit_code"] == 0
    assert result["artifact"] is not None
    assert engine.create_count == engine.start_count == 1
    assert not private_auth.exists()


def test_different_databases_in_one_directory_do_not_share_attempt_state(
    launch_workspace,
):
    work, _, item, auth = launch_workspace
    first_engine = FakeDockerEngine()
    first_engine.fail_wait = True
    first = DockerWorkerLauncher(work, engine=first_engine, auth_path=auth)
    with pytest.raises(WorkerLaunchError, match="lost contact"):
        first.start(item["id"], "same-attempt", IMAGE)
    marker = first_engine.workspace / "in-progress.txt"
    marker.write_text("First workspace's active work")

    other_database = work.database_path.with_name("other-workspace.db")
    other_goal = GoalAPI(other_database).create_goal("Other work", status="active")
    other_operator = OperatorAPI(other_database).register_operator("Other builder")
    other_api = WorkAPI(other_database)
    other_item = other_api.create_work_item(
        other_goal["id"], 1, other_operator["id"], "Other assignment"
    )
    second_engine = FakeDockerEngine(on_wait=submit_file)
    second = DockerWorkerLauncher(other_api, engine=second_engine, auth_path=auth)
    result = second.start(other_item["id"], "same-attempt", IMAGE)
    assert result["artifact"] is not None
    assert marker.read_text() == "First workspace's active work"
    assert first.directory("same-attempt") != second.directory("same-attempt")
    first_engine.fail_wait = False
    first_engine.on_wait = submit_file
    first.start(item["id"], "same-attempt", IMAGE)
    assert first_engine.create_count == first_engine.start_count == 1


@pytest.mark.parametrize("alias_kind", ["directory", "database"])
def test_workspace_path_alias_replays_the_same_attempt(
    launch_workspace, tmp_path, alias_kind
):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine(on_wait=submit_file)
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    result = launcher.start(item["id"], "aliased-workspace", IMAGE)
    if alias_kind == "directory":
        alias = tmp_path / "workspace-alias"
        alias.symlink_to(work.database_path.parent, target_is_directory=True)
        alias_database = alias / work.database_path.name
    else:
        alias_database = tmp_path / "database-alias.db"
        alias_database.symlink_to(work.database_path)
    alias_launcher = DockerWorkerLauncher(
        WorkAPI(alias_database), engine=engine, auth_path=auth
    )
    engine.forbid_calls = True
    assert alias_launcher.start(item["id"], "aliased-workspace", IMAGE) == result


@pytest.mark.parametrize("failure", ["missing_base", "timeout"])
def test_checkout_preparation_failure_raises_a_launcher_error(
    launch_workspace, tmp_path, monkeypatch, failure
):
    work, _, original, auth = launch_workspace
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    item = work.create_work_item(
        original["goal_id"],
        1,
        original["operator_id"],
        "Check the recorded base",
        source_path=source,
        base_sha="c" * 40,
    )
    if failure == "timeout":

        def timeout(arguments, **kwargs):
            assert kwargs["timeout"] == 30
            raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

        monkeypatch.setattr("harness_operator.worker.subprocess.run", timeout)
    engine = FakeDockerEngine()
    with pytest.raises(WorkerLaunchError, match="Git"):
        DockerWorkerLauncher(work, engine=engine, auth_path=auth).start(
            item["id"], "missing-base", IMAGE
        )
    assert engine.create_count == engine.start_count == 0


@pytest.mark.parametrize(
    "operation", ["image_id", "inspect", "create", "start", "wait", "logs"]
)
def test_docker_timeouts_raise_launcher_errors(tmp_path, monkeypatch, operation):
    def timeout(arguments, **kwargs):
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr("harness_operator.worker.subprocess.run", timeout)
    engine = DockerEngine()
    with (tmp_path / "output").open("w") as output:
        invoke = {
            "image_id": lambda: engine.image_id(IMAGE),
            "inspect": lambda: engine.inspect("container"),
            "create": lambda: engine.create(["create"], {}),
            "start": lambda: engine.start("container"),
            "wait": lambda: engine.wait("container", 600),
            "logs": lambda: engine.write_logs("container", output, output),
        }[operation]
        with pytest.raises(WorkerLaunchError, match="timed out"):
            invoke()


def test_docker_log_failure_raises_a_launcher_error(tmp_path, monkeypatch):
    def failed(arguments, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(7, arguments)
        return subprocess.CompletedProcess(arguments, 7)

    monkeypatch.setattr("harness_operator.worker.subprocess.run", failed)
    with (
        (tmp_path / "output").open("w") as output,
        pytest.raises(WorkerLaunchError, match="logs"),
    ):
        DockerEngine().write_logs("container", output, output)


def test_worker_deadline_stops_container_and_records_exit(launch_workspace):
    work, _, item, auth = launch_workspace
    engine = FakeDockerEngine(exit_code=137)
    engine.wait_timeout_once = True
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    result = launcher.start(item["id"], "deadline", IMAGE, timeout=1)
    assert engine.calls.count("wait") == 2
    assert "stop" in engine.calls
    assert engine.create_count == engine.start_count == 1
    assert result["attempt"]["exit_code"] == 137
    assert result["artifact"] is None
    assert result["attempt"]["scratch_cleaned_at"] is not None
    assert not (launcher.directory("deadline") / "codex-home").exists()


def test_replay_finishes_cleanup_after_exit_was_saved_before_host_crash(
    launch_workspace,
):
    work, _, item, auth = launch_workspace
    work.create_attempt("exit-saved", item["id"])
    engine = FakeDockerEngine()
    launcher = DockerWorkerLauncher(work, engine=engine, auth_path=auth)
    directory = launcher.directory("exit-saved")
    scratch = directory / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "temporary").write_text("Scratch remaining after a crash")
    auth_directory = directory / "codex-home"
    auth_directory.mkdir()
    (auth_directory / "auth.json").write_text(auth.read_text())
    work.set_scratch("exit-saved", scratch)
    work.record_launch("exit-saved", "recorded-container", IMAGE)
    work.record_exit("exit-saved", 0)
    auth.unlink()
    engine.forbid_calls = True
    result = launcher.start(item["id"], "exit-saved", IMAGE)
    assert result["attempt"]["scratch_cleaned_at"] is not None
    assert not scratch.exists() and not auth_directory.exists()
    assert result["attempt"]["container_id"] == "recorded-container"


def test_entrypoint_uses_one_generic_codex_workspace_session():
    module = runpy.run_path(str(ENTRYPOINT))
    environment = {
        "HARNESS_WORKER_ATTEMPT_ID": "selected-attempt",
        "HARNESS_WORKER_TOKEN": "runtime-only-credential",
        "HARNESS_WORKER_MCP_URL": "http://127.0.0.1:8001/mcp",
    }
    arguments = module["command"]("selected-attempt", environment)
    assert arguments[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "--json" in arguments and "--skip-git-repo-check" in arguments
    assert arguments[arguments.index("--sandbox") + 1] == "workspace-write"
    assert arguments[arguments.index("-C") + 1] == "/workspace"
    assert 'mcp_servers.worker.bearer_token_env_var="HARNESS_WORKER_TOKEN"' in arguments
    assert "runtime-only-credential" not in " ".join(arguments)
    instruction = arguments[-1]
    assert instruction == module["INSTRUCTION"]
    assert all(
        value not in instruction
        for value in ("cities.txt", "changes.patch", "selected-attempt", "handoff")
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"HARNESS_WORKER_ATTEMPT_ID": "other-attempt"},
        {"HARNESS_WORKER_TOKEN": ""},
        {"HARNESS_WORKER_MCP_URL": ""},
        {"HARNESS_WORKER_MCP_URL": "file:///workspace"},
        {"HARNESS_WORKER_MCP_URL": "https://credential@example.invalid/mcp"},
    ],
)
def test_entrypoint_rejects_invalid_runtime_assignment(updates):
    module = runpy.run_path(str(ENTRYPOINT))
    environment = {
        "HARNESS_WORKER_ATTEMPT_ID": "selected-attempt",
        "HARNESS_WORKER_TOKEN": "runtime-only-credential",
        "HARNESS_WORKER_MCP_URL": "http://127.0.0.1:8001/mcp",
    }
    with pytest.raises(ValueError):
        module["command"]("selected-attempt", environment | updates)
