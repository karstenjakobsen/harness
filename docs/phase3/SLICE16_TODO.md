# Slice 16 — Delegate a work item against a specific goal revision

Implement `WorkAPI.delegate_work(...)` in `packages/harness_api`. A registered
operator with an explicit grant can save an immutable assignment against the
goal revision it reviewed. The saved work item identifies the operator, exact
grant and committing call. An authorized replay recovers the same work item.
[Slice 16 design](SLICE16.md)

This checklist implements the final, model-only proposal in the design. Worker
launch, engine/model/effort selection, provider credential records and delivery,
Nomad rendering, and new CLI, HTTP or MCP operations remain future work. Creating
a work item creates zero attempts and leaves the goal definition and status
unchanged. Acceptance runs in Python against temporary SQLite without Docker,
Nomad, an MCP server or an AI session.

Production code and tests for Slice 16 belong in `packages/harness_api`.
Existing CLI and MCP callers continue to work through their current contracts.

## Public contract and authority

- [ ] Add `WorkAPI.delegate_work(goal_id, expected_revision, brief, workspace_input, retry_key, *, call) -> WorkItem`. Use the existing public `CallReference` to identify a durably recorded operator call. Derive the operator and exact grant from its trusted run binding; accept no caller-selected operator or grant as delegation authority.
- [ ] Define and export the workspace-input type through `harness_api.__all__`. Represent either an empty workspace or a requested source repository with an absolute source path and full pinned commit SHA, stored as `source_path` and `base_sha`. Reject relative paths rather than resolving them against the caller's working directory. Accepting the request authorizes no repository access: do not read the repository, create a checkout or scratch directory, or introduce a repository catalog. Repository access authorization belongs to a future launch operation. Keep exact skill guidance compatible with existing work items; this operation takes the brief and workspace input specified in the design.
- [ ] Add the minimal owner model operations to grant and withdraw `delegate_work` for one goal and registered operator. Bind recorded runs to that exact grant through the public API. A grant for a parent does not implicitly cover its children, and a goal assignment, completion grant or definition grant does not authorize delegation.
- [ ] Recheck the call, run, exact grant, registered operator, workspace ownership, target goal and expected revision inside the write transaction, including on replay. Require an unfinished matching call in an unfinished run, with the correct tool, target and revision. Reject advisory runs, missing or mismatched calls, withdrawn grants, unregistered operators, inaccessible goals and stale revisions.
- [ ] Preserve the current work-item rule that the goal must be open (`draft`, `active` or `paused`). Withdrawing and regranting authority must leave the old run denied; unregistering an operator must invalidate its delegation authority without deleting earlier work or attribution.

[Work model](../../packages/harness_api/src/harness_api/models/work.py) ·
[Recorded runs and delegated-write patterns](../../packages/harness_api/src/harness_api/models/goals.py) ·
[Operator lifecycle](../../packages/harness_api/src/harness_api/models/accounts.py)

## Atomic persistence and replay

- [ ] Reuse the existing work-item validation and persistence within one model transaction. Keep the trusted-owner `create_work_item` operation working for its existing callers. Avoid composing independently committed public writes to implement delegation.
- [ ] Save the work item, its exact goal revision, operator, grant, retry record and committing-call relationship atomically. Store the immutable brief and requested workspace input. A failed insert or audit-link write must leave none of those new records committed.
- [ ] Enforce at most one committed work item per recorded call, with a uniqueness constraint on the committing `(run_id, sequence)`. Reject reuse of a call that already committed an item, even if its reply is unfinished and the new request uses a different retry key. A genuine retry requires a new recorded call.
- [ ] Scope retry keys to the exact delegation grant and fingerprint all assignment inputs: goal ID, expected revision, brief and normalized workspace input. Validate nonempty keys. An identical authorized request returns the original ID; changed inputs with that key raise a conflict. A fresh key creates a new work item, including for a changed brief.
- [ ] Recheck authority and the current goal revision before returning a saved retry. After withdrawal, unregistration or revision change, replay must not recover authority or create another item. A goal revision change rejects even an identical replay; the committed item remains discoverable through history, so recovery after a lost reply may require a history read. A new grant must not retrieve an old grant's retry record.
- [ ] Preserve the original committing call on replay. A retry uses a separate recorded call that identifies the work item it retrieved. Concurrent identical requests under the same grant and key must leave one work item and one original committing call.
- [ ] Extend the unversioned `schema.sql` directly with the necessary grant, run-binding, retry and call relationships and constraints. Initialize empty workspaces from it and reopen saved workspaces as they are. Use a fresh workspace after an incompatible change; add no migration framework.

[Schema](../../packages/harness_api/src/harness_api/schema.sql) ·
[Existing work-model tests](../../packages/harness_api/tests/test_work.py)

## Inspectable attribution

