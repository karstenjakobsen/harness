import os
import stat
import subprocess
import sys
import tomllib
from itertools import pairwise
from pathlib import Path

import pytest

from harness_operator import ask_codex


def test_ask_connects_codex_to_workspace_mcp(monkeypatch, tmp_path):
    workspace = tmp_path / 'workspace "with quotes" 🌱'
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    def run(command, **options):
        overrides = [value for flag, value in pairwise(command) if flag == "-c"]
        config = tomllib.loads("\n".join(overrides))
        assert config["mcp_servers"]["harness_mcp"] == {
            "command": sys.executable,
            "args": ["-P", "-m", "harness_mcp.server"],
            "cwd": str(workspace),
            "required": True,
        }
        assert "list_goals tool" in options["input"]
        assert options["input"].endswith("\nList active goals.")
        return subprocess.CompletedProcess(command, returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert ask_codex("List active goals.") == 0


def test_trace_is_private_exclusive_and_separate_from_reply(
    monkeypatch, tmp_path, capsys
):
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
