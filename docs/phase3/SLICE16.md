I’d choose packages/harness_api and make Slice 16 “Delegate a work item against a specific goal revision.” Implement the first of the two proposed operations, WorkAPI.delegate_work(...). That gives the future operator MCP tool a tested function to call.

The package already supports creating work items. The new behavior is delegation under an operator’s authority. In one transaction, check the recorded operator call, its active grant, the target goal and expected revision. Save the brief and workspace input, and link the work item to the call that created it. An authorized replay with the same key and inputs returns the original work item.

Acceptance can run entirely in Python against temporary SQLite:

* Delegate once, reopen the workspace, and follow the work item back to its goal revision, operator, grant, and committing call.
* Replay the request and recover the same ID. Reusing the key with a changed brief produces a conflict.
* Verify that a withdrawn grant or a new request against a stale revision creates no work item. The successful delegation itself creates zero attempts.

I’d stop there. Model, effort, worker engine, and provider credential belong to launch_attempt. Slice 14 gave you the reason: Codex and Kiro can execute the same assignment. Keeping Slice 16 focused on the assignment preserves that choice for each attempt and requires no MCP server, Nomad cluster, or AI session to test.