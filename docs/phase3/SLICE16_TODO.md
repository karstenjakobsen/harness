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

## Public contract and authority

- [ ] Add `WorkAPI.delegate_work(goal_id, expected_revision, brief, workspace_input, retry_key, *, call) -> WorkItem`. Use the existing public `CallReference` to identify a durably recorded operator call. Derive the operator and exact grant from its trusted run binding; accept no caller-selected operator or grant as delegation authority.
- [ ] Define and export the workspace-input type through `harness_api.__all__`. Represent either an empty workspace or a source repository with a full pinned commit SHA, preserving the existing work item's `source_path` and `base_sha` meanings. Validate and normalize the input without creating a checkout or scratch directory. Keep exact skill guidance compatible with existing work items; this operation takes the brief and workspace input specified in the design.
- [ ] Add the minimal owner model operations to grant and withdraw `delegate_work` for one goal and registered operator. Bind recorded runs to that exact grant through the public API. A grant for a parent does not implicitly cover its children, and a goal assignment, completion grant or definition grant does not authorize delegation.
- [ ] Recheck the call, run, exact grant, registered operator, workspace ownership, target goal and expected revision inside the write transaction, including on replay. Require an unfinished matching call in an unfinished run, with the correct tool, target and revision. Reject advisory runs, missing or mismatched calls, withdrawn grants, unregistered operators, inaccessible goals and stale revisions.
- [ ] Preserve the current work-item rule that the goal must be open (`draft`, `active` or `paused`). Withdrawing and regranting authority must leave the old run denied; unregistering an operator must invalidate its delegation authority without deleting earlier work or attribution.

[Work model](../../packages/harness_api/src/harness_api/models/work.py) ·
[Recorded runs and delegated-write patterns](../../packages/harness_api/src/harness_api/models/goals.py) ·
[Operator lifecycle](../../packages/harness_api/src/harness_api/models/accounts.py)

## Atomic persistence and replay

- [ ] Reuse the existing work-item validation and persistence within one model transaction. Keep the trusted-owner `create_work_item` operation working for its existing callers. Avoid composing independently committed public writes to implement delegation.
- [ ] Save the work item, its exact goal revision, operator, grant, retry record and committing-call relationship atomically. Store the immutable brief and normalized workspace input. A failed insert or audit-link write must leave none of those new records committed.
- [ ] Scope retry keys to the exact delegation grant and fingerprint all assignment inputs: goal ID, expected revision, brief and normalized workspace input. Validate nonempty keys. An identical authorized request returns the original ID; changed inputs with that key raise a conflict. A fresh key creates a new work item, including for a changed brief.
- [ ] Recheck authority and the current goal revision before returning a saved retry. After withdrawal, unregistration or revision change, replay must not recover authority or create another item. A new grant must not retrieve an old grant's retry record.
- [ ] Preserve the original committing call on replay. A retry uses a separate recorded call that identifies the work item it retrieved. Concurrent identical requests under the same grant and key must leave one work item and one original committing call.
- [ ] Extend the unversioned `schema.sql` directly with the necessary grant, run-binding, retry and call relationships and constraints. Initialize empty workspaces from it and reopen saved workspaces as they are. Use a fresh workspace after an incompatible change; add no migration framework.

[Schema](../../packages/harness_api/src/harness_api/schema.sql) ·
[Existing work-model tests](../../packages/harness_api/tests/test_work.py)

## Inspectable attribution

- [ ] Expose the delegation grant and original committing-call reference through public model reads of the work item. Preserve unknown or absent delegation attribution for work items created through the existing owner operation.
- [ ] Extend the recorded-call model to recognize `delegate_work` and distinguish committed from retrieved work-item references. Starting with the work item, follow its goal revision, operator, exact grant, run and call; starting with the run, identify the same work item. A commit remains inspectable when reply recording never finishes.
- [ ] Keep already persisted denied or failed call attempts visible without a committed work-item reference. Preserve existing goal revisions, observations, decisions and call history after denial or rollback. Record IDs, timing and outcomes using the existing activity conventions; avoid adding raw prompts, briefs, responses or secrets to call history.
- [ ] Update affected shared types, exports, activity serialization and existing callers together. If existing HTTP or CLI history responses gain fields, update their schemas and focused contract tests to preserve the same meanings. Add no delegation transport or tool discovery in this slice.

[Activity model](../../packages/harness_api/src/harness_api/models/activity.py) ·
[Public exports](../../packages/harness_api/src/harness_api/__init__.py)

## Acceptance through the public Python API

Use isolated temporary workspaces, real SQLite transactions and small fixtures.
Create users, operators, goals, grants, runs and call attempts through public
model operations. Use a narrow failure injection only where needed to prove
rollback; tests should assert saved results and history.

- [ ] **Delegate and reopen.** Delegate once under a valid goal-scoped grant. Reopen the workspace and verify the exact brief, workspace input, goal revision, operator, grant and committing call. Cover empty input and a pinned source input. Verify zero attempts and no goal or parent change.
- [ ] **Replay and conflict.** Replay through a new call with the same key and inputs, including after reopening and after a lost reply. Assert one ID and preserved original attribution, with a retrieval reference on the retry. Change the brief, workspace input or revision under the same key and verify rejection without another item. Use a fresh key to save a revised brief as a separate item.
- [ ] **Authority boundary.** Cover another goal, another owner's goal or operator, an assignment without a grant, an advisory run, an unrelated action grant, and missing or mismatched call context. Withdraw a grant after run start, deny both a new request and replay, regrant the action, and verify the old run remains denied. Verify a fresh run bound to the replacement grant can delegate within its scope.
- [ ] **Revision and lifecycle.** Revise the goal after the operator read it and reject a new delegation and a saved replay against the stale revision. Reject completed, revoked or deleted goals and unregistered operators, including on retry. Verify existing work items and attribution remain readable.
- [ ] **Rollback and interruption.** Force a failure after the work-item insert but before all related writes finish. Reopen and verify no partial item, retry record or commit link, with earlier history intact. Separately commit delegation without finishing the call's reply; reopen, follow the original unfinished call to the saved item, and recover it through an authorized retry.
- [ ] **Concurrent retries and validation.** Exercise two identical calls competing for the same grant and retry key and verify one work item. Cover invalid IDs, empty briefs and keys, malformed workspace inputs, and missing or invalid pinned SHAs. Verify failed requests leave prior saved state intact.
- [ ] **Compatibility.** Retain coverage for owner-created work items, exact skill bindings, attempt preparation, worker authority, artifacts and audit. Test first use and reopening with saved delegation data. Update focused activity adapter tests only where their existing response contracts change; MCP discovery and signed-in delegation acceptance belong to the future tool slice.

## Documentation and verification

- [ ] Update [terminology](../../TERMINOLOGY.md) for delegation grants, work-item attribution and replay. Update the [command catalog](../../CATALOG.md) and [README](../../README.md) where needed to explain the model capability and current transport boundary without advertising an unimplemented command or tool.
- [ ] Run `make check` and `make test` after implementation and record actual results. Report live checks separately: the model-only slice requires no AI session; if implementation changes live operator behavior, also run the applicable signed-in `make test-live` and identify any blocker.
- [ ] After completing implementation and acceptance, create and run `docs/phase3/SLICE16_EVIDENCE.sh`. Use public Python operations and temporary SQLite to demonstrate successful delegation, reopened attribution, replay/conflict, authority denial, stale-revision rejection and zero attempts. Capture actual output in `docs/phase3/SLICE16_EVIDENCE.md`, including check results and any remaining limitation.
