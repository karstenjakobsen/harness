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
| `operator ask [--trace-file PATH] [MESSAGE]` | Opens an advisory session and prints its reply. The optional flag saves the Codex event stream, including MCP calls, to a new file. |
| `operator ask --completion-grant GRANT_ID [--trace-file PATH] [MESSAGE]` | Opens a session that can complete the specific subgoal covered by the active grant. |
| `operator ask --definition-grant GRANT_ID [--trace-file PATH] [MESSAGE]` | Opens a session that can create top-level goals, create draft children under one parent, or revise one goal, according to its grant. |

Today, `operator ask` can read goals with `list_goals`, `get_goal_tree` and
`get_goal_progress`. Advisory and delegated sessions can inspect goal timelines
and earlier runs with `get_goal_activity` and `get_run`. Both tools require a
recorded run and save references to the records they expose.
The assistant can weigh the evidence, suggest completion or ask what
is missing. To act on its advice, the local owner uses `operator goal complete`.
Named registration creates a workspace record. Ordinary ask sessions remain advisory.

Before starting each run, `operator ask` imports the committed Harness skill
catalog into the selected workspace. A recorded session can discover descriptions
with `list_skills()` and choose exact instructions with `read_skill(id, revision)`.
An invalid catalog stops startup before a run is created. Inspect
`operator run show RUN_ID` for the skill revisions each call listed or read. [Skill catalog and provenance](README.md#plan-with-versioned-skills)

The delegated session exposes
`complete_goal(goal_id, expected_revision, evidence_ids, rationale)`.
Harness derives the actor from the grant bound at startup and returns the saved
decision with its citations. The operator decides when the evidence is sufficient.
The session's grant is checked again on every completion call.

The owner grants one definition action per session. MCP discovery reflects the
bound grant’s current authority. The model rechecks it inside every write transaction.

- `create_goal` saves a top-level goal and defaults to `draft`.
- `create_subgoal` takes a parent ID, expected parent revision, retry key, title
  and success criteria. Each new key can save one direct draft child.
- `revise_goal` takes the current `expected_revision` of the granted goal.

Both creation tools return the original revision 1 result on an identical
authorized retry. On conflict, read the current definition and activity before
deciding how to proceed.

`operator ask` records Harness MCP activity in the workspace database. The
two history commands read its typed references and outcomes without requiring
`--trace-file`. [HTTP and CLI activity contract](README.md#operator-activity)

## Workspace users and operators

These commands use the current workspace database and print JSON. Every operator
record has one owner. The default owner is the protected system user `admin` (ID 1). Use the numeric IDs returned by creation commands for subsequent operations.
See how each entry point determines the target, owner and caller in [Identity and attribution](TERMINOLOGY.md#identity-and-attribution).

| Command | What it does |
| --- | --- |
| `operator user create USERNAME [--name DISPLAY_NAME]` | Creates a user and returns the generated ID. The display name defaults to the username. |
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

`operator goal` and `operator run show` call `GoalAPI` for the current workspace,
which uses `.harness/goals.sqlite3` in the current working directory. Message-based
creation uses Codex to draft the goal before the CLI saves it through `GoalAPI`.
Explicit creation and the other workspace commands print JSON.

| Command | What it does |
| --- | --- |
| `operator goal create [MESSAGE]` | Saves a Codex-generated draft and prints its ID, goal kind, assessment type, and any clarification question. |
| `operator goal create --title TITLE [--parent GOAL_ID] [FIELDS]` | Creates an active goal. Supply a parent ID to create a subgoal. |
| `operator goal list` | Lists saved goals in this workspace. |
| `operator goal show GOAL_ID` | Shows the current goal. Add `--tree` for its descendants and current completion decisions, or `--history` for revision creation times, evidence recorded under each revision, and saved decisions. |
| `operator goal history GOAL_ID` | Shows revisions, observations, decisions and run calls linked by a resolved target or returned goal. |
| `operator run show RUN_ID` | Shows one operator run with its identity, timing, outcome, ordered calls, returned references and revision or decision links. |
| `operator goal revise GOAL_ID FIELDS` | Updates the supplied fields and appends a revision when the definition changes. Use `--title TITLE` to rename the goal. |
| `operator goal observe GOAL_ID --retry-key KEY [--reported-date YYYY-MM-DD] EVIDENCE` | Records an owner confirmation or owner-supplied reference. Reuse the key for an identical retry. Use separate keys for intentional reports about the same day. |
| `operator goal progress GOAL_ID [--revision N]` | Assesses the current or selected revision. `evidence` contains every record considered. `days` lists each qualifying date and its supporting IDs. |
| `operator goal complete GOAL_ID --revision N EVIDENCE [--evidence-id ID]...` | Completes the current revision and cites the supplied records from this goal. Returns the saved decision on an identical retry. |
| `operator goal grant-completion GOAL_ID OPERATOR_ID` | Assigns the subgoal with explicit completion authority. Returns a fresh grant `id`, the goal ID and operator ID. |
| `operator goal withdraw-completion GRANT_ID` | Closes that assignment and invalidates sessions bound to the grant. |
| `operator goal grant-create OPERATOR_ID` | This operator may create top-level goals in this workspace until you withdraw the grant. Returns the grant ID and operator ID. |
| `operator goal grant-subgoals PARENT_ID OPERATOR_ID` | Grants repeated creation of direct draft children under the specified parent. Returns the grant ID for `operator ask --definition-grant`. |
| `operator goal grant-revision GOAL_ID OPERATOR_ID` | Grants revision of the specified goal. Returns the grant ID, goal ID and operator ID. |
| `operator goal withdraw-definition-grant GRANT_ID` | Withdraws the definition grant and invalidates sessions bound to it. |

For `FIELDS`, use `--desired-outcome`, `--success-criteria`, `--measurement-plan`,
`--assessment-type` (`objective`, `judgment`, or `mixed`), `--duration` (`one_time`
or `standing`), or `--duration-days` (a positive whole number). A revision
requires at least one field or a new title.

Use `--target-distinct-dates N` to count distinct dates confirmed by the owner.
With `--duration-days D`, the inclusive window begins on `--window-start YYYY-MM-DD`
or the goal’s UTC creation date and lasts D calendar days. Without a duration, the rule has no time window. A new report can concern
today in UTC or an earlier date. Future dates are rejected.

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

## Worker assignments

These owner commands use `WorkAPI` and print JSON, except `serve-mcp`, which
runs until interrupted. All accept `operator work --workspace PATH COMMAND`.
The default workspace is the current directory. Related preparation, scratch,
credential, server and artifact operations must select the same workspace.
Create a goal and named operator first. Work creation imports the committed
skill catalog and records exact revisions.

| Command | What it does |
| --- | --- |
| `operator work create --goal-id ID --revision N --operator-id ID --brief TEXT [--skill ID@REVISION]... [--source PATH --base-sha SHA]` | Saves an immutable work item. Supply both source options to record a local Git repository and its exact base commit SHA. Returns the work item ID. |
| `operator work prepare WORK_ITEM_ID --attempt-id ID` | Persists an attempt and returns its `id` and `work_item_id`, plus saved attempt metadata. An identical retry returns the same attempt. Reusing the ID for another work item conflicts. Works offline. |
| `operator work bind-scratch ATTEMPT_ID PATH` | Binds an existing directory to the attempt for MCP file submissions. A repeated binding to that path returns the attempt. Another path conflicts. |
| `operator work issue-credential ATTEMPT_ID --output NEW_PATH` | Writes a fresh credential to a new mode-0600 file and returns grant metadata. Preserves existing files. Replaces any active grant with the new grant. |
| `operator work revoke-credential ATTEMPT_ID` | Revokes the active grant. Existing connections and saved-result retries recheck authority. |
| `operator work serve-mcp [--host ADDRESS] [--port PORT] [--allowed-host HOST]...` | Serves authenticated worker MCP at `/mcp`. Defaults to `127.0.0.1:8001`. Use Ctrl-C or SIGTERM to stop. |
| `operator work show ATTEMPT_ID` | Reads persisted `attempt`, `work_item`, worker MCP `calls` and saved `artifact` metadata. Runtime fields may be null. `trace_path` is null. |
| `operator work artifact GOAL_ID --output NEW_PATH` | Copies the latest saved artifact for the goal into a new file and returns metadata. Preserves existing output files. Works after scratch cleanup and credential revocation. |

Keep the credential outside scratch and seed receipts. The owner binds scratch,
issues the private credential file, serves MCP and revokes the credential using
the documented shell sequence. Slice 11 can reuse these installed CLI commands.
[Manual handoff sequence](README.md#prepare-an-attempt-and-hand-off-a-file)

Worker MCP exposes `get_work_brief()`, `list_skills()`,
`read_skill(id, revision)` and `submit_work_result(relative_path)`. Each request
uses its Bearer credential to establish the attempt and exact grant. Skills are
scoped to assigned revisions. The first successful submission saves independent
bytes with the attempt, goal revision, operator and grant. An authorized retry
of that path returns the original artifact after scratch changes or cleanup.
Another path conflicts. Goal completion remains a separate decision.

`make worker-image` preserves the generic `harness-worker:slice10` image and its
`harness-worker run --attempt-id ID` entrypoint. The person launching the workload
provides scratch, endpoint, credential and model access at runtime. During Phase 2,
we render Jinja and submit jobs directly to Nomad. [Phase 2 plan](docs/phase2/phase2.md)

## Development commands

| Command | What it does |
| --- | --- |
| `make setup` | Installs the workspace packages into `.venv` using `uv`. |
| `make api` | Starts FastAPI at `http://127.0.0.1:8000`. |
| `make nomad-server` | Starts the checkout’s Nomad 2.1.1 Compose service and waits for its leader health check. |
| `make nomad-agent` / `make nomad-up` | Starts or reuses the Compose server and systemd user client, then waits for the host client to report a healthy Docker driver. |
| `make test-nomad` | Brings up the development cluster and checks workload exit, concurrent start, repeated stop, literal arguments and refusal of a second placement. Cleans up its test jobs. |
| `make nomad-down` | Attempts client and Compose cleanup independently. Removes the checkout’s Compose server, network and data volume and reports a failure if it cannot verify the systemd client cleanup. |
| `make check` | Runs Ruff lint and formatting checks. |
| `make format` | Formats files with Ruff. |
| `make test` | Runs the offline test suite. |
| `make worker-image` | Builds the thin worker image as `harness-worker:slice10`. Set `WORKER_IMAGE` to choose another build tag. |
| `make test-live` | Runs the signed-in operator scenarios for plans, progress, delegation, revision history, skills and HTTP attribution. |
| `make test-live-extended` | Invokes the same signed-in operator suite as `make test-live`. The historical Slice 10 Docker handoff results are archived. |
| `uv run --package harness-mcp harness_mcp` | Starts the standalone MCP server over stdio. |
