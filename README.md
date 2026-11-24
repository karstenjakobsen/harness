# Harness Operator

`operator ask` sends one message to Codex and prints its reply. Use it to read
relevant workspace files, think through a goal, or suggest a small next step.
The operator treats goal changes as proposals. Each invocation starts a fresh
conversation using the Codex read-only sandbox. It uses your existing Codex
sign-in and skips your personal Codex configuration.

## Setup

Install `uv`, GNU Make, and a Codex CLI that supports `codex exec` with
`--ephemeral` and `--ignore-user-config`.

```sh
make setup
uv run --package harness-operator operator ask "List goals."
uv run --package harness-operator operator ask "Read goals/POC.md and suggest one small next step."
```

`make setup` uses `uv` to create `.venv` with Python 3.14. You can run
`harness-operator` or `operator` directly after activating the virtual environment.

Run `operator ask` to type a message at the prompt, or pipe a message into the
same command. Use `make check` to run the Ruff lint and format checks.

## Sign in to Codex

To connect Harness to your ChatGPT account, enable device code login in your
ChatGPT security settings or workspace permissions. Then run

```sh
uv run --package harness-operator operator register
```

Open the link shown in the terminal and enter the one-time code. Keep the
terminal open until Codex confirms sign-in. `operator ask` uses that sign-in.
Use `codex login status` to check it. [Codex authentication guide](https://developers.openai.com/codex/auth#login-on-headless-devices)

## Saved goals

`operator ask` starts the local `harness_mcp` server over stdio. The server
uses `harness_api` to open `.harness/goals.sqlite3` in the working directory.
On first run, the API applies its SQLite migrations and creates a local user
with an empty goal list.

The schema gives each goal a stable ID, an owner, and a status. Goal revisions
store titles and outcomes. Operator assignments have their own history, and
SQLite allows one open assignment per goal.

`harness_mcp` exposes the read-only `list_goals` tool. It returns the local
user's goal IDs, statuses, latest revision numbers and titles, and current
operators. The optional `status` argument accepts `draft`, `active`, `paused`,
`completed`, or `revoked`. Try `operator ask "List active goals."`

### Create a draft goal

```sh
uv run --package harness-operator operator goal create "Keep the sample config file at mode 0600."
```

Codex drafts the outcome, success criteria, and measurement plan from your
request. It considers duration separately from how to judge success. In this
example, the goal is standing and success is an objective permissions check.

The command saves a draft, prints its ID, and asks a focused question if it
needs clarification. Unclear details can stay open. SQLite keeps your original
request and any question alongside the first revision. View the draft with
`operator ask "List draft goals."`

## FastAPI

Run `make api` from the workspace root to serve the goal API. Open
[the API docs](http://127.0.0.1:8000/docs) to try the endpoints.

In a second terminal, list goals directly over HTTP. This command requires no
sign-in.

```sh
uv run --package harness-operator harness-operator api goals list
```

The command uses `http://127.0.0.1:8000` by default. Use `HARNESS_API_URL` or
`harness-operator api --url URL goals list` to point it at another instance.

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/goals` | List goals, optionally filtered by `status` |
| `POST` | `/goals` | Create a draft |
| `GET` | `/goals/{goal_id}` | Read the latest definition |
| `PATCH` | `/goals/{goal_id}` | Revise the title or desired outcome |
| `DELETE` | `/goals/{goal_id}` | Hide the goal and close its current assignment while preserving history |

The `harness_api` package follows MVC. The model owns SQLite and goal rules,
the FastAPI controllers handle requests, and the Pydantic views define the JSON
contract. FastAPI, `goal create`, and the MCP tools call the shared Python goal
model. The `api goals list` command reads from FastAPI over HTTP. Start FastAPI
and run the Codex-backed commands from the same workspace to use the same
SQLite database.

Use `make test` to run pytest. The model, HTTP, and MCP tests use temporary
SQLite databases.
