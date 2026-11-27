# Harness Operator

`operator ask` sends one message to Codex and prints its reply. Use it to read
relevant workspace files, think through a goal, or suggest a small next step.
An ordinary session offers advice. The workspace owner can delegate a definition change,
creation of draft children under one parent, or completion of one subgoal. Each invocation starts a fresh
conversation using the Codex read-only sandbox. It uses your existing Codex
sign-in and skips your personal Codex configuration.

## Setup

Install `uv` and GNU Make. For `operator ask` and message-based goal creation,
install a Codex CLI that supports `codex exec` with `--ephemeral` and
`--ignore-user-config`.

```sh
make setup
uv run --package harness-operator operator ask "List goals."
uv run --package harness-operator operator ask "Read goals/POC.md and suggest one small next step."
```

`make setup` uses `uv` to create `.venv` with Python 3.14. You can run
`harness-operator` or `operator` directly after activating the virtual environment.

Run `operator ask` to type a message at the prompt, or pipe a message into the
same command. Use `make check` to run the Ruff lint and format checks.

## Local Nomad workloads

Use a Linux host with Docker Compose, a running systemd user manager with access
to the local Docker Engine, and `bash`, `flock`, `curl`, `jq`, GNU Make and
`uv`. Compose runs the digest-pinned Nomad **2.1.1** server, publishes its
loopback ports, and checks for an elected leader. The systemd user service
copies the matching binary from that container into its runtime directory and
runs the client on the Linux host. The client uses the Docker driver to launch
workloads. The server API is at `http://127.0.0.1:14646`. Reserve local ports
14646–14651 for this setup. [Compose definition](dev/nomad/compose.yaml) · [Client unit](dev/nomad/harness-nomad-client@.service)

```sh
make nomad-up       # Start the server, then the host client. Wait for Docker readiness.
make test-nomad    # Starts or reuses the cluster and runs the real workload tests.
make nomad-down    # Stop the client and remove the Compose server and its data volume.
```

`make nomad-up` links a checkout-specific unit into the systemd user manager
for the current login session. While it is running, `dev/nomad/cluster.sh identity`
prints the container ID for `docker logs` and the unit name for `journalctl --user -u`.
After a server-only or partial startup, `make nomad-down` still attempts Compose
cleanup if the systemd user session is unavailable. It returns a nonzero status
and reports when client cleanup could not be verified.

In Python, construct `NomadBackend(address)` with an already-running cluster.
`start(run_id, WorkloadSpec(image, argv))` accepts an image pinned by digest
and a literal argument tuple starting with the executable. It returns a handle
for one batch job. For example, `("printf", "%s", "${NOMAD_ALLOC_ID}")` prints
`${NOMAD_ALLOC_ID}`. Repeating the same request retrieves that handle. A changed spec under
the same ID raises `WorkloadConflictError`. If registration cannot be
confirmed, retry `StartOutcomeUnknown` with the original ID and spec.

