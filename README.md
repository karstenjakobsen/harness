# Harness Operator

`operator ask` sends one message to Codex and prints its reply. Use it to read
relevant workspace files, think through a goal, or suggest a small next step.
An ordinary session offers advice. The workspace owner can delegate completion
of one subgoal for an explicit session. Each invocation starts a fresh
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
`GoalAPI`. SQLite assigns integer IDs when it creates records. The protected system
user `admin` has ID 1. Use the ID returned by `operator user create` with
`--user`. Omitting the option registers the operator under `admin`.
In this fresh-workspace example, Sam receives user ID 2 and Planner receives operator ID 1.

```sh
operator user create sam --name "Sam Lee"
operator register Planner --user 2
operator list --user 2
operator unregister 1
operator user delete 2
```

Unregistering an operator timestamps its record and releases its open goal
assignments. After a user's last operator is unregistered, the user can be
soft-deleted. Ownership and assignment history survive both operations, and
deleted usernames and IDs stay reserved. See the [CLI command catalog](CATALOG.md).

## Saved goals

`operator ask` starts the local `harness_mcp` server over stdio. The server
uses `harness_api` to open `.harness/goals.sqlite3` in the working directory.
On first run, the API creates the database from the full schema snapshot in
`001_initial.sql`. Version 10 upgrades workspaces from versions 7, 8 and 9 in
place. Existing assignments keep their responsible operator and require an
explicit grant for completion authority. Opening a pre-v7 or unrecognized
workspace returns an error and leaves the file intact.

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

### Delegate completion of a subgoal

Register an operator, record evidence on the subgoal and run
`operator goal grant-completion GOAL_ID OPERATOR_ID`. Pass the returned grant
`id` to the next review session.

```sh
operator ask --completion-grant GRANT_ID \
  "Review this goal. If you judge the evidence sufficient, complete it. Otherwise tell me what's missing."
```

