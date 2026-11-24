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
| `operator ask --trace-file PATH [MESSAGE]` | Saves the Codex JSON event stream to a new file and prints the final reply. |
| `harness-operator goal create [MESSAGE]` | Asks Codex to draft a goal and prints its saved ID, duration, assessment type, and any clarification question. |
| `operator api goals create --title TITLE [--parent ID] [OPTIONS]` | Saves an active goal and prints its ID, revision, and definition as JSON. |
| `operator api goals revise ID [OPTIONS]` | Appends a revision when a definition field changes. |
| `operator api goals complete ID --revision N` | Records completion with either `--confirmation TEXT` or `--reference REF`. |
| `operator api goals show ID [--tree or --history]` | Prints the latest goal, the subtree with current evidence, or one goal’s revision history. |
| `harness-operator api goals list [--json]` | Calls FastAPI directly and lists saved goals. `--json` prints the complete API response. No sign-in is required. |

`ask` and message-based `goal create` use the Codex sign-in. Supply a quoted message, pipe it
on standard input, or omit it to type at the terminal prompt. Add `--help` to
any command or group to see its options.

```sh
harness-operator register
harness-operator ask "List draft goals."
harness-operator goal create "Keep the sample config file at mode 0600."
```

`operator api goals create`, `revise`, `complete`, and `show` use the local
workspace database. Start `make api` in a separate terminal for `operator api goals list`.
The API defaults to `http://127.0.0.1:8000`. Use `HARNESS_API_URL` or set
`--url` on the `api` group to list goals from another instance.

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
| `make test` | Runs the offline pytest suite. |
| `make test-live` | Runs the signed-in CLI and MCP acceptance test. |
| `uv run --package harness-mcp harness_mcp` | Starts the standalone MCP server over stdio for an MCP client. |
