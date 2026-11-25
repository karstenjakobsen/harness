# CLI command catalog

Run `make setup` from the repository root, then activate the environment with
`source .venv/bin/activate`. This catalog uses `operator` throughout.
`harness-operator` is an equivalent executable. From the repository root you
can also run commands with `uv run --package harness-operator operator`.
Add `--help` to any command or group to see its options.

## Codex

| Command | What it does |
| --- | --- |
| `operator register` | Starts Codex device sign-in and displays the verification link and one-time code. |
| `operator ask [--trace-file PATH] [MESSAGE]` | Asks Codex a question and prints its reply. The optional flag saves the Codex event stream to a new file. |

## Workspace users and operators

These commands use the current workspace database and print JSON. Every operator
record has one owner. The default owner is the protected system user `admin`.
See how each entry point determines the target, owner and caller in [Identity and attribution](TERMINOLOGY.md#identity-and-attribution).

| Command | What it does |
| --- | --- |
| `operator user create USER_ID [--name DISPLAY_NAME]` | Creates a user. The display name defaults to the ID. |
| `operator user get USER_ID` | Gets a current user by ID. |
| `operator user list` | Lists current users. |
| `operator user update USER_ID --name DISPLAY_NAME` | Updates the display name and preserves the user ID. |
| `operator user delete USER_ID` | Marks the user as deleted. The command rejects `admin` and users who still own a registered operator. |
| `operator register NAME [--user USER_ID] [--mission TEXT]` | Registers a named operator and returns its numeric ID. |
| `operator get OPERATOR_ID` | Gets a registered operator and its owner. |
| `operator list [--user USER_ID]` | Lists registered operators, optionally filtered by owner. |
| `operator unregister OPERATOR_ID` | Marks the operator as deleted and releases its open goal assignments. |

Both deletion commands return the record with its `deleted_at` timestamp.
Get and list show active records. The database retains deleted user IDs,
operator ownership, and assignment history.

## Workspace goals

`operator goal` uses `.harness/goals.sqlite3` in the current working directory.
Message-based creation uses Codex to draft the goal. Explicit creation and the
other goal commands access the local database directly and print JSON.

| Command | What it does |
| --- | --- |
| `operator goal create [MESSAGE]` | Saves a Codex-generated draft and prints its ID, goal kind, assessment type, and any clarification question. |
| `operator goal create --title TITLE [--parent GOAL_ID] [FIELDS]` | Creates an active goal. Supply a parent ID to create a subgoal. |
| `operator goal list` | Lists saved goals in this workspace. |
| `operator goal show GOAL_ID` | Shows the current goal. Add `--tree` for its descendants and current completion decisions, or `--history` for revision creation times, evidence recorded under each revision, and saved decisions. |
| `operator goal revise GOAL_ID FIELDS` | Updates the supplied fields and appends a revision when the definition changes. Use `--title TITLE` to rename the goal. |
| `operator goal observe GOAL_ID --retry-key KEY [--reported-date YYYY-MM-DD] EVIDENCE` | Records an owner confirmation or owner-supplied reference. Reuse the key for an identical retry. Use separate keys for intentional reports about the same day. |
| `operator goal progress GOAL_ID [--revision N]` | Assesses the current or selected revision using the evidence available now. Returns goal status, result, qualifying dates and their evidence IDs. Prose-only criteria return the available records. |
| `operator goal complete GOAL_ID --revision N EVIDENCE [--evidence-id ID]...` | Completes the current revision and cites the supplied records from this goal. Returns the saved decision on an identical retry. |

For `FIELDS`, use `--desired-outcome`, `--success-criteria`, `--measurement-plan`,
`--assessment-type` (`objective`, `judgment`, or `mixed`), `--duration` (`one_time`
or `standing`), or `--duration-days` (a positive whole number). A revision
requires at least one field or a new title.

Use `--target-distinct-dates N` to count distinct dates confirmed by the owner.
With `--duration-days D`, the inclusive window begins on `--window-start YYYY-MM-DD`
or the goal’s UTC creation date and lasts D calendar days. Without a duration,
all reported dates qualify if they have owner confirmation.

For `EVIDENCE`, supply exactly one of `--confirmation TEXT` or `--reference REF`.
A reference keeps its owner-supplied provenance. `complete` returns the statement’s
own evidence ID and the exact set of additional IDs supplied with `--evidence-id`.

Both `operator ask` and message-based `operator goal create` accept a quoted
message, piped input, or a message typed at the prompt.

```sh
operator ask "Which goals are still open?"
operator goal create "Help me track food for seven days."
operator goal create --title "Track food" --duration-days 7
```

## Development commands

| Command | What it does |
| --- | --- |
| `make setup` | Installs the workspace packages into `.venv` using `uv`. |
| `make api` | Starts FastAPI at `http://127.0.0.1:8000`. |
| `make check` | Runs Ruff lint and formatting checks. |
| `make format` | Formats files with Ruff. |
| `make test` | Runs the offline test suite. |
| `make test-live` | Runs the signed-in CLI and MCP acceptance tests for goal plans and progress. |
| `uv run --package harness-mcp harness_mcp` | Starts the standalone MCP server over stdio. |
