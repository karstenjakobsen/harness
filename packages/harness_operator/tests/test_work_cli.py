import json
import shutil
import sqlite3
import sys
from contextlib import closing

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
    api.record_launch("cli-handoff", "historical-container", "sha256:" + "a" * 64)
    api.record_exit("cli-handoff", 0)
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
    assert record["attempt"]["container_id"] == "historical-container"
    assert record["attempt"]["exit_code"] == 0
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


@pytest.mark.parametrize("commit_during_read", [False, True])
def test_show_uses_one_snapshot_while_a_submission_commits(
    saved_handoff, monkeypatch, tmp_path, commit_during_read
):
    invoke, _, item, _, _ = saved_handoff
    writer = WorkAPI()
    attempt_id = "concurrent-inspection"
    writer.create_attempt(attempt_id, item["id"])
    scratch = tmp_path / "inspection-scratch"
    scratch.mkdir()
    (scratch / "result.txt").write_text("Concurrent result")
    writer.set_scratch(attempt_id, scratch)
    writer.grant_attempt(attempt_id, "inspection-credential")
    with closing(sqlite3.connect(writer.database_path, autocommit=True)) as db:
        db.execute("PRAGMA journal_mode = WAL")

    committed = []

    def submit():
        if not committed:
            committed.append(
                writer.submit_work_result(
                    attempt_id, "inspection-credential", "result.txt"
                )
            )

    class InspectionConnection(sqlite3.Connection):
        def close(self):
            super().close()
            if not commit_during_read:
                submit()

    def before_query(statement):
        if statement.startswith("SELECT * FROM worker_calls"):
            submit()

    connect = sqlite3.connect

    def observed_connection(database, **kwargs):
        if "mode=ro" in str(database):
            kwargs["factory"] = InspectionConnection
        connection = connect(database, **kwargs)
        if commit_during_read and "mode=ro" in str(database):
            connection.set_trace_callback(before_query)
        return connection

    # Commit through the public model immediately after the first read connection
    # closes or while it reads calls. Independent reads would mix the old attempt
    # with the new audit. WAL allows the writer to commit during a read snapshot.
    monkeypatch.setattr(sqlite3, "connect", observed_connection)
    before = invoke("work", "show", attempt_id)
    assert committed
    assert before["artifact"] is None
    assert before["attempt"]["artifact_id"] is None
    assert before["calls"] == []
    after = invoke("work", "show", attempt_id)
    assert after == writer.get_attempt_details(attempt_id)
    assert after["artifact"] == committed[0]
    assert after["attempt"]["artifact_id"] == committed[0]["id"]
    assert after["calls"][0]["artifact_id"] == committed[0]["id"]
