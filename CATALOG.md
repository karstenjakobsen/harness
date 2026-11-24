# CLI command catalog

Run these commands from the workspace root after `make setup`. Activate the
Python 3.14 virtual environment with `source .venv/bin/activate`, or prefix an
operator command with `uv run --package harness-operator`. `operator` is an
alias for `harness-operator`.

## Operator commands

| Command | What it does |
| --- | --- |
| `harness-operator register` | Starts Codex device sign-in and prints a verification link and one-time code. |
| `harness-operator ask [MESSAGE]` | Sends a message to Codex and prints its reply. |
| `harness-operator goal create [MESSAGE]` | Saves a draft goal and prints its ID, duration, assessment type, and any clarification question. |
| `harness-operator api goals list [--json]` | Calls FastAPI directly and lists saved goals. `--json` prints the complete API response. No sign-in is required. |

`ask` and `goal create` use the Codex sign-in. Supply a quoted message, pipe it
on standard input, or omit it to type at the terminal prompt. Add `--help` to
any command or group to see its options.

```sh
harness-operator register
harness-operator ask "List draft goals."
harness-operator goal create "Keep the sample config file at mode 0600."
```

Start `make api` in a separate terminal before listing goals through FastAPI.
The API defaults to `http://127.0.0.1:8000`. Use `HARNESS_API_URL` or set
`--url` on the `api` group to point at another instance.

```sh
harness-operator api goals list
harness-operator api goals list --json
harness-operator api --url http://127.0.0.1:9000 goals list
```

## Workspace commands

| Command | What it does |
| --- | --- |
| `make setup` | Installs the workspace packages into `.venv` using `uv`. |
| `make api` | Starts FastAPI at `http://127.0.0.1:8000`. |
| `make check` | Runs Ruff lint and format checks. |
| `make format` | Formats files with Ruff. |
| `make test` | Runs the pytest suite. |
| `uv run --package harness-mcp harness_mcp` | Starts the standalone MCP server over stdio for an MCP client. |
