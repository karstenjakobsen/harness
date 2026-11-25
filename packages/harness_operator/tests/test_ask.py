import json
import os
import stat
import subprocess
import sys
import tomllib
from itertools import pairwise
from pathlib import Path

import pytest

from harness_api import GoalAPI, OperatorAPI
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