The operator chooses whether to complete the assigned subgoal. A saved
completion records the operator’s ID, rationale and cited observations. Use
`operator goal show GOAL_ID --history` to see the decision and the evidence
with its original attribution. Withdraw authority with
`operator goal withdraw-completion GRANT_ID`. A new grant requires a new session.
[Command catalog](CATALOG.md#workspace-goals)

### Create a draft goal

```sh
uv run --package harness-operator operator goal create "Keep the sample config file at mode 0600."
```

Codex drafts the outcome, success criteria, and measurement plan from your
request. `duration` describes a one-time result or a standing goal.
`duration_days` records the time window when supplied. For example, “Track food
for seven days” saves a window of 7 days. An unspecified window is stored as null.
“Log food on seven distinct dates within 14 days starting December 1, 2026” sets
`target_distinct_dates` to 7, `duration_days` to 14, and `window_start` to
`2026-12-01`. The draft can show progress as soon as it is saved.

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
| `GET`, `POST` | `/users` | List users or create one with `username` and optional `display_name`. Creation returns the generated numeric `id` |
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
| `GET` | `/goals/{goal_id}/history?view=activity` | Read the goal timeline and discover related operator runs |
| `GET` | `/runs/{run_id}` | Read the run identity, timing, outcome and ordered tool calls |
| `POST` | `/goals/{goal_id}/completion` | Complete the current `revision` with a confirmation or reference and optional `evidence_ids` |
| `DELETE` | `/goals/{goal_id}` | Soft-delete a leaf and close its assignment. A parent with visible children returns HTTP 409 |

An identical observation retry returns HTTP 200 with the original evidence ID.
Reusing a saved report’s key with different content returns 409. Submitting a new
observation dated after today in UTC returns 422 and leaves its retry key available.
A stale completion revision, conflicting completion retry, or citation from
another goal returns 422.

### Operator activity

Start with `GET /goals/{goal_id}/history?view=activity`. Its `timeline` contains
`revision`, `observation`, `decision` and `call` entries ordered by UTC `at`.
Calls use their start time. Timestamps can include fractional seconds. Entries
with equal timestamps sort by revision, observation, call, and decision, then
by their stable IDs. Each call gives its
`run_id`, `sequence`, `tool`, `outcome` and `relationship` to the goal. The
relationship is `listed`, `descendant`, `requested`, `completion_target`,
`creation_result`, or `revision_target`.
Requested targets contribute to the timeline when they resolved to an
owner-visible goal at call start. Returned goals and committed or retrieved
revision references also contribute to the timeline. A denied attempt appears
in run history, and appears on the goal timeline if the target resolved at
call start. The goal's definition, status, and decisions are preserved.
For version 9 records, returned references and matching bound grants establish
goal relationships. Older attempts with only a supplied ID remain in the run trace.
The revision list remains available at `/goals/{goal_id}/history`.

Follow a `run_id` to `GET /runs/{run_id}`. An advisory run has null operator and
grant fields. A delegated run identifies the registered operator and exact grant.
Completion runs retain `completion_grant_id` and `granted_goal_id`. A run with
a creation or revision grant includes `definition_grant` with `id`, `operator_id`,
`action`, and `goal_id`. The action is `create_goal` for top-level creation with
`goal_id: null`, or `revise_goal` for a single goal. The run outcome is
`succeeded`, `failed`, or `unfinished`.
A launch error, such as an existing trace file, marks the run `failed`.
Calls are ordered by `sequence` and retain the requested goal ID and revision
when supplied, including on denial. The call outcome is `returned`, `denied`,
`failed`, or `unfinished`. A successful empty result has `returned_goals: []`.
Calls without a returned result have `returned_goals: null`.

Each result reference retains its goal ID, revision and any returned status. `observation_ids`
identifies observation records returned by a progress call. A result's `decision`
identifies the event and its citations, including the statement evidence ID when
present. For completion, follow `committed_event_id` from the call to the timeline's
decision and its `committing_call`. An identical authorized retry uses
`retrieved_event_id`. The decision records the rationale, operator, and grant.
The observation entries resolve each evidence ID to its submitter and timestamp.

For goal definitions, a revision entry's `committing_call` identifies its run
and sequence. Follow it to the call's `committed_revision`, which carries
`goal_id` and `revision`. An identical authorized creation retry has its own call
with `retrieved_revision` pointing to revision 1. A revision call with a stale
`expected_revision` conflicts. A patch that leaves the definition unchanged can
return the current revision without a commit. Direct owner and HTTP revisions
have `committing_call: null`, as do revisions saved before definition auditing.

`operator goal history GOAL_ID` and `operator run show RUN_ID` return the same
records through `GoalAPI.get_goal_activity` and `GoalAPI.get_run`. Audit capture
covers Harness MCP calls during `operator ask`. It stores typed references and
outcomes. Prompt text, raw tool arguments and results, and credentials are
excluded. Direct CLI and HTTP reads fall outside capture. Owner reports entered
through the CLI appear in the timeline with their original attribution.

A read reference is saved before MCP hands the response to the transport.
Receipt by the assistant can remain unknown if the connection drops. A revision
or completion transaction saves its committing call even if the call remains
`unfinished` after an interruption. Older decisions and direct owner completions
have `committing_call: null`. All MCP goal writes require a recorded run.

The `harness_api` package follows MVC. `GoalAPI`, `UserAPI`, and `OperatorAPI`
own persistence and business rules. The FastAPI controllers call those models,
and Pydantic views define the HTTP request and response bodies. Workspace CLI
commands call the same Python models. Start FastAPI and run the CLI from the
same workspace to use the same SQLite database.

Run `make test` for the offline suite and `make check` for lint and formatting.
Run `make test-live` separately with Codex signed in. It populates temporary workspaces through
the CLI, verifies plan and progress reads through MCP, and checks the replies.
Test teardown removes the workspace and its database even if an assertion fails.
