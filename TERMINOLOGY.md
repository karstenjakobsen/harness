# Harness terminology

## People and interfaces

| Term | Meaning in Harness |
| --- | --- |
| User | A workspace account with a database-generated integer ID, a unique username and a display name. The protected system account is `admin` (ID 1). |
| Owner | The user related to a particular resource by its `owner_user_id`. |
| Registered operator | A workspace record with its own numeric ID, an owning user and optional goal assignments. |
| Assignment | The recorded relationship between a goal and the registered operator responsible for it. Unregistering the operator releases its open assignments. Completion authority requires an explicit grant. |
| Delegation | The owner’s explicit grant of a specific action on a specific goal to a registered operator. A completion grant uses the ID of the assignment created when the owner grants completion of one subgoal. |
| Assistant | The Codex session that answers `operator ask` or drafts a goal definition. The CLI executable is named `operator`. |
| Workspace | The context for a set of goals. Local commands use the workspace database. HTTP commands address the workspace served by the selected API server. |
| Schema snapshot | The complete SQLite schema and initial system user in `001_initial.sql`. SQLite’s `user_version` records the schema version installed in each workspace. |
| GoalAPI | The public Python interface for goal operations. It owns the rules shared by the HTTP, CLI, and MCP adapters. Use “HTTP API” when referring specifically to the network interface. |

## Identity and attribution

| Current entry point | What the application establishes |
| --- | --- |
| Goal CLI and HTTP endpoints | `GoalAPI` scopes goals to the workspace account identified by `ADMIN_USER_ID`. Local owner writes use that account as `submitted_by` for reports and `recorded_by` for completion. HTTP writes have no established caller and return null for those identities. In message-based creation, Codex drafts the definition and the CLI saves it through `GoalAPI` in the same account. |
| Account CLI and HTTP endpoints | A numeric user or operator ID selects an existing record. Named registration assigns the owner from `--user` or HTTP `owner_user_id`, defaulting to `admin`. These operations record no separate initiating identity. |
| Bare `operator register` | Starts Codex sign-in. Named registration creates a workspace operator record. |
| Ordinary `operator ask` and MCP | The assistant reads saved goals through the admin-scoped MCP goal tools. |
| `operator ask --completion-grant GRANT_ID` | The assistant can also complete the specific subgoal covered by the active grant. Harness derives the registered operator from the grant. |

In a delegated session, Harness binds the assistant to a registered operator and a specific grant at startup. A replacement grant requires a fresh session. The **decision maker** is the actor who exercises the delegated authority. The **evidence submitter** is the actor who supplied a cited record. If the owner confirms “My membership is active” and an operator uses that confirmation to complete the subgoal, the evidence keeps the owner’s user ID and the decision records the registered operator’s ID. These IDs refer to different tables and can have the same numeric value. [Delegated completion plan](docs/SLICE3_TODO.md#delegated-completion)

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

A successful HTTP response supports only the claim defined by that endpoint. A health check can establish reachability. A file-mode check can establish the mode of the file it inspected.

The local workspace CLI and default Python model operate as the workspace owner. A confirmation has source `owner_confirmation` and identifies that owner as submitter and observer. A pasted reference has source `owner_supplied_reference`, identifies its submitter and leaves the original observer unknown. An adapter without an established caller uses `GoalAPI(path, local_owner=False)`, as the HTTP service does. Its reports have source `unattributed_confirmation` or `unattributed_reference`. Unknown identities are null. Owner-input reports have no check requester. A retry key is scoped to the goal and submitting identity, with one scope for unattributed requests.

**Count distinct reported dates** groups dated owner confirmations by `reported_date` and retains each supporting evidence ID. The rule compares the number of qualifying dates with `target_distinct_dates`. `duration_days` optionally limits those dates to an inclusive window starting on `window_start` or the goal’s UTC creation date. A one-day window includes only its start date. The model returns `met` or `unmet` for this rule and `unavailable` for prose-only criteria.

Progress returns every record considered in `evidence`. Only the IDs grouped under `days` contribute to the distinct-date count. For example, a dated HTTP confirmation with an unknown submitter appears in `evidence` and contributes zero days.

An observation’s reported date may be at most the UTC calendar date when Harness records it. Earlier versions accepted advance reports. These retain their IDs, retry results and citations, and are excluded from the count even after the reported date passes.

Historical progress applies the selected revision’s criteria to the evidence available at read time and returns the goal’s current lifecycle status. A completion with a confirmation or reference keeps its original `statement_evidence_id` and the additional citations in `evidence_ids`. A delegated completion stores `recorded_by_operator_id`, `completion_grant_id`, `rationale` and the exact cited IDs in `evidence_ids`.
