import json
import shutil
import sys

import pytest

from harness_api import WorkAPI, WorkStorageError
from harness_operator import main


@pytest.fixture
def saved_handoff(monkeypatch, tmp_path, capsys):
    workspace = tmp_path / "owner"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    def invoke(*args, error=None):
        monkeypatch.setattr(sys, "argv", ["operator", *map(str, args)])
        code = main()
        captured = capsys.readouterr()
        if error is not None:
            assert code == 1 and error in captured.err
            assert not captured.out
            return
        assert code == 0, captured.err
        return json.loads(captured.out)

    goal = invoke("goal", "create", "--title", "Prepare a file")
    operator = invoke("register", "Builder")
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
        "Create a deliverable.",
        "--skill",
        "worker-handoff@1",
    )
    api = WorkAPI()
    api.create_attempt("cli-handoff", item["id"])
    api.grant_attempt("cli-handoff", "fixture-credential")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    content = b"retained file\n"
    (scratch / "result.txt").write_bytes(content)
    api.set_scratch("cli-handoff", scratch)
    artifact = api.submit_work_result("cli-handoff", "fixture-credential", "result.txt")
    shutil.rmtree(scratch)
    api.mark_scratch_cleaned("cli-handoff")
    return invoke, goal, item, artifact, content


def test_work_commands_use_current_workspace_and_preserve_existing_output(
    saved_handoff, monkeypatch, tmp_path
):
    invoke, goal, item, artifact, content = saved_handoff
    record = invoke("work", "show", "cli-handoff")
    assert record["work_item"] == item
    assert record["artifact"] == artifact
    assert record["attempt"]["scratch_cleaned_at"] is not None
    output = tmp_path / "owner-result.txt"
    assert invoke("work", "artifact", goal["id"], "--output", output) == artifact
    assert output.read_bytes() == content
    invoke("work", "artifact", goal["id"], "--output", output, error="File exists")
    assert output.read_bytes() == content

    other = tmp_path / "other-owner"
    other.mkdir()
    monkeypatch.chdir(other)
    invoke("work", "show", "cli-handoff", error="Work attempt was not found")
    missing = other / "result.txt"
    invoke(
        "work", "artifact", goal["id"], "--output", missing, error="Goal was not found"
    )
    assert not missing.exists()


def test_artifact_read_failure_does_not_create_empty_owner_file(
    saved_handoff, monkeypatch, tmp_path
):
    invoke, goal, _, _, _ = saved_handoff
    output = tmp_path / "unavailable-result.txt"

    def unavailable(self, artifact_id):
        raise WorkStorageError()

    monkeypatch.setattr(WorkAPI, "read_artifact_bytes", unavailable)
    invoke(
        "work",
        "artifact",
        goal["id"],
        "--output",
        output,
        error="database is unavailable",
    )
    assert not output.exists()
