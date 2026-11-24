import asyncio
import json
import os
import sys
from pathlib import Path

from harness.client import call, connect
from harness.evidence import EXPECTED, TASK


async def fixture(mode: str):
    if mode == "fixture-missing":
        print(json.dumps({"fixture": mode, "action": "exit without writing"}))
        return
    content = {"fixture-write": EXPECTED, "fixture-wrong": EXPECTED + "\n"}[mode]
    async with connect(os.environ["WORKER_MCP_URL"], os.environ["RUN_TOKEN"]) as session:
        for name, args in [
            ("write_file", {"path": "result.txt", "content": content}),
            ("read_file", {"path": "result.txt"}),
        ]:
            print(
                json.dumps(
                    {"fixture": mode, "tool": name, "result": await call(session, name, **args)}
                )
            )


def codex():
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
        TASK,
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    if sys.argv[1] == "codex":
        codex()
    else:
        asyncio.run(fixture(sys.argv[1]))
