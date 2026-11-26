import json
import os
import stat
import subprocess
import sys
import tomllib
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest

from harness_api import GoalAPI, OperatorAPI, RunNotFoundError, read_skill_catalog
from harness_operator import ask_codex, main


def test_ask_connects_codex_to_workspace_mcp(monkeypatch, tmp_path):
    workspace = tmp_path / 'workspace "with quotes" 🌱'
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    def run(command, **options):
        overrides = [value for flag, value in pairwise(command) if flag == "-c"]
        config = tomllib.loads("\n".join(overrides))
        assert config["mcp_servers"]["harness_mcp"] == {
            "command": sys.executable,
            "args": ["-P", "-m", "harness_mcp.server", "--run-id", "1"],
            "cwd": str(workspace),
            "required": True,
        }
        assert "list_goals tool" in options["input"]
        assert options["input"].endswith("\nList active goals.")
        assert GoalAPI().get_run(1)["outcome"] == "unfinished"
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert ask_codex("List active goals.") == 0
    saved = GoalAPI().get_run(1)
    assert saved["mode"] == "advisory" and saved["outcome"] == "succeeded"
    assert saved["operator_id"] is None and saved["completion_grant_id"] is None
    assert saved["finished_at"] is not None
    assert saved["started_at"] <= saved["finished_at"] and saved["calls"] == []


def test_trace_is_private_exclusive_and_separate_from_reply(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)

    def run(command, **options):
        options["stdout"].write('{"type":"thread.started"}\n')
        reply = Path(command[command.index("--output-last-message") + 1])
        reply.write_text("Goal is open.\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    trace = tmp_path / "ask.jsonl"
    previous_umask = os.umask(0o022)
    try:
        assert ask_codex("List goals.", trace) == 0
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(trace.stat().st_mode) == 0o600
    assert capsys.readouterr().out == "Goal is open.\n"
    with pytest.raises(FileExistsError):
        ask_codex("List goals.", trace)
    assert trace.read_text(encoding="utf-8") == '{"type":"thread.started"}\n'
    failed = GoalAPI().get_run(2)
    assert failed["outcome"] == "failed" and failed["calls"] == []


def test_cli_grants_binds_and_withdraws_completion(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    goals = GoalAPI()
    parent = goals.create_goal("Parent")
    child = goals.create_goal("Child", parent_goal_id=parent["id"])
    operator = OperatorAPI().register_operator("Reviewer")
    monkeypatch.setattr(
        sys,
        "argv",
        ["operator", "goal", "grant-completion", str(child["id"]), str(operator["id"])],
    )
    assert main() == 0
    grant = json.loads(capsys.readouterr().out)
    assert grant["goal_id"] == child["id"] and grant["operator_id"] == operator["id"]
    launched = []

    def run(command, **options):
        overrides = [value for flag, value in pairwise(command) if flag == "-c"]
        config = tomllib.loads("\n".join(overrides))
        server = config["mcp_servers"]["harness_mcp"]
        assert server["args"] == [
            "-P",
            "-m",
            "harness_mcp.server",
            "--run-id",
            "1",
            "--completion-grant",
            str(grant["id"]),
        ]
        assert server["tools"] == {"complete_goal": {"approval_mode": "approve"}}
        assert command[command.index("--ask-for-approval") + 1] == "never"
        assert command[command.index("--sandbox") + 1] == "read-only"
        assert f"completion of subgoal {child['id']}" in options["input"]
        saved = GoalAPI().get_run(1)
        assert saved["mode"] == "delegated" and saved["operator_id"] == operator["id"]
        assert saved["completion_grant_id"] == grant["id"]
        launched.append(command)
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    ask_args = ["operator", "ask", "--completion-grant", str(grant["id"]), "Review."]
    monkeypatch.setattr(sys, "argv", ask_args)
    assert main() == 0
    monkeypatch.setattr(
        sys, "argv", ["operator", "goal", "withdraw-completion", str(grant["id"])]
    )
    assert main() == 0
    trace = tmp_path / "denied.jsonl"
    monkeypatch.setattr(
        sys, "argv", [*ask_args[:-1], "--trace-file", str(trace), ask_args[-1]]
    )
    assert main() == 1
    assert "inactive" in capsys.readouterr().err and len(launched) == 1
    assert not trace.exists()


def test_launcher_records_nonzero_exit_and_start_failure(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def run(command, **options):
        if options["input"].endswith("missing"):
            raise FileNotFoundError("codex")
        return subprocess.CompletedProcess(command, returncode=7)

    monkeypatch.setattr(subprocess, "run", run)
    assert ask_codex("Review") == 7
    with pytest.raises(FileNotFoundError):
        ask_codex("missing")
    for run_id in (1, 2):
        saved = GoalAPI().get_run(run_id)
        assert saved["outcome"] == "failed" and saved["finished_at"] is not None


@pytest.mark.parametrize("action", ["create_goal", "create_subgoal", "revise_goal"])
def test_cli_binds_one_definition_grant_and_approves_its_tool(
    action, monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    goals = GoalAPI()
    operator_id = OperatorAPI().register_operator("Planner")["id"]

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["operator", *map(str, args)])
        return main()

    if action == "create_goal":
        assert invoke("goal", "grant-create", "--help") == 0
        help_text = " ".join(capsys.readouterr().out.split())
        assert (
            "This operator may create top-level goals in this workspace until you withdraw the grant."
            in help_text
        )
        goal_id = None
        assert invoke("goal", "grant-create", operator_id) == 0
    else:
        goal_id = goals.create_goal("Library")["id"]
        command = "grant-subgoals" if action == "create_subgoal" else "grant-revision"
        assert invoke("goal", command, goal_id, operator_id) == 0
    grant = json.loads(capsys.readouterr().out)
    assert grant == {
        "id": grant["id"],
        "action": action,
        "operator_id": operator_id,
        "goal_id": goal_id,
    }

    def run(command, **options):
        overrides = [value for flag, value in pairwise(command) if flag == "-c"]
        server = tomllib.loads("\n".join(overrides))["mcp_servers"]["harness_mcp"]
        assert server["args"][-4:] == [
            "--run-id",
            "1",
            "--definition-grant",
            str(grant["id"]),
        ]
        assert server["tools"] == {action: {"approval_mode": "approve"}}
        assert action in options["input"]
        assert goals.get_run(1)["definition_grant"] == grant
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert invoke("ask", "--definition-grant", grant["id"], "Save the definition.") == 0
    assert (
        invoke(
            "ask", "--definition-grant", grant["id"], "--completion-grant", 1, "Review."
        )
        == 2
    )
    assert invoke("goal", "withdraw-definition-grant", grant["id"]) == 0
    assert json.loads(capsys.readouterr().out) == grant
    assert invoke("ask", "--definition-grant", grant["id"], "Save the definition.") == 1


def test_catalog_conflict_stops_ask_before_starting_a_run(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    catalog = read_skill_catalog()
    goals = GoalAPI()
    goals.skills.import_catalog(catalog)
    changed = replace(
        catalog.sources[0], instructions="Changed without a revision bump"
    )
    monkeypatch.setattr(
        "harness_operator.codex.read_skill_catalog",
        lambda: replace(catalog, sources=(changed, *catalog.sources[1:])),
    )
    monkeypatch.setattr(sys, "argv", ["operator", "ask", "Propose a plan"])
    assert main() == 1
    assert "Bump its revision" in capsys.readouterr().err
    with pytest.raises(RunNotFoundError):
        goals.get_run(1)
