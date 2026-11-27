# Harness terminology

## People and interfaces

| Term | Meaning in Harness |
| --- | --- |
| User | A workspace account with a database-generated integer ID, a unique username and a display name. The protected system account is `admin` (ID 1). |
| Owner | The user related to a particular resource by its `owner_user_id`. |
| Registered operator | A workspace record with its own numeric ID, an owning user and optional goal assignments. |
| Assignment | The recorded relationship between a goal and the registered operator responsible for it. Unregistering the operator releases its open assignments and invalidates its grants. Delegated writes require an explicit grant. |
| Delegation | The owner’s explicit grant of a specific action and scope to a registered operator. A top-level creation grant covers the owner’s workspace. A subgoal creation grant authorizes draft children of one parent, whose ID is the grant’s `goal_id`. A revision grant covers one goal. A completion grant uses the ID of the assignment created when the owner grants completion of one subgoal. |
| Assistant | The Codex session that answers `operator ask` or drafts a goal definition. The CLI executable is named `operator`. |
| Workspace | The context for users, registered operators, goals, evidence, decisions, operator run history and worker handoffs. Local commands use the current workspace database. HTTP requests use the workspace served by the selected API server. |
| Schema snapshot | The table definitions, constraints and initial system user used to initialize an empty local database. [Workspace schema](packages/harness_api/src/harness_api/schema.sql) |
| Harness API | The workspace operations provided by the `harness_api` package. Its public Python interfaces are `UserAPI`, `OperatorAPI`, `GoalAPI`, `SkillAPI` and `WorkAPI`. The HTTP, CLI and MCP adapters call the model operations they expose. |
| HTTP API | The FastAPI interface for working with workspace users, registered operators and goals, and reading goal activity and operator runs. [Endpoint catalog](README.md#fastapi) |
| `UserAPI` | The public Python interface for creating, reading, updating and deleting workspace user accounts. |
| `OperatorAPI` | The public Python interface for registering, reading and unregistering operators. Unregistering also releases the operator’s open goal assignments. |
| `SkillAPI` | The public model for importing the workspace owner’s catalog, listing current skills, reading exact revisions and finding the run calls that read them. |
| `GoalAPI` | The public Python interface for goals and revisions, observations, progress assessments, completion decisions and grants. It also records operator runs and MCP tool calls and serves goal activity and run history. |
| `WorkAPI` | The public model for immutable work items, worker attempts and grants, scoped skill reads, saved artifacts and worker MCP audit calls. It checks the exact attempt authority and goal revision on worker operations. |
| Worker | One Codex session executing one attempt in an externally launched workload. It uses ordinary file and shell tools in `/workspace` and worker MCP to read its assignment and submit a file. A worker session is separate from an `operator ask` session. |

## Identity and attribution

| Current entry point | What the application establishes |
| --- | --- |
| Skill catalog and revision reads | The manifest ID identifies a skill across folder moves. `SkillAPI` scopes the catalog, revision lookup and reverse lookup of reading calls to the workspace account identified by `ADMIN_USER_ID`. The manifest author is the source’s declared author. |
| Goal and run reads | `GoalAPI` scopes goals, goal activity and operator runs to the workspace account identified by `ADMIN_USER_ID`. |
| Goal CLI and HTTP writes | Local owner writes use the workspace account as `submitted_by` for reports and `recorded_by` for completion. HTTP writes have no established caller and return null for those identities. In message-based creation, Codex drafts the definition and the CLI saves it through `GoalAPI` in the same account. |
| Account CLI and HTTP endpoints | A numeric user or operator ID selects an existing record. Named registration assigns the owner from `--user` or HTTP `owner_user_id`, defaulting to `admin`. These operations record no separate initiating identity. |
| Bare `operator register` | Starts Codex sign-in. Named registration creates a workspace operator record. |
| Advisory `operator ask` and MCP | The assistant reads saved goals through the admin-scoped MCP goal tools. History tools require a recorded run and can read across operators in the same workspace. |
| `operator ask --completion-grant GRANT_ID` | The assistant can also complete the specific subgoal covered by the active grant. Harness derives the registered operator from the grant. |
| `operator ask --definition-grant GRANT_ID` | The assistant can create top-level goals, create draft children under one parent, or revise one goal. The run’s bound grant determines the registered operator, permitted action and scope. |
| `operator work` owner commands | The local workspace owner selects the goal revision, registered operator, brief, skill revisions and optional source checkout. The trusted owner prepares an attempt, binds its scratch directory and issues or revokes its credential separately. `operator work --workspace PATH` selects the workspace for these operations and for serving worker MCP. |
| Worker MCP | A Bearer credential establishes one attempt and its exact grant. Tools accept no caller-selected attempt, operator or goal ID. Saved artifacts retain the attempt, work item, goal revision, registered operator and grant; every worker operation, including a retry, rechecks that authority. |

In a delegated session, Harness binds the assistant to a registered operator and a specific grant at startup. A replacement grant requires a fresh session. The **decision maker** is the actor who exercises the delegated authority. The **evidence submitter** is the actor who supplied a cited record. If the owner confirms “My membership is active” and an operator uses that confirmation to complete the subgoal, the evidence keeps the owner’s user ID and the decision records the registered operator’s ID. These IDs refer to different tables and can have the same numeric value. [Delegated completion plan](docs/phase1/SLICE3_TODO.md#delegated-completion)

The current HTTP endpoints do not establish who initiated a request. A resource ID identifies its target, `owner_user_id` identifies its owner, and `ADMIN_USER_ID` identifies the workspace account. For evidence writes, store the established submitter’s integer user ID or null for unknown attribution. Draft message roles (`user` and `operator`) describe the speaker’s role. Record the requester of a check and the observer that produced the result separately when known. Leave unknown identities explicit. An owner pasting an app link supplies a reference. Attributing an observation to the app requires a report from the app itself.

## Goals and decisions

| Term | Meaning in Harness |
| --- | --- |
| Goal | A desired outcome with a stable ID. “Build a personal tracker” defines an outcome. Creating that goal records it for planning. |
| Subgoal | A goal with a parent goal ID. It has its own criteria, revision history, and status. Completing a subgoal leaves the parent open until the parent's own completion decision. |
| Goal revision | A numbered snapshot of one goal's definition. Changing seven days to fourteen creates a revision under the same goal ID. |
| Success criteria | The conditions that must hold for a revision to succeed. For example, the file at a specified path has mode `0600`. |
| Measurement plan | How to check the criteria. For the file example, read its mode through an interface that reports the mode for that path. |
| Assessment type | How the criteria are evaluated. The model uses `objective`, `judgment`, or `mixed`. |
| Timing | `duration` distinguishes a one-time outcome (`one_time`) from an ongoing condition (`standing`). `duration_days` expresses a length in days. |
| Goal status | A stored lifecycle value of `draft`, `active`, `paused`, `completed`, or `revoked`. Use the exact value in API contracts and test assertions. |
| Operator judgment | Interpreting the available evidence against the owner’s criteria and choosing to act, ask for clarification or leave the goal open. A day pass shows a gym visit. The operator can ask whether the member joined. |
| Completion | A recorded decision that a specific goal revision met its criteria. It identifies the revision, decision time, decision maker when known and exact evidence cited. Owner and HTTP completion calls supply a confirmation or reference with its own evidence ID. Delegated completions cite existing observations. |
| Rationale | The decision maker’s explanation of why the cited evidence satisfies the revision. A delegated completion stores it alongside the IDs of the existing observations. |

## Evidence, assessment, and audit

An owner can record evidence while a goal is open. The event ID identifies the evidence for its lifetime. A report retains its submission revision when later revisions reuse it. In history, `created_at` dates a revision and `recorded_at` dates an evidence submission. Both timestamps are UTC. The optional `reported_date` is the calendar date the statement concerns. For owner input, `occurred_at` dates the reporting action.

| Term | Question it answers | File-mode example |
| --- | --- | --- |
| Observation | What did a person or interface report, and when? | At 10:00 the file check reported mode `0600` for the specified path. |
| Evidence | What information supports a claim, and where did it come from? | The file check's response supports a claim about the mode at 10:00. A link pasted by the owner has owner-supplied provenance. |
| Assessment | What does the evidence establish against this revision's criteria? | The standing goal met its condition at 10:00. Its lifecycle status is still `active`. |
| Audit record | Who performed which action in Harness, and when? | At 10:05 the owner recorded an observation made at 10:00. |
| Operator run | Which `operator ask` session contained the activity? | A delegated run records the registered operator and exact grant. An advisory run has no bound operator or grant. |
| Tool call | What did MCP attempt, and what outcome did it record? | The run trace keeps the requested target ID. When the goal was visible to the workspace owner at call start, the resolved target also links the call to that goal's timeline. A call can remain unfinished after the run ends. |
| Returned reference | Which goal revisions, skill revisions, observations, decision citations, runs or calls did a tool response expose? | A progress response returned observations 31 and 32. MCP saved their IDs before handing off the response. Assistant receipt can remain unknown. |
| Skill revision | Which exact guidance could the operator open? | The pair `(chess-rules, 1)` resolves to its original manifest, instructions, repository path, SHA and hash after revision 2 is imported. |
| Skill catalog | Which skill revisions are discoverable now? | A skill removed by the last successful import disappears from the listing. Earlier revisions remain available by exact ID and revision. |
| Listed skill | Which revision’s name and description did a discovery call return? | `list_skills` recorded revision 1 of both chess and Go. |
| Skill read | Which revision’s instructions did the tool return? | `read_skill` returned chess revision 1. The call records exposure of the instructions. Evidence of following them would require a separate observation. |
| History read | What did an operator see when inspecting a goal timeline or run? | A run read exposed an unfinished call with revision 2 already committed. The read retains that outcome and commit reference after the call becomes returned. |
| Committing call | Which call saved the revision or decision? | The model saves the revision or decision and its call link in the same transaction. On subgoal creation the requested goal and revision identify the parent, and the committed revision identifies the child. An identical creation or completion retry can retrieve the original record under its own call sequence. |

A successful HTTP response supports only the claim defined by that endpoint. A health check can establish reachability. A file-mode check can establish the mode of the file it inspected.

An **execution run ID** identifies one attempt to execute a workload on a selected cluster. The workload spec names a digest-pinned image and its literal argument vector. `NomadBackend` maps the run ID to a batch job. An **allocation** is a scheduler placement, with its own ID. A prestart check permits the workload in its original placement. On client loss or conflicting placements the run outcome is `unknown`. Inspection reports the original allocation when identifiable and the observed replacement IDs separately. A fresh attempt requires a caller-selected run ID. An **operator run** records an assistant session in the workspace. [Local Nomad workloads](README.md#local-nomad-workloads)

The local `operator goal` commands and `GoalAPI` with its default caller setting attribute observations to the workspace owner. A confirmation has source `owner_confirmation` and identifies that owner as submitter and observer. A pasted reference has source `owner_supplied_reference`, identifies its submitter and leaves the original observer unknown. An adapter without an established caller uses `GoalAPI(path, local_owner=False)`, as the HTTP service does. Its reports have source `unattributed_confirmation` or `unattributed_reference`. Unknown identities are null. Owner-input reports have no check requester. A retry key is scoped to the goal and submitting identity, with one scope for unattributed requests.

**Count distinct reported dates** groups dated owner confirmations by `reported_date` and retains each supporting evidence ID. The rule compares the number of qualifying dates with `target_distinct_dates`. `duration_days` optionally limits those dates to an inclusive window starting on `window_start` or the goal’s UTC creation date. A one-day window includes only its start date. The model returns `met` or `unmet` for this rule and `unavailable` for prose-only criteria.

Progress returns every record considered in `evidence`. Only the IDs grouped under `days` contribute to the distinct-date count. For example, a dated HTTP confirmation with an unknown submitter appears in `evidence` and contributes zero days.

An observation’s reported date may be at most the UTC calendar date when Harness records it. Earlier versions accepted advance reports. These retain their IDs, retry results and citations, and are excluded from the count even after the reported date passes.

Historical progress applies the selected revision’s criteria to the evidence available at read time and returns the goal’s current lifecycle status. A completion with a confirmation or reference keeps its original `statement_evidence_id` and the additional citations in `evidence_ids`. A delegated completion stores `recorded_by_operator_id`, `completion_grant_id`, `rationale` and the exact cited IDs in `evidence_ids`.

## Worker handoffs

| Term | Meaning in Harness |
| --- | --- |
| Work item | An immutable assignment with a generated integer ID: one goal ID and revision, registered operator, brief, exact skill revisions and workspace input. A changed brief creates a new work item. |
| Work attempt | A prepared execution of a work item, identified by a caller-selected string ID within its workspace database. Preparation persists the ID before any execution. Repeating preparation for that work item returns the same attempt. An intentional execution retry uses a fresh attempt ID under the same work item. |
| Attempt grant | Authority bound to one attempt and its credential. It permits the four worker MCP operations while the registered operator, open goal and bound revision remain valid. A withdrawn or replaced grant does not authorize an old credential. |
| Workspace input | Either an empty directory or an isolated checkout of a local source repository at the recorded base SHA. The person launching the workload prepares its scratch directory or isolated checkout and keeps the original checkout separate. The trusted owner binds that directory to the attempt for submissions. |
| Work artifact | An independent copy of the submitted file's bytes in the workspace database, with a generated ID, relative path, SHA-256, size and worker attribution. Its metadata retains the checkout base SHA when one was assigned. |
| Worker call | An audited worker MCP operation with its attempt, grant, arguments, timestamps and `returned`, `denied` or `failed` outcome. A successful submission links the saved artifact. |

Worker MCP exposes `get_work_brief()`, `list_skills()`,
`read_skill(id, revision)` and `submit_work_result(relative_path)`. Skill reads
are limited to the exact revisions assigned to that work item. The trusted host
reads a regular file inside that attempt's mounted workspace and commits its
independent copy before acknowledging a submission.

Scratch bindings reserve disjoint resolved directories within the workspace
database. Binding checks equal, ancestor and descendant paths in the write
transaction, including on retry. Symlink aliases resolve to the same directory.
`WorkAPI.get_attempt_details` reads the attempt, work item, worker calls and
artifact metadata from one SQLite read snapshot, so inspection remains coherent
when a submission commits concurrently.

The first successful save is authoritative. An authorized retry with the same
relative path returns the original artifact ID without rereading scratch, even
after cleanup or changes to the scratch file. A different path conflicts and
leaves the saved artifact intact. A source fix, ordinary patch and test report
use this same file handoff; the model does not infer test success from their
contents.

Preparation, execution outcome and artifact submission are separate facts. An externally run attempt may have no recorded container, image or exit code. The attempt ID is a lookup key. Its credential, saved in a private runtime file by the owner CLI, establishes worker authority. Revocation or replacement invalidates the old credential on every request.

Container exit code and artifact submission are separate recorded outcomes.
Neither completes or revises the goal. The operator reviews the retained result
and makes any completion decision separately. [Worker commands](CATALOG.md#worker-assignments)

A **Phase 2 experiment receipt** records CLI-created goal, revision, work item and
attempt identifiers alongside the exact rendered job digest and observed Nomad
allocation outcome. Assignment criteria live under `fixture`, and scheduler and
worker observations live under `execution`. Required Slice 11 acceptance records
one real Codex worker session, zero AI operator sessions and the artifact saved
through authenticated worker MCP. The owner retrieves that artifact through
Harness after worker exit and scratch cleanup. Optional scripted smoke tests
record their scheduler results in their own receipts. [Slice 11 experiment](docs/phase2/SLICE11.md)

The container worker uses Codex `danger-full-access`, with isolation supplied by
the container user, mounts and Docker's security profiles. A terminal experiment
receipt retains its allocation and exit before teardown. `verify_pending` retries
the final Harness export, and `cleanup_pending` retries teardown. An interrupted
active run is stopped and its exact runtime is cleaned up. Executing the workload
again uses a fresh attempt. Runtime process identity and grant ownership let
recovery target that run's listener, credential and private files.

A **Slice 12 service receipt** links one submitted script artifact, its digest,
producing attempt and goal revision to a separate consuming Nomad service job.
The development checkpoint retrieves and verifies the artifact after worker
cleanup, stages it read-only and renders the service job. Explicit submission
starts its independent lifetime. Startup, deliberate drift and shutdown are
separate external observations with recorded samples and elapsed times. They
leave the standing goal active. The service uses a shell image and disposable
data without Codex or worker MCP authority. This experiment adds no Harness
deployment model. [Slice 12](docs/phase2/SLICE12.md)

The standing file-mode goal records `duration: standing` through the owner CLI.
Its experiment checks that field and the original active revision before
deployment and after observation. The drift deadline starts at the deliberate
mode reset, after persisting the observation intent. Submission sends the exact
job bytes validated against the checkpoint digest.

The service receipt identifies each original disposable regular file by device
and inode. Its `cleanup_pending` phase records that shutdown observation and
artifact verification succeeded. The receipt reaches `finished` when teardown
also succeeds.

A **Slice 13 activity capture** is the host's copy of one attempt's Nomad task
streams, stored under `phase2/activity/ATTEMPT_ID/`. It records what the reader
observed and when. The stdout JSONL is the worker's own account and cannot
replace the worker MCP audit. A claimed submission is checked against the audited
call and saved artifact. A `complete` capture was drained before allocation
cleanup and has a recorded task outcome. An `incomplete` capture keeps every
readable event. Capture status, task outcome and submission are separate facts,
and none of them changes the goal. [Slice 13](docs/phase2/SLICE13.md)
