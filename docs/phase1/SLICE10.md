Wokers should be oneshot - right ? Then operator can relaunch
Yes. One worker container runs one attempt, hands back its result, and exits. It can read skills, edit files, run tests, and make several MCP calls during that attempt. Then the operator reviews the evidence and decides whether to accept it, retry, change the brief, or ask you for input.

I’d give “relaunch” three precise meanings:

Situation	What Harness does
The launch response was lost	Look up the existing attempt by ID. Repeating the launch request must never start a second worker.
The operator wants another try with the same brief	Start a fresh container with a new attempt ID under the same work item. Keep the first attempt and its evidence.
The operator changes the brief	Create a new work item tied to the goal revision, so each result can be traced to the instructions its worker received.
This also fits your standing file-permission goal. The worker can build and test the permission-maintaining service, hand it over, and exit. The service can run in Nomad for months. The operator can inspect it later and launch a fresh worker if it needs a fix.

A worker exiting 0 tells Harness that the process succeeded. Goal completion remains the operator’s separate, audited decision.

How do we mount scratch pads for the workers ? Sometimes they need to produce a new file and sometimes build on an existing project. Do we give them git repo url and credentials to clone and submit a branch ? Do we mount s path from the VPs ?
I’d give every worker attempt its own writable workspace. For a new file, it starts empty. For an existing project, Harness prepares it from a specific Git commit. The worker image and entrypoint are identical in both cases.

Assignment	What the worker sees at startup	What survives after exit
“Write five Danish cities to cities.txt”	An empty workspace	The submitted file, linked to the attempt and goal revision
“Add castling to the Go chess game”	A writable checkout of the chess project at a recorded commit SHA	The proposed changes, their base SHA, and the worker’s test results
“Fix the failing test from the previous attempt”	A fresh workspace seeded with the previous attempt’s saved changes	A new result linked to the earlier attempt
Would I mount a VPS path? Yes, for the first Docker prototype. Have the launcher create a fresh directory for each attempt and bind-mount only that directory at /workspace, writable by the container’s non-root user. This also makes it easy to inspect a failed run during development. I’d keep your personal checkout separate so two workers can edit the same project independently. On Nomad, the same worker can use a directory under NOMAD_TASK_DIR, or NOMAD_ALLOC_DIR if a preparation task needs to share it. The worker just needs to know its working directory. 

Would I give the worker a repo URL and Git credentials? For this design, the Git credential belongs to the project connection. The operator selects the project and base revision. A trusted launcher fetches the source and gives the worker a clean checkout with no embedded credential. The worker can edit, run tests, inspect diffs, and commit locally. If the operator has a grant to publish, it can use the Git connector to push the saved changes to a review branch. Harness records the base SHA, resulting SHA, branch, and attempt. For GitHub, the connector can use a short-lived GitHub App token scoped to the repository and required permissions. 

For the next slice, I’d prove the workspace contract before building the Git connector. Run the same image twice with plain Docker. Give the first attempt an empty directory and the second a clean checkout from a local test repo. Have the second worker change a file and run the project’s test. Acceptance is that both deliverables remain recoverable after their scratch directories are removed, and the original checkout stays intact. That proves workers can both create something new and build on existing work before we add remote credentials or branch publishing.

So very short . What is our new slice 10 ? Create a docker worker that uses s known one shot codex image and can take attempt id to use against the mcp and deliver something in a mounted path ?
Slice 10 — Run one worker attempt in Docker. Start a pinned, existing Codex image with a thin entrypoint, harness-worker run --attempt-id ID. The worker authenticates to Harness MCP, fetches its brief and assigned skills, writes the deliverable to a per-attempt directory mounted at /workspace, reports its relative path through MCP, and exits. Harness links the saved artifact to the attempt before scratch cleanup.

Acceptance: Use the same image for two briefs. One writes cities.txt in an empty workspace. The other edits a file in a checkout pinned to a known commit. Both results are recoverable after cleanup, and the goal stays open for operator review. Nomad integration comes afterward.

i saved current latest cimmit in a branch . do we go back to 5f07a8de3ec233c05098023509f3ac1eac70e296? for this new slice 10 ?
Yes. 5f07a8d is the revised Slice 9 handoff. I’d start the new Slice 10 from 157346c. I checked the diff: it has identical code and adds only PLAYBOOK.md. The old Slice 10 proposal first appears in the next commit, bf3df2f.

git switch -c slice-10-docker-worker 157346c

That gives you the Slice 9 baseline for the Docker-first worker, preserves your saved prototype branch, and requires no reset or force-push of main.