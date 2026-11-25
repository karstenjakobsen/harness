import json
import sys

from click.testing import CliRunner

from harness_api import DATABASE_PATH
from harness_operator import cli, main


def test_removed_api_group_is_unknown(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["api", "--help"])
    assert result.exit_code == 2
    assert "No such command 'api'" in result.stderr
    assert not DATABASE_PATH.exists()


def test_workspace_goal_commands_read_and_write_the_same_goal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    def goal(*args):
        result = runner.invoke(cli, ["goal", *args])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    created = goal("create", "--title", "Review notes")
    goal_id = str(created["id"])
    assert goal("show", goal_id) == created
    revised = goal("revise", goal_id, "--title", "Review all notes")
    revision = str(revised["revision"])
    decision = goal(
        "complete", goal_id, "--revision", revision, "--confirmation", "Reviewed"
    )
    assert goal("show", goal_id)["completion"] == decision
    [summary] = goal("list")
    assert (summary["id"], summary["title"], summary["status"]) == (
        created["id"],
        revised["title"],
        "completed",
    )


def test_cli_observations_revision_selection_and_completion_citations(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)

    def call(*args, code=0):
        monkeypatch.setattr(sys, "argv", ["operator", "goal", *map(str, args)])
        assert main() == code
        captured = capsys.readouterr()
        return captured.err if code else json.loads(captured.out)

    goal = call(
        "create",
        "--title",
        "Food log",
        "--target-distinct-dates",
        7,
        "--window-start",
        "2026-11-23",
        "--duration-days",
        7,
    )
    goal_id = goal["id"]
    args = (
        "observe",
        goal_id,
        "--confirmation",
        "Logged meals",
        "--reported-date",
        "2026-11-23",
    )
    first = call(*args, "--retry-key", "a")
    assert call(*args, "--retry-key", "a") == first
    second = call(*args, "--retry-key", "b")
    call("revise", goal_id, "--target-distinct-dates", 14)
    for revision, target in ((1, 7), (2, 14)):
        progress = call("progress", goal_id, "--revision", revision)
        assert (progress["count"], progress["target"], progress["status"]) == (
            1,
            target,
            "active",
        )
        assert progress["evidence"] == [first, second]
    cite = (
        "--evidence-id",
        first["evidence_id"],
        "--evidence-id",
        second["evidence_id"],
    )
    assert "Stale revision" in call(
        "complete", goal_id, "--revision", 1, "--reference", "app:log", *cite, code=1
    )
    saved = call("complete", goal_id, "--revision", 2, "--reference", "app:log", *cite)
    assert saved["evidence_ids"] == [first["evidence_id"], second["evidence_id"]]
    assert saved["evidence_kind"] == "owner_supplied_reference"
