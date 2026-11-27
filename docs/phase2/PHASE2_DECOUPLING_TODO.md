# Phase 2 prerequisite — Separate attempt preparation from worker execution

An owner can prepare and inspect a worker assignment on a machine with neither Docker nor Nomad available. Preparation persists an attempt ID that can be used later, including when execution never happens. Complete this checklist before running the Slice 11 experiment. [Phase 2 plan](phase2.md) · [Slice 11 experiment](SLICE11.md)

## Establish the Phase 2 boundary

- [x] Move slice documents through Slice 10, including their TODOs, reviews, evidence scripts and captured outputs, into `docs/phase1/`, or verify the existing archive move. Fix links to and within the archive and evidence-script paths so they resolve from the new location.
- [x] Point root `AGENTS.md` to the active Phase 2 plan and this prerequisite checklist. Add the explicit rule “During Phase 2, Harness prepares attempts and serves worker MCP. We launch workloads ourselves by rendering Jinja and submitting the job directly to Nomad.”

## Retire Harness worker dispatch

- [x] Remove `operator work start` from CLI registration and delete its production `DockerWorkerLauncher` dispatch and recovery path.
- [x] Find all launcher callers and imports, including `operator work show`, live fixtures and Make targets. Update each affected caller when removing the launcher.
- [x] Verify that production CLI, HTTP, MCP and model entry points cannot dispatch a worker. Keep the Slice 9 cluster setup and backend proof callable through their existing development tests.
- [x] Retire tests that depend on the deleted launcher. Preserve coverage for the generic worker entrypoint, attempt authority, skill reads, saved artifacts and audit.

The owner adapter exposes preparation, manual handoff setup and persisted inspection. The production Docker launcher has been removed. [Click adapter](../../packages/harness_operator/src/harness_operator/commands/work.py)

## Prepare attempts through the public model

- [x] Add `operator work prepare WORK_ITEM_ID --attempt-id ID` as a thin Click adapter around `WorkAPI.create_attempt(attempt_id, work_item_id)`.
- [x] Return JSON containing the work item ID and attempt ID so a later process can consume them.
- [x] Preserve the existing model behavior for an identical retry. Preparing the same attempt ID for the same work item returns the original attempt, and reusing that ID for another work item fails.
- [x] Preserve model validation of the work item's goal revision and registered operator when creating an attempt. Keep related validation and writes inside the model transaction.
- [x] Make preparation succeed without an image, scheduler endpoint, scratch directory, runtime credential or Codex login.
- [x] Verify that preparation records the work item binding and creation time with an empty execution outcome.

Reuse the existing work model and its retry semantics. [WorkAPI](../../packages/harness_api/src/harness_api/models/work.py)

## Read persisted attempts and results

- [x] Change `operator work show ATTEMPT_ID` to read the attempt, work item, worker calls and saved artifact metadata through the public Harness API.
- [x] Read the full inspection through `WorkAPI.get_attempt_details` in one SQLite read transaction. Exercise submissions committing during and between inspection reads.
- [x] Support prepared attempts with no launch, calls or artifact, and externally run attempts whose runtime fields are absent.
- [x] Preserve reads of saved attempts, calls and artifacts after reopening the workspace in a fresh process, including records with saved runtime metadata.
- [x] Preserve `operator work artifact GOAL_ID --output NEW_PATH` and retrieval of saved bytes after scratch cleanup.
- [x] Keep execution outcome and artifact submission independently observable. Verify the goal remains at its original revision and status after preparation or artifact submission.

## Expose worker MCP and manual handoff setup

- [x] Expose the existing worker MCP app through an independently invocable server entry point using an explicit Harness workspace destination.
- [x] Preserve the generic worker image and `harness-worker run --attempt-id ID` entrypoint for externally initiated execution.
- [x] Add trusted-owner CLI commands to bind per-attempt scratch through `WorkAPI.set_scratch` and issue and revoke the existing attempt credential through `WorkAPI.grant_attempt` and `WorkAPI.revoke_attempt_grant`, separately from preparation. Credential issuance writes directly to a private runtime file.
- [x] Reject equal, ancestor and descendant scratch bindings across attempts in the binding transaction, including resolved symlink aliases. Test both binding orders and concurrent binding attempts.
- [x] Document one copyable shell command sequence that binds scratch, issues the credential to a private file, starts worker MCP against the seeded workspace and revokes the credential afterward. Specify the workspace destination consistently across all commands, the credential file permissions and the server shutdown step. Make this sequence reusable by Slice 11 through installed CLI entry points, with zero AI operator sessions and zero imports of Harness internals.
- [x] Store credentials in a private runtime file. Verify seed JSON, command output, logs and audit records exclude credential values.
- [x] Derive the worker's attempt and exact grant from its authenticated session. Treat the attempt ID as a lookup key and require the credential for worker access.
- [x] Preserve `get_work_brief()`, `list_skills()`, `read_skill(id, revision)` and `submit_work_result(relative_path)`, with skills scoped to assigned revisions and authority rechecked on every call and retry.
- [x] Preserve worker call audit and artifact attribution to the attempt, work item, goal revision, registered operator and exact grant.
- [x] Verify revoked or replaced credentials stay denied, including after a new grant is issued. Retain coverage for invalid credentials, cross-attempt access and stale goal revisions.
- [x] Retain artifact path containment, atomic save and retry coverage. The first saved bytes remain authoritative after scratch changes or cleanup, and conflicting paths and failed saves preserve the saved result.

