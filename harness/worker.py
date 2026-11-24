import asyncio
import base64
import json
import os
import sys
from pathlib import Path


def codex(prompt: str):
    home = Path(os.environ["CODEX_HOME"])
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    auth = Path("/run/secrets/codex-auth")
    if auth.exists():
        (home / "auth.json").symlink_to(auth)
    args = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--disable",
        "shell_tool",
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "multi_agent",
        "-c",
        'web_search="disabled"',
        "-c",
        'approval_policy="never"',
        "-c",
        f"mcp_servers.workspace.url={json.dumps(os.environ['WORKER_MCP_URL'])}",
        "-c",
        'mcp_servers.workspace.bearer_token_env_var="RUN_TOKEN"',
        "-c",
        "mcp_servers.workspace.required=true",
        "-c",
        'mcp_servers.workspace.default_tools_approval_mode="approve"',
        "--",
        prompt,
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    task = json.loads(base64.b64decode(os.environ["RUN_TASK_B64"]))
    if sys.argv[1] == "codex":
        codex(task["prompt"])
    else:
        from harness.hello_file import fixture_worker

        asyncio.run(fixture_worker(sys.argv[1], task["outcome"]))
