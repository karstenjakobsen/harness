Engineering handoff · Goal Operator V1

Build a CLI application where a human can give an AI operator a goal in ordinary language, return later with new information, and see what was agreed, who is responsible, and what evidence supports the current assessment. Several named operators can work for the same user. The user owns the goal, and at most one operator can manage it at any instant. Deliver the following slices in order. Each slice must be demonstrable through the CLI.

System boundaries

Component

Responsibility

CLI

Accept human messages and explicit commands. Show the operator’s reply, goal ID, assigned operator, and history.

Operator

Interpret intent, inspect existing goals, identify overlap or conflict, ask for clarification, and propose or apply goal changes through MCP. Load the operator’s configured mission at the start of each session.

Operator API

Own goal IDs, lifecycle rules, authorization, assignments, revisions, and event recording. Implement it as a Python application service shared by the CLI and MCP server. V1 can run locally without a separate HTTP service.

MCP server

Expose the application service as typed tools such as search_goals, get_goal, create_goal, revise_goal, and record_assessment. Bind the human or operator identity to the session. Tool arguments cannot select an actor identity.

SQLite

Persist goals, relationships, assignments, and the evidence trail across restarts. Application code owns all database access.

Use Codex as the first operator adapter. Keep the adapter replaceable so tests can drive the same MCP tools deterministically. This project ends at defining, managing, and assessing goals. Leave the existing harness POC untouched. Worker execution, Nomad submission, catalogs, host inspection, scheduling, and a web UI are outside this build.

Slice 1 — Start a conversation and recover it

Build the smallest path from a CLI message to a persisted goal conversation and an operator reply. When a message arrives without a goal ID, create a draft goal and store the original message in the same transaction. A draft gives discovery and clarification a goal ID before the operator knows whether the request describes a new goal. When the user supplies a goal ID, attach the message directly to it.

Record application-mediated reads, searches, writes, messages, and decisions as append-only events. Include the goal in whose context the action occurred, actor, time, action, and outcome. A search records its query and returned goal IDs. A read records the target and revision returned. Keep state changes and their events in the same transaction. Reading history records one read event at the API boundary.

Pass when a user can start a conversation, exit, resume it by goal ID, and retrieve the original exchange and tool activity in order. A draft awaiting clarification stays out of the active goals list.

Slice 2 — Assign one operator at a time

Support named operators, claim, release, and explicit handoff. Any operator belonging to the user can discover that user’s goals. The user can send input and transfer responsibility. Require a current assignment for operator changes to a goal. Check its ID on every change so a delayed command from an earlier assignment cannot succeed, even if the same operator later reclaims the goal.

Enforce one open assignment per goal in SQLite with a partial unique index on goal_id where released_at IS NULL. Make handoff atomic and preserve the assignment history. When input concerns a goal held by another operator, record it as user input and route it to the assigned operator. Scope goal lookup and assignment to the owning user.

Pass when two operators racing to claim one goal produce exactly one winner. After handoff from Alice to Bob, Bob can revise the goal, Alice’s outstanding write is rejected, and the user can see the transfer. One operator can hold two different goals.

Slice 3 — Resolve intent before creating an active goal

Give the operator MCP tools to search existing goals and inspect their definitions. On new user input, have it check relevant ongoing goals, including paused goals and those awaiting input. It can answer a question, attach the conversation to an existing goal, revise a goal, activate a new one, or ask a focused question when instructions conflict. Record the goals considered and a short decision rationale. Preserve the intake draft and link it to the selected goal when reusing an existing one.

A goal definition contains a desired outcome, scope, success criteria, and whether it is one-time or standing. Preserve the original request. Revisions record what changed, who changed it, and why. Reject writes based on a stale revision. Reusing a goal held by another operator preserves its assignment.

Pass when “Keep the config file readable and writable only by its owner” and a later “Keep that same file at mode 0600” resolve to one active goal. “Make the same file readable by everyone” prompts clarification and leaves the existing definition intact until the conflict is resolved. The operator never touches the file in this exercise.

Slice 4 — Change how achievement is measured

Support objective checks, human judgment, and a combination of both. A measurement plan states what will be observed, the source, and when a review is due if applicable. Let the user provide input later. Store observations with source, observation time, and recording time. Each assessment cites the definition revision and the observations or user feedback supporting it. Keep a standing goal active after a favorable assessment. Show missing evidence as unknown.

Pass when a user defines a standing weight-tracking goal using manual Sunday readings, then changes the source to a connected scale. The goal ID stays the same. Earlier readings and assessments retain the original plan and source. Accept a sample scale observation through the API. Connecting to a real scale is outside the test. Also demonstrate a qualitative goal assessed from a user’s written feedback.

Slice 5 — Relate, revisit, and revoke goals

Support subgoals, dependencies, and small tasks. A subgoal has its own outcome, assignment, and history. A task is a checklist item belonging to one goal. Allow one parent and multiple dependencies. Reject containment and dependency cycles. Expose goal history, relationships, and goals awaiting input or due for review through the CLI.

Support pause, resume, completion, and revocation. Revocation is terminal, closes the active assignment, and preserves the full history. Reversing the effects of earlier work requires a new goal linked to the old one with mitigates. Record who requested the mitigation and why.

Pass when a user can inspect a parent goal, its subgoal, a dependency, and a task. After revocation, an outstanding operator command is rejected, the old evidence remains readable, and the mitigation can be managed independently under a new ID.

Slice 6 — Reserve the Nomad link and prove the handoff

Add a goal_runs table with an application-owned run_id, goal_id, goal revision, and fields for the Nomad job and allocation IDs. One run belongs to one goal. A goal may accumulate several run records over its lifetime. Goal creation and management must work with an empty table and Nomad offline.

Pass when a database test links two example runs to successive attempts for one goal and rejects an unknown goal ID. No production CLI command in this release launches a workload.

Data model and delivery

Use migrations for users, operators, goals, goal_revisions, goal_assignments, goal_links, goal_tasks, goal_events, and goal_runs. Give each revision a unique (goal_id, revision) key. Events can hold conversation entries, observations, assessments, and tool activity with typed payloads and explicit references. Keep the current lifecycle state separate from the latest assessment so “active, awaiting input” and “active, criterion met” are both representable.

Ship a README with setup, CLI examples, the MCP tool contract, and commands for tests and a live demonstration. Use a temporary SQLite database and real application boundaries for automated tests. Include one credentialed Codex walkthrough from a natural-language request to a persisted goal and a follow-up. Record which checks used a fixture and which used the live operator.

An engineer with just the goal ID should be able to answer what the user asked for, who owns the next decision, what changed, and what evidence supports the current assessment.