`inspect(handle)` reports state, job ID, allocation ID once placed and exit code
when observed. After `stop(handle)`, poll for `stopped`. A task that exits
unsuccessfully reports `failed`. A disconnected or lost allocation reports
`unknown` with an unknown exit code. The original allocation can reconnect
within a one-hour window. Nomad is configured to keep it and suppress replacement
during that window. [Nomad disconnect policy](https://developer.hashicorp.com/nomad/docs/job-specification/disconnect)

Before the workload starts, a pinned Nomad CLI prestart task checks its allocation
and the job’s placements through the task-local API socket. Only a sole allocation
with no predecessor or successor passes. A failed read also blocks launch. On a
cluster with ACLs, the prestart task’s workload identity needs access to read its
allocation and the job’s allocations. This check also covers a placement created
after disconnect expiry or by a scheduler override.

If multiple placements are observed, `inspect` returns `unknown`. It keeps
the original `allocation_id` when identifiable and exposes additional IDs in
`replacement_allocation_ids`. Inspect and stop remain available for older jobs.
A start retry against a job registered before the prestart check raises
`WorkloadConflictError`. Capture outcomes before Nomad collects their records.
During Phase 2, Harness prepares attempts and serves worker MCP. We launch
workloads ourselves by rendering Jinja and submitting the job directly to Nomad.
The existing backend remains available for the Slice 9 development proof.
[Execution contract and acceptance](docs/phase1/SLICE9_TODO.md) · [Active Phase 2 plan](docs/phase2/phase2.md)

## Run the Slice 11 worker experiment

`make test-phase2` runs required acceptance with one real Codex worker session
and zero AI operator sessions. The worker reads its brief through MCP, writes
`cities.txt` in `/workspace`, submits it through MCP and exits. The owner then
retrieves the saved file through Harness after exit and after scratch cleanup.
Use the installed CLI, Docker, the local Nomad setup and an existing Codex login.

The three steps can be run separately from the repository root. Choose a new,
empty workspace for each attempt. Seed and render work with Nomad stopped.

```sh
make setup
make worker-image
workspace="$PWD/.harness/phase2/my-worker-run"
.venv/bin/python dev/phase2/experiment.py seed --workspace "$workspace"
receipt="$workspace/phase2/receipt.json"
image="$(docker image inspect --format '{{.Id}}' harness-worker:slice10)"
.venv/bin/python dev/phase2/experiment.py render --receipt "$receipt" --image "$image"

# Inspect this checkpoint before submitting anything.
cat "$workspace/phase2/prepared.json"
cat "$workspace/phase2/job.json"

make nomad-up
.venv/bin/python dev/phase2/experiment.py run --receipt "$receipt"
```

`prepared.json` records the persisted attempt with an empty execution outcome.
`job.json` is the exact request sent to Nomad, including its unique job ID,
immutable image, one task, disabled restart and reschedule policies, runtime
bootstrap and mount declarations. Its SHA-256 is saved in the receipt. An edited
job must be rendered again before submission. Changing the brief uses a new work
item and attempt in a fresh workspace.

At run time the development script binds the attempt's scratch through the owner
CLI, issues a mode-0600 credential file and starts the standalone worker MCP
server. It registers the scratch and private runtime directories as per-attempt
Nomad host volumes, then submits the rendered job directly to Nomad. The worker
receives its credential and a private copy of the selected Codex `auth.json`
through the runtime mount. Credentials stay outside the rendered job and receipt.
Use `run --auth-file PATH` for a different login file and `render --mcp-port PORT`
for a different loopback endpoint. For Docker Desktop, supply
`render --mcp-url http://host.docker.internal:8001/mcp`. That selects an
authenticated MCP listener reachable from its containers. The local worker uses
Docker host networking.

The receipt's `fixture` contains the assignment and expected city lines.
`execution` contains observed allocation, exit, trace, audit and artifact results.
A prepared or pending attempt has no successful execution result. Saved evidence
includes the allocation record, stdout JSONL worker trace, stderr, worker MCP log,
Harness inspection and retrieved file. The script revokes the credential, stops
MCP and removes its job, volumes and runtime directories after execution. Scheduler
observations stay in the experiment receipt. The goal remains active at its
original revision. [Slice 11 acceptance](docs/phase2/SLICE11.md)

The worker image runs Codex with `--sandbox danger-full-access`, using the
container as the isolation boundary. Worker commands inherit the container
user's filesystem and network permissions. The live handoff passes with Docker's
default seccomp and AppArmor profiles. On Docker Desktop, run acceptance with
its worker-reachable MCP address.

```sh
HARNESS_PHASE2_MCP_URL=http://host.docker.internal:8001/mcp make test-phase2
```

Receipts persist the terminal allocation and exit before cleanup. A failed final
export leaves `phase: "verify_pending"`. Repeating `run` retries that export from
Harness. `cleanup_pending` retries the recorded teardown. These stages preserve
the original worker session and submission.

After an interruption before a terminal allocation was observed, repeating `run`
revokes the run's grant, stops its owned MCP listener and cleans up its Nomad job,
volumes and private runtime directory. The attempt records the interruption.
Another execution uses a fresh attempt. Runtime ownership includes a process ID,
kernel start time and run marker, and the MCP process lifetime is bound to its
runner. Older receipts with a completed allocation also recover through the
saved result. [Captured live and recovery results](docs/phase2/SLICE11_EVIDENCE.md)

`make test-phase2-smoke` runs two scripted city writers from separate empty
workspaces and an exit-7 failure case. These optional scheduler checks use the
fixture's `smoke_argv` with zero model sessions. Worker receipts retain only
the assignment criteria. Required worker acceptance uses
the generic `harness-worker` entrypoint. A successful live receipt records
`worker_sessions: 1` from the real Codex trace, `ai_operator_sessions: 0` from
the recorded CLI command sequence, a saved `artifact_id`, the actual
allocation exit code and the digest of the bytes retrieved through Harness.

## Prepare an attempt and hand off a file

Preparation persists an attempt ID and work item binding. The same ID and work
item return the original attempt. Another work item under that ID conflicts.
Preparation works offline with Python, the installed CLI and Git for skill
catalog import. The manual MCP handoff below uses zero model sessions.

Run this Bash sequence from the repository root after `make setup`. It uses a
new workspace, parses the returned IDs and keeps the credential outside scratch.
Choose an available loopback port for `serve-mcp`.

```sh
source .venv/bin/activate
operator_cli="$(command -v operator)"
workspace="$(mktemp -d)"
attempt_id=manual-1
json_field() { python -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }

cd "$workspace"
operator_id="$("$operator_cli" register Builder | json_field id)"
"$operator_cli" goal create --title "Prepare a real file" > goal.json
goal_id="$(json_field id < goal.json)"
revision="$(json_field revision < goal.json)"
work_id="$("$operator_cli" work --workspace "$workspace" create \
  --goal-id "$goal_id" --revision "$revision" --operator-id "$operator_id" \
  --skill worker-handoff@1 --brief "Write a real result.txt." | json_field id)"
"$operator_cli" work --workspace "$workspace" prepare "$work_id" --attempt-id "$attempt_id"
"$operator_cli" work --workspace "$workspace" prepare "$work_id" --attempt-id "$attempt_id"
"$operator_cli" work --workspace "$workspace" show "$attempt_id"

mkdir "$workspace/scratch"
"$operator_cli" work --workspace "$workspace" bind-scratch "$attempt_id" "$workspace/scratch"
"$operator_cli" work --workspace "$workspace" issue-credential "$attempt_id" \
  --output "$workspace/worker.credential"
# Issuance creates a new mode-0600 file and prints only grant metadata.
"$operator_cli" work --workspace "$workspace" serve-mcp --port 8001 > worker-mcp.log 2>&1 &
mcp_pid=$!
cleanup() {
  trap - EXIT
  "$operator_cli" work --workspace "$workspace" revoke-credential "$attempt_id"
  kill "$mcp_pid"
  wait "$mcp_pid" || [ "$?" -eq 143 ]
}
trap cleanup EXIT
```

With that server running, this protocol client reads the assignment, writes a
real file and submits it. It uses the MCP and HTTP clients installed by
`make setup`. The client waits for the server to become ready. The credential
stays in the private file and HTTP header.

```sh
python - "$workspace" <<'PYCLIENT'
import asyncio
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def handoff():
    endpoint = "http://127.0.0.1:8001/mcp"
    async with httpx.AsyncClient(trust_env=False, timeout=0.5) as probe:
        for _ in range(150):
            try:
                if (await probe.get(endpoint)).status_code == 401:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Worker MCP did not become ready")
    workspace = Path(sys.argv[1])
    credential = (workspace / "worker.credential").read_text()
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {credential}"}, trust_env=False,
    ) as http:
        async with (
            streamable_http_client(endpoint, http_client=http) as (reader, writer, _),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            brief = await session.call_tool("get_work_brief", {})
            assert not brief.isError
            print(brief.structuredContent)
            (workspace / "scratch/result.txt").write_text("A real file.\n")
            saved = await session.call_tool("submit_work_result", {"relative_path": "result.txt"})
            assert not saved.isError
            print(saved.structuredContent)

asyncio.run(handoff())
PYCLIENT

rm -- "$workspace/scratch/result.txt"
rmdir "$workspace/scratch"
"$operator_cli" work --workspace "$workspace" artifact "$goal_id" --output "$workspace/recovered.txt"
cat "$workspace/recovered.txt"
"$operator_cli" work --workspace "$workspace" show "$attempt_id"
cleanup
trap - EXIT
```

Revocation takes effect on every request, including an existing MCP connection
and artifact submission retries. Issuing a replacement into a new private file
invalidates the previous credential. An existing output file is preserved.
After an interrupted issuance, use the saved file or issue a replacement to a
new file. The owner can retrieve saved artifacts after revocation and scratch
cleanup. `show` reads persisted work, attempt, call and artifact data. Runtime
fields can be null and `trace_path` is null.

Scratch directories must be disjoint across attempts. Binding resolves symlink
aliases and rejects equal, ancestor or descendant directories inside the write
transaction. `show` uses `WorkAPI.get_attempt_details` to read the complete
inspection result from one SQLite snapshot during concurrent submissions.

`work create --source /absolute/local/repository --base-sha FULL_COMMIT_SHA`
records checkout input. The person launching the workload prepares its isolated
checkout, mounts scratch at `/workspace` and provides model access when needed.
`serve-mcp --host ADDRESS --allowed-host HOST` supports an explicitly reachable
endpoint. Every worker request requires its attempt credential. Worker tools are
`get_work_brief`, `list_skills`, `read_skill` and `submit_work_result(relative_path)`.
The public model rechecks the exact grant, operator, goal revision and assigned
skills. Artifact bytes, metadata and attribution are saved together. The first
successful save stays authoritative on an authorized same-path retry after
scratch changes or cleanup. Another path conflicts. Files are limited to 16 MiB,
and submission validates regular files and path containment.

The generic image remains buildable with `make worker-image`. It uses the pinned
`ghcr.io/icoretech/codex-docker:0.166.0@sha256:c0568397f66fb8cc22c541fbafe26948da5000d24770b0ac2e918517dfc02615`
base and `harness-worker run --attempt-id ID`. External execution supplies
`HARNESS_WORKER_ATTEMPT_ID`, `HARNESS_WORKER_MCP_URL`, `HARNESS_WORKER_TOKEN`,
the writable workspace and the worker's model access. The attempt ID identifies
the assignment, and the credential establishes authority. Goal review remains a
separate decision after submission.

`make test` includes the subprocess CLI and real HTTP handoff acceptance with
Docker, Nomad and Codex unavailable. `make test-live` runs the signed-in operator
scenarios for plans, progress, delegation, history, skills and HTTP attribution.
`make test-live-extended` invokes that same signed-in suite. The Slice 10 city and
checkout Docker handoffs remain recorded as incomplete because the host blocked
Bubblewrap namespaces. Their captured evidence and image digests are preserved
in the archive. [Slice 10 evidence](docs/phase1/SLICE10_EVIDENCE.md) · [Phase 2 prerequisite](docs/phase2/PHASE2_DECOUPLING_TODO.md)

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
Harness initializes an empty database from the current [schema.sql](packages/harness_api/src/harness_api/schema.sql)
and reuses it on later runs. For local development, start in a fresh directory
after an incompatible schema change. Your previous database stays in its original directory.

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

### Plan with versioned skills

Before each `operator ask` session, Harness imports the committed `skills/` tree
from the Harness checkout used by `make setup`. The caller can start in an empty
workspace. Each skill directory contains a UTF-8 `operator.yaml` and `SKILL.md`.
The manifest declares `kind: skill`, a stable `id` matching
`[A-Za-z0-9][A-Za-z0-9_.-]*`, a positive 64-bit integer `revision`, and a
`name`, `description`, and `author`. A duplicate manifest field rejects the
catalog. The Git reader uses the original objects for its recorded commit SHA,
including in checkouts with local replacement refs.

Recorded sessions can use `list_skills()` to discover guidance and
`read_skill(id, revision)` to retrieve it. The operator chooses which revisions
to read and which subgoals to propose. An advisory plan stays in the reply.

Discovery reflects the last successful import into this workspace. Removing a
skill removes it from discovery. The saved revision retains its original files,
directory path, Git commit SHA and SHA-256 content hash. The hash covers the
manifest’s UTF-8 byte length as eight big-endian bytes, then the manifest and
Markdown bytes in order. An unrelated commit or folder move preserves the
original provenance. Changing either file under an existing ID and revision
rejects the entire import before the run starts. Bump the manifest revision to
publish changed content. Historical HTTP reads use SQLite even when the source
checkout is unavailable. The public skill queries raise `SkillValidationError`
for a malformed ID or revision (HTTP 422) and `SkillNotFoundError` for a valid
key absent from the owner’s catalog history (HTTP 404). [Seed catalog](skills)

### Delegate subgoal creation

In a fresh workspace, use `operator goal grant-subgoals PARENT_ID OPERATOR_ID`
and pass the returned grant ID to `operator ask --definition-grant GRANT_ID`.
Ask the operator to break the named goal into subgoals and save them for review.
Each saved child starts at revision 1 in draft status with success criteria.
Inspect the plan with `operator goal show PARENT_ID --tree`. An interruption can
leave a partial plan, so the next operator can inspect the children before continuing.

A grant permits direct children under a draft, active, or paused parent. An
identical authorized retry can retrieve a saved child after the parent completes
or is revoked at the same revision. A change to the parent definition makes an
older request stale. After reviewing the new revision, use a new key for new work.

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
| `GET` | `/skills` | List skills and revisions in the workspace owner’s current catalog |
| `GET` | `/skills/{skill_id}/revisions/{revision}` | Read the exact saved manifest, instructions and source provenance |
| `GET` | `/skills/{skill_id}/revisions/{revision}/reads` | List owner-visible `{run_id, sequence}` pairs for calls that returned the full revision |
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
The revision list remains available at `/goals/{goal_id}/history`.

Follow a `run_id` to `GET /runs/{run_id}`. An advisory run has null operator and
grant fields. A delegated run identifies the registered operator and exact grant.
Completion runs retain `completion_grant_id` and `granted_goal_id`. A run with
a creation or revision grant includes `definition_grant` with `id`, `operator_id`,
`action`, and `goal_id`. The action is `create_goal` for top-level creation with
`goal_id: null`, `create_subgoal` with the parent’s ID, or `revise_goal` for a single goal. The run outcome is
`succeeded`, `failed`, or `unfinished`.
A launch error, such as an existing trace file, marks the run `failed`.
Calls are ordered by `sequence` and retain the requested goal ID and revision
or the requested run ID (`target_run_id`), including on denial. The call outcome
is `returned`, `denied`, `failed`, or `unfinished`. A successful empty goal
result has `returned_goals: []`. History reads use `returned_history`. Skill calls
use `returned_skills`, an ordered list of `{id, revision}` references. A
successful empty catalog listing returns `[]`. A call without a returned
result has all three fields set to `null`.

For `create_subgoal`, the parent’s activity lists the call as `requested`.
Follow its run ID and sequence to see `target_goal_id` and `target_revision`
for the parent and `committed_revision` for the new child. An identical retry
has a `retrieved_revision`. Open `GET /goals/{child_id}/history?view=activity`
to find the `creation_result` and follow revision 1’s `committing_call` back
to the original call. This link survives an interruption before reply delivery.
A denied call has no saved result. Once a call commits or retrieves a child,
its audit record preserves that fact even if delivery fails.

For a `list_skills` call, these references identify the descriptions made
available for discovery. For a `read_skill` call, `target_skill_id` and
`target_revision` identify the requested revision. An invalid skill ID yields
a denied attempt with a null `target_skill_id`. A returned reference
identifies the instructions Harness handed to the transport. To inspect them,
follow the reference to `GET /skills/{skill_id}/revisions/{revision}`. Append
`/reads` to find the calls that returned those instructions. A listing alone
contributes zero entries to that reverse lookup.

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
records through `GoalAPI.get_goal_activity` and `GoalAPI.get_run`. Advisory and
delegated `operator ask` sessions can use these queries through the read-only
MCP tools `get_goal_activity` and `get_run`, including for other operators'
runs in the same workspace. A standalone MCP server without a recorded run
omits both tools from discovery and rejects direct calls to them.

For `get_goal_activity`, `returned_history` contains the goal ID and ordered
timeline references, including revision numbers and their committing calls,
observation IDs, decision IDs and citations, and related call entries. For
`get_run`, it contains the inspected run ID and its outcome, plus each call's
run ID, sequence, outcome, and commit or retrieval references as returned at
read time. For example, a saved read can show an `unfinished` call with a
committed revision after the call itself becomes `returned`. The snapshot
excludes the executing call. Inspecting an earlier history read exposes its
saved references one level deep.

Audit capture covers Harness MCP calls in recorded runs. It stores typed references and
outcomes. Prompt text, raw tool arguments and results, and credentials are
excluded. Direct CLI and HTTP reads fall outside capture. Owner reports entered
through the CLI appear in the timeline with their original attribution.

A read reference is saved before MCP hands the response to the transport.
Receipt by the assistant can remain unknown if the connection drops. A revision
or completion transaction saves its committing call even if the call remains
`unfinished` after an interruption. Direct owner completions
have `committing_call: null`. All MCP goal writes require a recorded run.

The `harness_api` package follows MVC. `GoalAPI`, `SkillAPI`, `UserAPI`, and `OperatorAPI`
own persistence and business rules. The FastAPI controllers call those models,
and Pydantic views define the HTTP request and response bodies. Workspace CLI
commands call the same Python models. Start FastAPI and run the CLI from the
same workspace to use the same SQLite database.

Run `make test` for the offline suite and `make check` for lint and formatting.
Run `make test-live` separately with Codex signed in. It populates temporary workspaces through
the CLI, verifies MCP reads and delegated writes, and checks the replies. The
shared history test follows a revision to its committing call and a separate
operator's history read over HTTP.
Test teardown removes the workspace and its database even if an assertion fails.
