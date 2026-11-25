# Harness terminology

## People and interfaces

| Term | Meaning in Harness |
| --- | --- |
| User | A workspace account with a user ID. The protected system account is `admin`. |
| Owner | The user related to a particular resource by its `owner_user_id`. |
| Registered operator | A workspace record with its own numeric ID, an owning user and optional goal assignments. |
| Assistant | The Codex session that answers `operator ask` or drafts a goal definition. The CLI executable is named `operator`. |
| Workspace | The context for a set of goals. Local commands use the workspace database. HTTP commands address the workspace served by the selected API server. |
| Schema snapshot | The complete SQLite schema and initial system user in `001_initial.sql`. SQLite’s `user_version` records the schema version installed in each workspace. |
| GoalAPI | The public Python interface for goal operations. It owns the rules shared by the HTTP, CLI, and MCP adapters. Use “HTTP API” when referring specifically to the network interface. |

## Identity and attribution

| Current entry point | What the application establishes |
| --- | --- |
| Goal CLI and HTTP endpoints | `GoalAPI` scopes goals to the workspace account identified by `ADMIN_USER_ID`. CLI completion stores that account as `recorded_by`. In message-based creation, Codex drafts the definition and the CLI saves it through `GoalAPI` in the same account. |
| Account CLI and HTTP endpoints | A user or operator ID selects the target record. Named registration assigns the owner from `--user` or HTTP `owner_user_id`, defaulting to `admin`. These operations record no separate initiating identity. |
| Bare `operator register` | Starts Codex sign-in. Named registration creates a workspace operator record. |
| `operator ask` and MCP | The assistant reads saved goals through the admin-scoped MCP goal tools. Asking selects no registered operator ID. |

The current HTTP endpoints do not establish who initiated a request. A resource ID identifies its target, `owner_user_id` identifies its owner, and `ADMIN_USER_ID` identifies the workspace account. For evidence writes, record a submitter only from established caller context. Record the requester of a check and the observer that produced the result separately when known. Leave unknown identities explicit. An owner pasting an app link supplies a reference. Attributing an observation to the app requires a report from the app itself.

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
| Completion | A decision that a specific goal revision met its criteria. The current implementation records the actor, time, and either an owner confirmation or an owner-supplied reference. |

## Evidence, assessment, and audit

Today, Harness stores evidence with a completion event. The following terms also guide design of the planned first-class evidence layer.

| Term | Question it answers | File-mode example |
| --- | --- | --- |
| Observation | What did a person or interface report, and when? | At 10:00 the file check reported mode `0600` for the specified path. |
| Evidence | What information supports a claim, and where did it come from? | The file check's response supports a claim about the mode at 10:00. A link pasted by the owner has owner-supplied provenance. |
| Assessment | What does the evidence establish against this revision's criteria? | The standing goal met its condition at 10:00. Its lifecycle status is still `active`. |
| Audit record | Who performed which action in Harness, and when? | At 10:05 the owner recorded an observation made at 10:00. |

A successful HTTP response supports only the claim defined by that endpoint. A health check can establish reachability. A file-mode check can establish the mode of the file it inspected.
