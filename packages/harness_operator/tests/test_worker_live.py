"""Signed-in worker acceptance and the checkout acceptance oracle."""

import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sysconfig
from pathlib import Path
from uuid import uuid4

import pytest

FIXTURE = Path(__file__).parent / "fixtures/invoice_checkout"
TEST_COMMAND = "python3 -m unittest discover -s tests -p check_invoice.py -v"
TEST_PATH = "tests/check_invoice.py"
TEST_NAME = "test_quantities_are_included_without_losing_decimal_precision"
CITIES = ["København", "Aarhus", "Odense", "Aalborg", "Esbjerg"]
SKILL = {"id": "worker-handoff", "revision": 1}


def process(directory, *args, check=True, timeout=30):
    result = subprocess.run(
        list(map(str, args)),
        cwd=directory,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if check:
        assert result.returncode == 0, (
            f"Command failed: {args!r}\n{result.stdout}\n{result.stderr}"
        )
    return result


def git(directory, *args):
    return process(directory, "git", *args).stdout.strip()


def run_invoice_test(directory):
    return process(directory, *shlex.split(TEST_COMMAND), check=False)


def make_checkout_fixture(directory):
    """Commit a real fixture and prove its specific test fails at that SHA."""
    shutil.copytree(FIXTURE, directory, ignore=shutil.ignore_patterns("__pycache__"))
    git(directory, "init", "--quiet")
    git(directory, "config", "user.email", "fixture@example.invalid")
    git(directory, "config", "user.name", "Checkout fixture")
    git(directory, "add", ".")
    git(directory, "commit", "--quiet", "-m", "Record failing invoice fixture")
    base_sha = git(directory, "rev-parse", "HEAD")
    baseline = run_invoice_test(directory)
    assert baseline.returncode != 0
    assert TEST_NAME in baseline.stderr
    assert "AssertionError" in baseline.stderr
    assert "FAILED (failures=1)" in baseline.stderr
    assert not git(directory, "status", "--porcelain")
    return base_sha


def source_snapshot(directory):
    return {
        path: (directory / path).read_bytes()
        for path in git(directory, "ls-files").splitlines()
    }


def verify_checkout_patch(source, base_sha, patch, destination):
    """Apply the ordinary artifact and run the unchanged test from its base."""
    process(
        source.parent, "git", "clone", "--quiet", "--no-hardlinks", source, destination
    )
    git(destination, "checkout", "--quiet", "--detach", base_sha)
    original_test = (destination / TEST_PATH).read_bytes()
    changes = git(destination, "apply", "--numstat", "--", patch)
    changed_paths = {line.split("\t", 2)[2] for line in changes.splitlines()}
    assert changed_paths == {"invoice.py", "WORKER_TEST_REPORT.txt"}, (
        "The handoff must fix invoice.py and include its test report; "
        f"the acceptance test must stay unchanged. Got {changed_paths!r}"
    )
    git(destination, "apply", "--check", "--", patch)
    git(destination, "apply", "--", patch)
    assert (destination / TEST_PATH).read_bytes() == original_test
    report = (destination / "WORKER_TEST_REPORT.txt").read_text(encoding="utf-8")
    assert TEST_NAME in report
    assert "Ran 1 test" in report and "OK" in report and "FAILED" not in report
    result = run_invoice_test(destination)
    assert result.returncode == 0, result.stdout + result.stderr
    assert TEST_NAME in result.stderr and "OK" in result.stderr
    assert (destination / TEST_PATH).read_bytes() == original_test
    return result


def reference_patch(directory, patch):
    """Create a known good ordinary patch solely to test the acceptance oracle."""
    implementation = directory / "invoice.py"
    implementation.write_text(
        implementation.read_text(encoding="utf-8").replace(
            "Decimal(price) for price, quantity",
            "Decimal(price) * quantity for price, quantity",
        ),
        encoding="utf-8",
    )
    result = run_invoice_test(directory)
    assert result.returncode == 0, result.stderr
    (directory / "WORKER_TEST_REPORT.txt").write_text(
        result.stdout + result.stderr, encoding="utf-8"
    )
    git(directory, "add", "--intent-to-add", "WORKER_TEST_REPORT.txt")
    patch.write_text(
        process(directory, "git", "diff", "--binary").stdout, encoding="utf-8"
    )


def test_checkout_fixture_is_red_and_patch_passes_the_same_unchanged_test(tmp_path):
    source = tmp_path / "source"
    base_sha = make_checkout_fixture(source)
    initial = source_snapshot(source)
    proposal = tmp_path / "proposal"
    process(tmp_path, "git", "clone", "--quiet", source, proposal)
    patch = tmp_path / "changes.patch"
    reference_patch(proposal, patch)
    verify_checkout_patch(source, base_sha, patch, tmp_path / "verification")
    assert source_snapshot(source) == initial
    assert not git(source, "status", "--porcelain")
    assert run_invoice_test(source).returncode != 0


def test_checkout_handoff_rejects_a_patch_that_changes_the_acceptance_test(tmp_path):
    source = tmp_path / "source"
    base_sha = make_checkout_fixture(source)
    proposal = tmp_path / "proposal"
    process(tmp_path, "git", "clone", "--quiet", source, proposal)
    patch = tmp_path / "tampered.patch"
    reference_patch(proposal, patch)
    test_file = proposal / TEST_PATH
    test_file.write_text(
        test_file.read_text(encoding="utf-8").replace(
            'Decimal("5.00")', 'Decimal("5.0")'
        ),
        encoding="utf-8",
    )
    assert run_invoice_test(proposal).returncode == 0
    patch.write_text(
        process(proposal, "git", "diff", "--binary").stdout, encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="acceptance test must stay unchanged"):
        verify_checkout_patch(source, base_sha, patch, tmp_path / "verification")


def successful_mcp_calls(events):
    calls = []
    for event in events:
        item = event.get("item", {})
        if (
            event.get("type") == "item.completed"
            and item.get("type") == "mcp_tool_call"
            and item.get("status") == "completed"
            and not item.get("error")
        ):
            result = item.get("result")
            if result and not (result.get("isError") or result.get("is_error")):
                record = result.get("structuredContent") or result.get(
                    "structured_content"
                )
                if record is None:
                    record = json.loads(result["content"][0]["text"])
                calls.append((item, record))
    return calls


def assert_worker_trace(record, relative_path, *, checkout=False):
    trace = Path(record["trace_path"])
    assert trace.is_file(), "The Codex trace must survive scratch cleanup."
    events = [
        json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()
    ]
    assert sum(event.get("type") == "thread.started" for event in events) == 1
    calls = successful_mcp_calls(events)
    for tool in ("get_work_brief", "list_skills", "read_skill", "submit_work_result"):
        assert any(item["tool"] == tool for item, _ in calls), (
            f"No successful real Codex MCP call: {tool}"
        )
    assert any(
        item["tool"] == "get_work_brief"
        and result["attempt_id"] == record["attempt"]["id"]
        and result["work_item"] == record["work_item"]
        for item, result in calls
    )
    assert any(
        item["tool"] == "read_skill"
        and item["arguments"] == SKILL
        and result["id"] == SKILL["id"]
        and result["revision"] == SKILL["revision"]
        for item, result in calls
    )
    assert any(
        item["tool"] == "submit_work_result"
        and item["arguments"] == {"relative_path": relative_path}
        and result["id"] == record["artifact"]["id"]
        for item, result in calls
    )
    commands = [
        event["item"]
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "command_execution"
        and event["item"].get("exit_code") == 0
    ]
    assert commands, "The real Codex worker must execute ordinary workspace commands."
    if checkout:
        assert any(
            "unittest" in command.get("command", "")
            and "check_invoice.py" in command.get("command", "")
            for command in commands
        ), "Codex must run the existing test successfully."
        output = "\n".join(command.get("aggregated_output", "") for command in commands)
        assert TEST_NAME in output and "OK" in output, (
            "Codex must expose the existing test's passing output."
        )
    for tool in ("get_work_brief", "list_skills", "read_skill", "submit_work_result"):
        assert any(
            call["tool"] == tool and call["outcome"] == "returned"
            for call in record["calls"]
        ), f"The host audit must retain the successful {tool} call."


@pytest.fixture
def worker_owner(tmp_path):
    """Each invocation is a fresh owner process; none starts an operator session."""
    workspace = tmp_path / "owner"
    workspace.mkdir()
    executable = Path(sysconfig.get_path("scripts")) / "operator"

    def invoke(*args):
        output = process(workspace, executable, *args, timeout=600).stdout
        return json.loads(output)

    return workspace, invoke


@pytest.fixture
def worker_image():
    image = os.environ.get("HARNESS_WORKER_IMAGE")
    assert image, "Set HARNESS_WORKER_IMAGE to the built worker image digest."
    assert "@sha256:" in image or image.startswith("sha256:"), (
        "HARNESS_WORKER_IMAGE must select an exact worker image digest."
    )
    assert shutil.which("docker"), "Docker is required for signed-in worker acceptance."
    return image


def assert_handoff(owner_workspace, invoke, goal, item, attempt_id, image, output):
    record = invoke("work", "show", attempt_id)
    attempt, artifact = record["attempt"], record["artifact"]
    assert record["work_item"] == item
    assert attempt["work_item_id"] == item["id"]
    assert attempt["image_digest"] == image
    assert attempt["exit_code"] == 0
    assert attempt["scratch_cleaned_at"]
    assert not Path(attempt["scratch_path"]).exists()
    assert artifact is not None, (
        f"Worker exited with {attempt['exit_code']} without a saved artifact; "
        f"inspect {record['trace_path']} and the adjacent codex.stderr.log."
    )
    assert artifact["attempt_id"] == attempt_id
    assert artifact["work_item_id"] == item["id"]
    assert artifact["goal_id"] == goal["id"]
    assert artifact["goal_revision"] == goal["revision"]
    assert artifact["operator_id"] == item["operator_id"]
    assert artifact["grant_id"] == attempt["grant_id"]
    retrieved = invoke("work", "artifact", goal["id"], "--output", output)
    assert retrieved == artifact
    assert output.is_file()
    assert hashlib.sha256(output.read_bytes()).hexdigest() == artifact["sha256"]
    assert output.stat().st_size == artifact["size_bytes"]
    current = invoke("goal", "show", goal["id"])
    assert current["revision"] == goal["revision"]
    assert current["status"] == "active"
    with sqlite3.connect(owner_workspace / ".harness/goals.sqlite3") as database:
        assert database.execute("SELECT COUNT(*) FROM operator_runs").fetchone() == (0,)
        assert database.execute("SELECT COUNT(*) FROM work_attempts").fetchone() == (1,)
    return record


@pytest.mark.live
@pytest.mark.worker_city
def test_city_artifact_survives_cleanup_and_is_retrieved_by_goal(
    tmp_path, worker_owner, worker_image
):
    workspace, invoke = worker_owner
    goal = invoke("goal", "create", "--title", "Prepare five Danish city names")
    operator = invoke("register", "City worker")
    brief = (
        "Read the assigned worker-handoff skill. Create cities.txt in the empty "
        "workspace as UTF-8 with exactly these five lines, in this order, and a "
        "final newline: "
        + json.dumps(CITIES, ensure_ascii=False)
        + ". Use your ordinary file and shell tools to create and check the file. "
        "Submit cities.txt through submit_work_result(relative_path)."
    )
    item = invoke(
        "work",
        "create",
        "--goal-id",
        goal["id"],
        "--revision",
        goal["revision"],
        "--operator-id",
        operator["id"],
        "--brief",
        brief,
        "--skill",
        "worker-handoff@1",
    )
    assert item["source_path"] is None and item["base_sha"] is None
    assert item["skills"] == [SKILL]
    attempt_id = f"cities-{uuid4().hex}"
    invoke(
        "work", "start", item["id"], "--attempt-id", attempt_id, "--image", worker_image
    )
    output = tmp_path / "retrieved-cities.txt"
    record = assert_handoff(
        workspace, invoke, goal, item, attempt_id, worker_image, output
    )
    assert output.read_bytes() == ("\n".join(CITIES) + "\n").encode("utf-8")
    assert record["artifact"]["relative_path"] == "cities.txt"
    assert_worker_trace(record, "cities.txt")
    print(
        f"City handoff: attempt={attempt_id} artifact={record['artifact']['id']} "
        f"image={worker_image} cities={','.join(CITIES)} scratch=cleaned "
        f"operator_sessions=0 goal={goal['id']} revision={goal['revision']} status=active"
    )


@pytest.mark.live
@pytest.mark.worker_extended
def test_checkout_worker_patch_passes_the_unchanged_test_after_cleanup(
    tmp_path, worker_owner, worker_image
):
    workspace, invoke = worker_owner
    source = tmp_path / "original-checkout"
    base_sha = make_checkout_fixture(source)
    original = source_snapshot(source)
    goal = invoke("goal", "create", "--title", "Fix invoice quantity totals")
    operator = invoke("register", "Checkout worker")
    brief = (
        "Read the assigned worker-handoff skill and this checkout's README.md. "
        "Fix invoice.py so invoice_total includes each quantity with exact decimal "
        "arithmetic. Keep the existing tests unchanged. The specific test fails at "
        f"the recorded base {base_sha}. Run this exact command: {TEST_COMMAND}. "
        "Save its complete output to WORKER_TEST_REPORT.txt and also print that "
        "output so the execution trace records the passing result. Create the "
        "ordinary patch file changes.patch containing only the invoice.py fix and "
        "WORKER_TEST_REPORT.txt. Use git add --intent-to-add WORKER_TEST_REPORT.txt "
        "then git diff --binary > changes.patch to include the new report. Submit "
        "changes.patch through the same submit_work_result(relative_path) tool."
    )
    item = invoke(
        "work",
        "create",
        "--goal-id",
        goal["id"],
        "--revision",
        goal["revision"],
        "--operator-id",
        operator["id"],
        "--brief",
        brief,
        "--skill",
        "worker-handoff@1",
        "--source",
        source,
        "--base-sha",
        base_sha,
    )
    assert item["base_sha"] == base_sha
    assert item["source_path"] == str(source)
    assert item["skills"] == [SKILL]
    attempt_id = f"checkout-{uuid4().hex}"
    invoke(
        "work", "start", item["id"], "--attempt-id", attempt_id, "--image", worker_image
    )
    patch = tmp_path / "retrieved-changes.patch"
    record = assert_handoff(
        workspace, invoke, goal, item, attempt_id, worker_image, patch
    )
    assert record["artifact"]["base_sha"] == base_sha
    assert record["artifact"]["relative_path"] == "changes.patch"
    verify_checkout_patch(source, base_sha, patch, tmp_path / "review-checkout")
    assert source_snapshot(source) == original
    assert git(source, "rev-parse", "HEAD") == base_sha
    assert not git(source, "status", "--porcelain")
    assert run_invoice_test(source).returncode != 0
    assert_worker_trace(record, "changes.patch", checkout=True)
    print(
        f"Checkout handoff: attempt={attempt_id} artifact={record['artifact']['id']} "
        f"image={worker_image} base_sha={base_sha} test={TEST_PATH} "
        "baseline=FAIL unchanged_test=PASS original_checkout=intact scratch=cleaned "
        f"operator_sessions=0 goal={goal['id']} revision={goal['revision']} status=active"
    )