Reuse the worker MCP app and existing attempt operations. [Worker MCP](../../packages/harness_mcp/src/harness_mcp/worker.py) · [Work model tests](../../packages/harness_api/tests/test_work.py)

## Update commands, documentation and test targets

- [x] Update the command catalog with preparation, persisted inspection and the chosen manual handoff entry points.
- [x] Update terminology for work attempts, workspace input and owner attribution to match the decoupled lifecycle.
- [x] Update README examples and prerequisites for offline preparation and independently served worker MCP, including the complete manual handoff command sequence used in acceptance.
- [x] Update Make targets and live test selection so they use supported entry points and cease advertising the retired launch command.
- [x] Preserve the Slice 10 baseline's unresolved host namespace failure in the recorded history when changing live targets. Describe which live scenarios remain runnable and how they are invoked.
- [x] Check production documentation and help text for remaining references that advertise the retired launch path.

[Command catalog](../../CATALOG.md) · [Terminology](../../TERMINOLOGY.md) · [README](../../README.md) · [Makefile](../../Makefile) · [Slice 10 evidence](../phase1/SLICE10_EVIDENCE.md)

## Acceptance and verification

With Docker and Nomad offline, prepare an attempt, read its brief over MCP, submit a real file and recover it after scratch cleanup. Exercise the documented CLI sequence and a protocol-level MCP client with zero model sessions and no Codex login.

- [x] Add a focused CLI regression test showing preparation and inspection succeed with Docker, Nomad and Codex unavailable. Use an isolated temporary workspace and separate CLI processes.
- [x] Register a named operator, create a goal with explicit fields, and create a work item using the returned operator ID, goal ID and revision.
- [x] Prepare the work item, repeat preparation with the same attempt ID, and inspect it in a later CLI process. Assert valid JSON identifiers, one persisted attempt, the saved goal revision and an empty execution outcome.
- [x] Create another work item and attempt to prepare it with the same attempt ID. Assert a conflict and that the original binding remains intact.
- [x] Check `operator work --help` for supported commands and directly invoke the retired `operator work start` command. Assert that invocation fails without dispatching anything.
- [x] Use the documented command sequence to bind scratch, issue the credential to a private file and start worker MCP against the same seeded workspace while Docker and Nomad are offline. Check the runtime file permissions and that command output excludes the credential.
- [x] Connect an MCP client using that credential, call `get_work_brief()` and assert the seeded brief and assignment identifiers. Write a real file into the bound scratch and submit it through `submit_work_result(relative_path)`.
- [x] Remove the attempt scratch, then retrieve the saved artifact through `operator work artifact` in a fresh owner process. Assert the exact file bytes, audit calls and attribution, the original goal revision and status, and an empty execution outcome.
- [x] Finish the documented sequence by revoking the credential through the CLI. Verify subsequent MCP access with that credential is denied, the saved artifact remains retrievable, and the standalone server shuts down cleanly.
- [x] Verify opening a fresh database and reopening one containing saved work items, attempts, calls and artifacts through the public API.
- [x] Run `make check` and `make test` and record their actual results.
- [x] Run the applicable signed-in live checks when changing live operator behavior. Report live results separately, including any checks that could not run and their blockers.
- [x] Review the completed cut against every requirement in `phase2.md` and record the implementation's verification results before proceeding to Slice 11.

## Verification record

Implemented and verified on 2026-11-26. `make check` passed, and `make test` passed
233 tests. The evidence script also ran the README handoff sequence against real
HTTP worker MCP. The signed-in suite reported seven passes and one reply-matching
failure. The failed scenario passed on a focused retry, exercising both evidence
turns. [Captured results](PHASE2_DECOUPLING_EVIDENCE.md) · [Evidence script](PHASE2_DECOUPLING_EVIDENCE.sh)
