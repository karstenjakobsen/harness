# Slice 3 — Record progress and explain it

An owner can ask “What progress have I made, and how do we know?” The source reports an observation, the model decides what it establishes against a goal revision, and MCP exposes the result for the assistant to explain. Both the food goal in 3A and the standing file goal in 3B can stay `active` as evidence arrives. [Slice 3 discussion](SLICE3.md)

## Agreed decisions

- **Historical progress.** `get_goal_progress(goal_id, revision=N)` evaluates revision N’s criteria using the evidence available now. A report about Monday submitted on Tuesday can count for N. A saved completion returns the original revision, statement and exact citations. A historical recording-time cutoff would need an explicit `as_of` read.
- **Criteria.** The first rule is **count distinct reported dates**. Food logging is its acceptance example. A date qualifies when its owner confirmation was recorded on or after that date in UTC. For a bounded rule, both ends of the window are inclusive. It starts on `window_start` or the goal’s UTC creation date and ends `duration_days - 1` calendar days later. The target can change independently of the window.
- **A revision during a file check.** Capture the revision, configured source, path and expected condition when the check starts. Persist the result against that original check, including when the owner revises the goal before the response arrives. A successful check of `/app/a` only establishes the condition of `/app/a`.

## 3A — Record and explain owner-supplied evidence

- [x] Store observations independently of completion under a stable goal ID and the revision in force at submission. Preserve what was reported, its source, reported date, recording time and known identities. Give each report a stable evidence ID and retry key. An identical retry returns the original record. A conflicting reuse fails.
- [x] Establish attribution at each entry point. The local owner supplies confirmations and references. HTTP writes keep an unknown caller explicit. A pasted app link retains its supplied provenance. [Identity and attribution](../TERMINOLOGY.md#identity-and-attribution)
- [x] Extend completion with optional evidence IDs alongside the existing confirmation or reference. Validate the current revision and citations, save the statement and decision, and change status in one transaction. Identical retries return the original decision. Conflicting or stale requests leave the records untouched.
- [x] Require a fresh database for schema version 7. Reopening an incompatible workspace reports its version and preserves the file. [Workspace setup](../README.md#saved-goals)
- [x] Assess distinct reported dates in the model. Return all records considered in `evidence` and the qualifying IDs for each date in `days`. Reject new future-dated reports at submission. Prose-only goals return their evidence and an unavailable automatic assessment. Return revision creation and evidence submission times in history. Reads and reports preserve lifecycle status.
- [x] Expose criteria, observation, progress, history and completion through the public model, workspace CLI and HTTP. MCP exposes a read-only progress operation. [Command catalog](../CATALOG.md#workspace-goals)
- [x] Verify the Monday example through the Python model, installed CLI and signed-in operator. Two reports count as one of seven days, then one of fourteen after revision. The answer attributes and cites both records and reports the goal as active. Inspect the successful MCP call and structured result for the captured goal ID. Verify fixed completion citations, retries, stale revisions, foreign evidence rejection and late evidence for an earlier revision.
- [x] Run `make check`, `make test` and the separate signed-in `make test-live`. The live workspaces and traces are temporary. [Model tests](../packages/harness_api/tests/test_goal_progress.py) · [Operator acceptance](../packages/harness_operator/tests/test_goal_plan_live.py)

Review the 3A model rules and acceptance results before starting 3B.

## 3B — Collect and explain machine observations

- [ ] Add structured criteria for a configured source, path and expected octal mode. Expose an owner-triggered `operator goal check`. Only the collector can submit machine observations. Preserve the requester separately from the interface that observed the result.
- [ ] Capture the original check inputs and fetch outside the database write transaction with a bounded timeout. Validate the returned source, path and mode. A dedicated endpoint can establish a condition with HTTP 200 when its configured contract guarantees it. Store that basis. A generic health response, malformed payload or timeout yields `unknown`.
- [ ] Return the latest check outcome and the last successful observation with their timestamps. Keep the goal active. Use a controlled clock and a local HTTP fixture that reads the actual mode of a temporary file.
- [ ] Test `0600` at 10:00 (`met`), then `0644` at 10:05 (`unmet`), then a timeout at 10:10 (`unknown`). Preserve `0644` at 10:05 as the last observed mode.
- [ ] Add a deterministic in-flight revision test. Hold the response for `/app/a`, revise the path to `/app/b`, then release the successful response. Verify the stored revision, source, path and expected condition, and verify that progress for `/app/b` still lacks a qualifying observation.
- [ ] Exercise the fixture through the installed CLI and signed-in operator in a temporary workspace. Assert a successful MCP read, the structured result, both citations, the interval during which the mode changed, and the last known mode after timeout. Use observed timestamps in the live test and keep expected facts out of the question. Clean up the database, trace, temporary file and server on success and failure. Run all three checks and report the signed-in result separately.
