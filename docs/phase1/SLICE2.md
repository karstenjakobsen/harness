## Next slice — Define and manage evolving goals through the CLI

An owner can define a goal, break it into subgoals, revise one as the plan changes, and ask the operator what is complete and why. This slice ends at goal management. “Build a personal tracker” creates a goal record. Building the tracker, deploying an app, and connecting a data source are future work.

### Functional requirements

- **Create and inspect a goal tree.** Extend the existing goal model with an optional parent goal ID. Each goal has its own outcome, success criteria, timing, and verification method. A subgoal can have children of its own. Existing goals remain valid root goals.
- **Revise one goal independently.** The CLI can change a goal’s requirements or duration while preserving its ID and revision history. Revising “track food for seven days” to fourteen days leaves its parent and siblings unchanged.
- **Record the basis for completion.** The owner can use the CLI to record a user confirmation or a reference to external evidence against a specific revision. Keep the evidence source and who recorded it. A manually supplied app reference should appear as owner-supplied evidence. A decision on an earlier revision stays in history and does not automatically complete a revised goal.
- **Let the operator explain the plan.** Extend the read-only MCP interface so `operator ask` can retrieve the goal tree, current requirements, status, and supporting evidence. Completing a child leaves the parent’s status unchanged. The operator can suggest revisions, and the owner applies them through the CLI.

### CLI integration test

Build **one end-to-end test** around the existing `operator ask` entry point. The command names for new goal operations are an implementation choice. The behavior below is the acceptance contract.

| Step | Action | What the test proves |
|---|---|---|
| 1 | Start in an empty temporary directory. Run the CLI to create “Lose 20 lb.” | The normal CLI startup creates and migrates a fresh SQLite database. Capture the returned goal ID. |
| 2 | Using only CLI commands, add “Build a personal tracker,” “Get a gym membership,” and “Track food for seven days” under that ID. Give each its own success criteria and verification method. | Separate CLI invocations persist three distinct children under the same parent. |
| 3 | Record the owner’s confirmation that the gym membership is active and mark that goal complete. Revise food tracking from seven to fourteen days. | The gym goal is complete by user confirmation. Food tracking is still open, with seven days retained in its revision history. |
| 4 | From the same directory, run `operator ask "For my Lose 20 lb goal, list each subgoal, tell me which is complete and how we know, give the current food-tracking duration, and tell me whether the parent goal is complete."` | The operator retrieves the saved goal data through MCP and answers from the database created by the CLI. |

**Pass criteria:** The answer identifies all three children, attributes gym completion to the owner’s confirmation, reports **14 days** as the current tracking requirement, and says the parent is **still open**. Assert those facts independently so wording and order can vary. Keep fixture creation entirely in the CLI and provide the operator only the question. This makes the test catch the important failure mode where the CLI writes one database and the operator reads another.

### Engineer follow-up — align the goal API contracts

At commit `21cd4f8`, `GoalAPI` owns persistence, revisions, completion evidence, retries, and status transitions. Keep those rules there and keep MCP read-only.

1. **Expose creation intent.** Reuse the model’s existing `status` argument. Let `POST /goals` accept `"draft"` or `"active"` at creation, with `"draft"` as the default. The message-based CLI should explicitly request a draft, and explicit CLI creation should request an active goal. Test the same title and definition with omitted status, explicit draft, and explicit active. All three should return HTTP 201 and revision 1 with the requested status. A request to create a completed goal should return 422 and write nothing. [Goal model](../../packages/harness_api/src/harness_api/models/goals.py) · [HTTP views](../../packages/harness_api/src/harness_api/views/goals.py)

2. **Persist structured timing from a draft.** Use the same definition fields in the draft schema and save path. `duration` describes whether the outcome is verified once (`one_time`) or maintained (`standing`). `duration_days` is an optional positive integer time window. For “Track food for seven days,” check that the generated schema asks for `duration_days`, return `7` from the stubbed Codex process, and read back `7` from the saved draft’s first revision. Cover an unspecified window with `null`. [Draft flow](../../packages/harness_operator/src/harness_operator/__init__.py) · [Draft contract test](../../packages/harness_operator/tests/test_create_goal.py)

3. **Reject deletion of a parent with visible children.** Check for an owned, undeleted direct child inside the same write transaction that soft-deletes the goal and closes its assignment. Return a domain conflict that HTTP maps to 409. Test that a rejected deletion preserves the assignment and the tree seen by list, get, and MCP. After deleting the last visible child, deleting the parent should succeed with 204. Replace the existing MCP test expectation that deleting an intermediate goal hides its grandchild. The guard prevents new orphan links. Any repair of links created before this change needs a separate data decision. [Deletion logic](../../packages/harness_api/src/harness_api/models/goals.py) · [MCP tree tests](../../packages/harness_mcp/tests/test_list_goals.py)

4. **Keep goal commands in the workspace.** Use `operator goal` for local list, explicit create, show, revise, complete, and Codex-assisted draft creation. HTTP clients can use the FastAPI endpoints directly. [Workspace commands](../../packages/harness_operator/src/harness_operator/commands/goal.py) · [CLI tests](../../packages/harness_operator/tests/test_goal_cli.py)

Run `make check`, `make test`, and the signed-in `make test-live`. Switch live fixture creation to the workspace commands. Keep the checks that the MCP result matches the CLI tree, the reply explains each goal correctly, and teardown removes the temporary database.
