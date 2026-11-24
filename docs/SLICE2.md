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