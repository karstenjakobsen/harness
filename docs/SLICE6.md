## Slice 6 — Let an operator learn from earlier runs

**An owner can ask, “Who changed this goal, what changed, and how do we know?” A fresh operator session can answer through audited MCP reads, even when another operator made the change.** This gives the operator the history it will later need to decide whether to retry work, ask a worker to fix something, or explain a blocker.

### Read scope

For the current single-owner workspace, I’d use **the same visibility as the existing goal reads**. A session that can read the owner’s workspace goals can inspect that workspace’s run history across operators. The owner boundary is enforced in the public model queries. Each session’s write authority continues to come from its own active grant.

This keeps Slice 6 small. We already let an advisory session read workspace goals. A completion grant narrows what that session may *change*. Introducing per-goal read grants just for history would give these two reads different visibility rules. If Harness later supports operators with restricted visibility, apply that policy consistently to goals, evidence, and run details.

### Implementation

- **Expose two read-only MCP tools for sessions with a recorded run.** `get_goal_activity(goal_id)` returns the existing goal timeline across operators. `get_run(run_id)` returns the existing structured run record with actor, grant, ordered calls, outcomes, returned references, and committed changes. Both advisory and delegated `operator ask` sessions qualify. A standalone server launched without a run ID omits both tools from discovery and rejects direct calls. CLI, HTTP, and MCP share the same public model queries.
- **Make history reads auditable themselves.** Record which goal or run was requested, the outcome, and references to the records exposed. For a run read, save the run outcome and each returned call's `(run_id, sequence)`, outcome, and commit or retrieval references as they appeared in the response. Later changes to the inspected run or call leave that record of the read intact. Reading an earlier audit read returns its saved references one level deep. Each history response excludes the currently executing call.
- **Preserve what each fact proves.** A committed revision identifies the call that saved it, even if that call’s reply was interrupted. A returned observation identifies evidence the tool exposed. A citation identifies evidence used in a decision. When the history contains no recorded rationale, the operator should say that the reason wasn’t recorded.
- **Keep judgment with the operator.** It can choose whether history is relevant, which runs to inspect, and what conclusion to draw. This slice adds the facts it can consult. Subgoal creation, worker execution, automated retries, and a separate learning store stay outside the slice.

### Acceptance

**Offline:** Use a temporary SQLite workspace and the real MCP adapter. Verify that the two tools return the same historical facts as HTTP for a completed run. Check discovery and direct invocation on a standalone server without a run ID. Exercise a denied write, a read of the current run, and a read of a run that previously inspected history. Have B inspect A's run after A's revision commits and before the reply is recorded. Finish A's call and run, then verify that B's saved read still reports the earlier run and call outcomes and the committed revision. Check owner isolation, finite responses, and an audit record for each history read.

**Signed in:** Register operators A and B. Have A use its revision grant to change a library goal from “active membership” to “active membership and a successful first checkout.” Start B in a fresh session with a completion grant for a **different** subgoal. This gives B a distinct, trusted identity while proving that read visibility and write scope remain independent. Give B only the library goal ID and ask:

> Who changed the success criteria for this goal, what changed, and which run and call saved it?

B should discover A’s committing call through `get_goal_activity`, inspect it through `get_run`, and attribute the change to A. Verify the answer against structured records, allow variation in wording and tool order, and confirm B made no goal change. Separately, test direct invocation of `revise_goal` under B’s grant and verify the denial.

**Done when** operator B can reconstruct operator A’s change from the goal ID alone. From that ID over HTTP, the owner can follow revision 2 to A’s committing call and follow B’s later activity read to the audit of the records B inspected. Report `make check`, `make test`, and signed-in `make test-live` separately.
