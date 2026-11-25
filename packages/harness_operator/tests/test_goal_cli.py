import json

from click.testing import CliRunner

from harness_api import DATABASE_PATH
from harness_operator import cli


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
