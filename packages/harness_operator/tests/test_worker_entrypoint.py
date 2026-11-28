import runpy
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[3] / "dev/worker/codex_worker.py"


@pytest.fixture
def codex_worker(monkeypatch):
    monkeypatch.syspath_prepend(str(ENTRYPOINT.parent))
    return runpy.run_path(str(ENTRYPOINT))


def test_entrypoint_uses_one_generic_codex_workspace_session(codex_worker):
    environment = {
        "HARNESS_WORKER_ATTEMPT_ID": "selected-attempt",
        "HARNESS_WORKER_TOKEN": "runtime-only-credential",
        "HARNESS_WORKER_MCP_URL": "http://127.0.0.1:8001/mcp",
    }
    arguments = codex_worker["command"]("selected-attempt", environment)
    assert arguments[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "--json" in arguments and "--skip-git-repo-check" in arguments
    assert arguments[arguments.index("--sandbox") + 1] == "danger-full-access"
    assert arguments[arguments.index("-C") + 1] == "/workspace"
    assert 'mcp_servers.worker.bearer_token_env_var="HARNESS_WORKER_TOKEN"' in arguments
    assert "runtime-only-credential" not in " ".join(arguments)
    instruction = arguments[-1]
    assert instruction == codex_worker["INSTRUCTION"]
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
def test_entrypoint_rejects_invalid_runtime_assignment(codex_worker, updates):
    environment = {
        "HARNESS_WORKER_ATTEMPT_ID": "selected-attempt",
        "HARNESS_WORKER_TOKEN": "runtime-only-credential",
        "HARNESS_WORKER_MCP_URL": "http://127.0.0.1:8001/mcp",
    }
    with pytest.raises(ValueError):
        codex_worker["command"]("selected-attempt", environment | updates)