- [ ] Expose the delegation grant and original committing-call reference through public model reads of the work item. Preserve unknown or absent delegation attribution for work items created through the existing owner operation.
- [ ] Extend the recorded-call model to recognize `delegate_work` and distinguish committed from retrieved work-item references. Starting with the work item, follow its goal revision, operator, exact grant, run and call; starting with the run, identify the same work item. A commit remains inspectable when reply recording never finishes.
- [ ] Keep already persisted denied or failed call attempts visible without a committed work-item reference. Preserve existing goal revisions, observations, decisions and call history after denial or rollback. Record IDs, timing and outcomes using the existing activity conventions; avoid adding raw prompts, briefs, responses or secrets to call history.
- [ ] Update affected shared types, exports and model activity serialization within `packages/harness_api`. Preserve existing HTTP, CLI and MCP contracts and their current callers. Expose the new attribution through public Python model reads without requiring adapter changes. Add no delegation transport, tool discovery or tests outside `packages/harness_api` in this slice.

[Activity model](../../packages/harness_api/src/harness_api/models/activity.py) ·
[Public exports](../../packages/harness_api/src/harness_api/__init__.py)

## Acceptance through the public Python API

Use isolated temporary workspaces, real SQLite transactions and small fixtures.
Create users, operators, goals, grants, runs and call attempts through public
model operations. Use a narrow failure injection only where needed to prove
rollback; tests should assert saved results and history.
Reuse existing validation and owner-work-item tests, parameterize authority
denials, and retain separate real SQLite tests for concurrency, rollback and
lost replies. The evidence script reuses these focused tests.

- [ ] **Delegate and reopen.** Delegate once under a valid goal-scoped grant. Reopen the workspace and verify the exact brief, workspace input, goal revision, operator, grant and committing call. Cover empty input and a pinned source input. Verify zero attempts and no goal or parent change.
- [ ] **Replay and conflict.** Replay through a new call with the same key and inputs, including after reopening and after a lost reply. Assert one ID and preserved original attribution, with a retrieval reference on the retry. Change the brief, workspace input or revision under the same key and verify rejection without another item. Use a fresh key to save a revised brief as a separate item.
- [ ] **One commit per call.** Commit a work item, leave its reply unfinished, and present that same call again with a different retry key. Assert rejection, one work item, no second retry record, and an intact original commit link. Then retry with a new call and the original key and verify retrieval of the original item.
- [ ] **Authority boundary.** Cover another goal, another owner's goal or operator, an assignment without a grant, an advisory run, an unrelated action grant, and missing or mismatched call context. Withdraw a grant after run start, deny both a new request and replay, regrant the action, and verify the old run remains denied. Verify a fresh run bound to the replacement grant can delegate within its scope.
- [ ] **Revision and lifecycle.** Revise the goal after the operator read it and reject a new delegation and a saved replay against the stale revision. Reject completed, revoked or deleted goals and unregistered operators, including on retry. Verify existing work items and attribution remain readable.
- [ ] **Rollback and interruption.** Force a failure after the work-item insert but before all related writes finish. Reopen and verify no partial item, retry record or commit link, with earlier history intact. Separately commit delegation without finishing the call's reply; reopen, follow the original unfinished call to the saved item, and recover it through an authorized retry.
- [ ] **Concurrent retries and input boundary.** Exercise two identical calls competing for the same grant and retry key and verify one work item. Reuse existing work-item validation tests and add focused coverage for retry keys and the new workspace-input type, including rejection of relative source paths. Verify an absolute path and full SHA are recorded as requested input without repository access or authorization. Verify failed requests leave prior saved state intact.
- [ ] **Compatibility.** Reuse existing coverage for owner-created work items, exact skill bindings, attempt preparation, worker authority, artifacts and audit. Test first use and reopening with saved delegation data. Preserve existing HTTP, CLI and MCP contracts; MCP discovery and signed-in delegation acceptance belong to the future tool slice.

## Documentation and verification

- [ ] Update [terminology](../../TERMINOLOGY.md) for delegation grants, work-item attribution and replay. Update the [command catalog](../../CATALOG.md) and [README](../../README.md) where needed to explain the model capability and current transport boundary without advertising an unimplemented command or tool.
- [ ] Run `make check` and `make test` after implementation and record actual results. Report live checks separately as not required for this model-only slice; live operator behavior and transport contracts remain unchanged.
- [ ] After completing implementation and acceptance, create and run `docs/phase3/SLICE16_EVIDENCE.sh`. Run the focused acceptance tests and one readable delegate-and-reopen example through public Python operations against temporary SQLite, showing attribution and zero attempts. Reuse the tests for authority, replay, concurrency, rollback and interruption rather than implementing a second acceptance suite in the script. Capture actual output in `docs/phase3/SLICE16_EVIDENCE.md`, including check results and any remaining limitation.
