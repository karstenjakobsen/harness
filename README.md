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

## Workspace users and operators

`UserAPI` and `OperatorAPI` manage accounts in the same SQLite database as
`GoalAPI`. Each workspace starts with the protected system user `admin`.
Register a named operator for a user with `--user`, or omit the option to use
`admin`. For example, in a new workspace the first operator receives ID 1.

```sh
operator user create sam --name "Sam Lee"
operator register Planner --user sam
operator list --user sam
operator unregister 1
operator user delete sam
```

Unregistering an operator timestamps its record and releases its open goal
assignments. After a user's last operator is unregistered, the user can be
soft-deleted. Ownership and assignment history survive both operations, and
deleted user IDs stay reserved. See the [CLI command catalog](CATALOG.md).

## Saved goals

`operator ask` starts the local `harness_mcp` server over stdio. The server
uses `harness_api` to open `.harness/goals.sqlite3` in the working directory.
On first run, the API creates the database from the full schema snapshot in
`001_initial.sql`. Workspaces on schema versions 1 through 5 upgrade in place
to version 6. Each existing completion statement receives a stable evidence ID.
For pre-v5 workspaces the upgrade renames the original `local` owner to `admin`, including its goal
and operator ownership and completion attribution. If a separate `admin`
user already exists, the upgrade stops so the two identities can be resolved.

The schema gives each goal a stable ID, an owner, and a status. Goal revisions
store titles and outcomes. Operator assignments have their own history, and
SQLite allows one open assignment per goal.

`harness_mcp` exposes the read-only `list_goals` tool. It returns the workspace
administrator's goal IDs, statuses, latest revision numbers and titles, and current
operators. The optional `status` argument accepts `draft`, `active`, `paused`,
`completed`, or `revoked`. Try `operator ask "List active goals."`
The Python API raises `GoalValidationError` for unknown status filters and for
non-text values in goal text fields. The corresponding HTTP requests return 422.
For questions about a plan, the operator calls `get_goal_tree` with the goal ID
to read each descendant’s current requirements, status, and completion evidence.
For progress it calls `get_goal_progress` and explains the model’s assessment
using the returned evidence IDs, dates and provenance.

### Create a draft goal

```sh
uv run --package harness-operator operator goal create "Keep the sample config file at mode 0600."
```

Codex drafts the outcome, success criteria, and measurement plan from your
request. `duration` describes a one-time result or a standing goal.
`duration_days` records the time window when supplied. For example, “Track food
for seven days” saves a window of 7 days. An unspecified window is stored as null.

The command saves a draft, prints its ID, and asks a focused question if it
needs clarification. Unclear details can stay open. SQLite keeps your original
request and any question alongside the first revision. View the draft with
`operator ask "List draft goals."`

### Manage workspace goals

The commands below call the workspace’s Python goal API directly. They work
with FastAPI stopped. Explicit creation saves an active goal and prints JSON
with its ID and revision.
Use the returned IDs in later commands. For example, if the parent ID is 1 and
the new child ID is 2, the following commands revise and complete the child.

```sh
operator goal create --title "Lose 20 lb"
operator goal create --parent 1 --title "Track food" --duration-days 7 \
  --success-criteria "A food entry each day" --measurement-plan "Review the log"
operator goal revise 2 --duration-days 14
operator goal complete 2 --revision 2 --confirmation "I reviewed all fourteen entries."
operator goal show 2 --history
operator goal show 1 --tree
operator goal list
```

Use `--reference REF` to record an owner-supplied app reference. Repeating the
same completion returns the saved decision. Changing a completed definition
reopens that goal and keeps the earlier evidence in its revision history.

### Record progress while a goal is active

In a fresh workspace, these commands create goal 1 and record two reports about Monday.

```sh
operator goal create --title "Food log" --target-distinct-dates 7
operator goal observe 1 --reported-date 2026-11-23 --confirmation "I logged lunch" --retry-key lunch
operator goal observe 1 --reported-date 2026-11-23 --confirmation "I logged dinner" --retry-key dinner
operator goal progress 1
operator goal revise 1 --target-distinct-dates 14
operator ask "What progress have I made on my food log, and how do we know?"
```

Both confirmations support one distinct date. Progress changes from 1/7 to 1/14,
and the goal stays active. `operator goal progress 1 --revision 1` evaluates the
seven-date rule with all evidence available now. Use `operator goal show 1 --history`
to see when the confirmations arrived and when the target changed. [Command catalog](CATALOG.md#workspace-goals)

## FastAPI

Run `make api` from the workspace root to serve the workspace API. Open
[the API docs](http://127.0.0.1:8000/docs) to try the endpoints.

Use `operator goal list` to list the current workspace’s goals. To list goals
from a running HTTP server, request its `/goals` endpoint directly.

```sh
curl --fail --silent --show-error http://127.0.0.1:8000/goals
```

| Method | Path | Operation |
| --- | --- | --- |
| `GET`, `POST` | `/users` | List users or create one with `id` and optional `display_name` |
| `GET`, `PATCH`, `DELETE` | `/users/{user_id}` | Read a user, update their `display_name`, or soft-delete them. Deleting `admin` or a registered operator’s owner returns HTTP 409 |
| `GET`, `POST` | `/operators` | List registered operators, optionally filtered by `owner_user_id`, or register one with `name`, optional `owner_user_id`, and optional `mission` |
| `GET`, `DELETE` | `/operators/{operator_id}` | Read a registered operator or unregister it and release its open assignments |
| `GET` | `/goals` | List goals, optionally filtered by `status` |
| `POST` | `/goals` | Create revision 1 with `status` set to `draft` (default) or `active` |
| `GET` | `/goals/{goal_id}` | Read the latest definition |
| `PATCH` | `/goals/{goal_id}` | Revise the title, outcome, timing, success criteria, or verification method |
| `POST` | `/goals/{goal_id}/observations` | Record a confirmation or reference with a retry key and optional reported date. The HTTP caller is unattributed |
| `GET` | `/goals/{goal_id}/progress` | Assess the optional `revision` with evidence available now |
| `GET` | `/goals/{goal_id}/history` | Read revision timestamps, submissions and saved completions |
| `POST` | `/goals/{goal_id}/completion` | Complete the current `revision` with a confirmation or reference and optional `evidence_ids` |
| `DELETE` | `/goals/{goal_id}` | Soft-delete a leaf and close its assignment. A parent with visible children returns HTTP 409 |

An identical observation retry returns HTTP 200 with the original evidence ID.
Reusing its key with different report content returns 409. A stale completion
revision, conflicting completion retry, or citation from another goal returns 422.

The `harness_api` package follows MVC. `GoalAPI`, `UserAPI`, and `OperatorAPI`
own persistence and business rules. The FastAPI controllers call those models,
and Pydantic views define the HTTP request and response bodies. Workspace CLI
commands call the same Python models. Start FastAPI and run the CLI from the
same workspace to use the same SQLite database.

Run `make test` for the offline suite and `make check` for lint and formatting.
Run `make test-live` separately with Codex signed in. It populates temporary workspaces through
the CLI, verifies plan and progress reads through MCP, and checks the replies.
Test teardown removes the workspace and its database even if an assertion fails.
