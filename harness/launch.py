import os


def worker_env(worker: str, token: str) -> tuple[dict[str, str], str | None]:
    env = {"RUN_TOKEN": token, "WORKER_MCP_URL": "http://harness:8000/worker/mcp"}
    if worker != "codex":
        return env, None
    if auth_file := os.getenv("CODEX_AUTH_FILE"):
        return env, auth_file
    if key := os.getenv("CODEX_API_KEY"):
        env["CODEX_API_KEY"] = key
        return env, None
    raise ValueError("Set CODEX_AUTH_FILE or CODEX_API_KEY for the Codex worker")
