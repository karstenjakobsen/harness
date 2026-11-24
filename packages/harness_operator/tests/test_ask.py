import subprocess
import sys
import tomllib
from itertools import pairwise

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
