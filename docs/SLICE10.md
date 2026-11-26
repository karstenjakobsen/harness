## Slice 10 — An operator delegates one goal-scoped task to a real worker

**Given a saved chess subgoal, the operator can choose skills, write a brief, and launch a Nomad worker. Later, a fresh operator session can start with only the goal ID, inspect what the worker received and returned, and decide whether the work satisfies the brief.**

I’d give the engineer five requirements.

| Requirement | What Slice 10 should deliver |
|---|---|
| **1. Reuse local skills** | Keep `skills/chess-rules/` and `skills/go-testing/` in the repo. Put the name, description, and instructions in each `SKILL.md`. Reuse the existing immutable snapshots and audited reads. The operator chooses which revisions to assign. The worker can read those revisions, and the audit distinguishes assignment from an actual read. |
| **2. Save one work item** | Under an owner grant for one goal, the operator calls `delegate_work` with the goal ID, expected revision, brief, selected skill revisions, and retry key. Harness saves the work item, its first execution attempt, and the committing MCP call together. The **work item** says what was requested. An **attempt** identifies one launch against that brief. |
| **3. Run one real worker** | Use one configured worker image pinned by digest and the Slice 9 execution backend. The worker authenticates from its original Nomad allocation. Through worker MCP it can read its brief and assigned skills and submit a bounded result. Harness derives attribution from the session. Withdrawing the owner’s delegation closes worker access, including for an already-open session. |
| **4. Keep retry decisions with the operator** | Repeating the same delegation after a lost reply

## Slice 10 — Delegate one goal revision to one Nomad worker

**An owner asks the operator to prepare test cases for a saved chess goal. The operator chooses the brief and skills, a worker returns its cases, and a fresh operator session can inspect the result and decide what it establishes.** That is the whole slice.

### What we build

| Step | Slice 10 contract |
| --- | --- |
| **1. Delegate work** | Under an owner grant for one goal, the operator can call `delegate_work` with the expected goal revision, a brief, selected skill revisions, and a retry key. Harness saves the work item, its first execution attempt, and the committing MCP call together. |
| **2. Launch one worker** | Harness starts the saved attempt through the Slice 9 execution backend using one configured worker image. A repeated delegation request returns the same work item and attempt. An uncertain launch stays visible as `unknown`. Only an explicit operator decision can create a fresh attempt against the same work item. |
| **3. Give the worker its inputs** | The authenticated worker can read its brief, the pinned goal definition, and its assigned skill revisions through MCP. Use the existing repo-local `skills/` directory with standard `SKILL.md` files. A single worker role is enough for this slice. |
| **4. Accept one result** | The worker submits a bounded JSON fixture containing the chess positions, candidate moves, expected outcomes, reasons, and whether the cases were executed. Harness checks the shape, derives the worker identity from the session, and saves the result against the assigned goal revision. An identical submission retry returns the original observation. |
| **5. Review from the goal** | Starting with only the goal ID, a fresh operator or the owner over HTTP can retrieve the brief, delegating call, worker attempt, allocation, assigned skills, actual skill reads, submitted cases, and exit status. The operator can explain what the evidence supports, ask for a correction, or leave the goal open. Completion uses the existing separately granted operation. |

### Boundaries to settle before coding

- **The operator owns judgment.** It chooses whether to delegate, what to ask, which skills to assign, and whether another attempt is worthwhile. Harness owns authorization, persistence, structural validation, and the audit recorded inside MCP.
- **The worker acts for one attempt.** Bind its session to the exact delegation, work item, and original Nomad allocation. A replacement allocation cannot inherit it. Withdrawing the delegation ends worker access, including for an already authenticated session. Regranting authority leaves that old session invalid.
- **A goal edit preserves the meaning of earlier work.** If the owner edits revision 1 while a worker is running, an otherwise authorized result can still be saved against revision 1. The reviewing operator can see both the original brief and the current definition.
- **Skills stay local and pinned.** Reuse the existing skill model and audited MCP reads. Snapshot the committed instructions so editing a skill tomorrow preserves what yesterday’s worker read. External downloaders, marketplaces, and plugin packaging can wait.

### Acceptance I’d give the engineer

1. **Real handoff.** In a temporary workspace, create a chess subgoal and grant delegation through the CLI. Ask the operator: *“Prepare two test cases showing when a pinned rook may move and when it may not.”* Give it no skill IDs or expected moves. Verify that the operator chose the skills, one real Nomad worker read the brief and assigned revisions, and the worker submitted the actual cases. The goal remains active.
2. **Fresh review.** End the original session. From the goal ID alone, have a new session recover the submitted cases and explain them. Check the same references over HTTP. If the worker prepared the fixture and exited `0` without running a move generator, the review should say exactly that.
3. **Judgment check.** In a separate controlled case, supply a schema-valid result that incorrectly says moving the pinned rook off the file is legal. Verify the reviewer can identify the error from the saved position and leave the goal open. The operator chooses whether to request a correction.
4. **Focused offline tests.** Cover duplicate delegation and submission, explicit retry, withdrawal after authentication, a replacement allocation, an unassigned skill, and a goal edit during execution. Confirm that audit history preserves the original committing calls and skill contents.

**I’d cut the profile catalog, registry reorganization, and workflow engine from the proposal.** The design decision worth proving now is that a worker can bring back evidence the operator can inspect, question, and act on.