**Slice 8 — Let a delegated operator save subgoals under one parent goal.**

Slice 7 lets the operator read skills and propose a plan. Slice 8 lets the owner say, *“Break ‘Build a chess game in Go’ into subgoals and save them so I can review them.”* The operator chooses the number of children, their scope, their success criteria, and which skills to consult.

**What I’d hand to the engineer**

- **One parent-scoped grant.** The owner grants a registered operator permission to create direct children of one named goal. One grant covers repeated creates. A child can later receive its own grant for further decomposition.
- **One audited MCP tool.** `create_subgoal(parent_goal_id, expected_parent_revision, definition, retry_key)` saves one child as a `draft` and returns its ID and revision. `GoalAPI` rechecks the exact grant, parent, and revision in the write transaction. An identical authorized retry returns the original child. If the parent definition changed before a new create, the operator gets a conflict and can reread the goal.
- **A plan the owner can inspect.** The existing goal tree shows the saved children. From the parent’s activity, the owner can find the planning run, see which skill revisions it read, and follow each creation call to the child revision it committed. Each child is saved independently, so an interrupted run leaves a visible partial plan the next operator can inspect before continuing.

**Acceptance:** Create the Go chess goal through the CLI. Ask the same planning question first in an advisory session, then in a session with the parent grant. The first produces a proposal and leaves zero children. The second saves draft children with concrete criteria. Let the operator choose their titles and count. Verify through HTTP that every saved child belongs to the intended parent and has a committing call, and that the parent keeps its original revision and status. Cover a wrong parent, withdrawn grant, stale revision, and identical retry offline.

I’d end Slice 8 when the owner can **open the saved plan and trace how it was created**. That gives the first worker-assignment slice a concrete input: a child goal with a stable ID, a revision, and success criteria.