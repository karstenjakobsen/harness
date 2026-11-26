Slice 9 — Let an operator hand one piece of work to a worker and inspect what comes back.

Slice 8 gave the operator a way to save a plan. I’d make Slice 9 prove the first handoff end to end: the operator chooses work for a saved subgoal, a worker reads the brief and relevant skills through MCP, and the operator can inspect the result in a fresh session.
The smallest useful example
Take the chess subgoal “Generate legal moves and enforce king safety.” The operator gives a worker a narrower task:
Produce two Go test cases from the same chess position. One move should expose the king and one should keep it safe. Explain the expected result for each.

The worker can return a table-driven test fixture. That is useful work even before there is a chess engine to run it against. The operator can inspect the fixture and tell the owner exactly where things stand: “We have the test cases. We still need the move generator to pass them.”
What I’d give the engineer
Step	Slice 9 contract
Delegate work	With an owner grant scoped to the named goal, the operator creates a work item through audited MCP. It records the goal ID and revision, the worker’s brief, and the exact skill revisions the operator selected. The operator chooses the scope of the task.
Pick it up	Start one local worker session bound to that work item. Through MCP, it can read the brief, the pinned goal definition, and the assigned skill revisions. Reuse list_skills and read_skill. Record which skills were assigned and which the worker actually read.
Return a result	The worker submits a result against the work item through MCP. For this slice, a small text or code result is enough. Harness derives the worker’s identity from the session and records the result as evidence tied to the original goal revision. An identical retry returns the original submission.
Review it	A fresh operator session can follow the goal to the work item, worker run, and result. The owner can follow the same references over HTTP. Returning work leaves the goal open for the operator’s judgment under the existing completion grant.


I’d reserve work item for the worker’s brief. Assignment already means a registered operator’s responsibility for a goal. A goal defines the desired outcome. A work item describes one contribution toward it. That distinction matters as soon as two workers contribute to the same goal or the first attempt needs fixing.

Acceptance: Run the chess handoff in a fresh workspace with one real local worker session. Verify that the returned fixture identifies both moves and their expected outcomes. Then start a fresh operator session with only the goal ID and ask, “What did the worker deliver, and what still needs to be verified?” Check the answer against the saved result and confirm the goal is still open. Offline, also prove that publishing a newer skill revision leaves the worker’s assigned version readable and that a worker bound to a different work item cannot submit against this one.

I’d stop at one local worker and one durable result. That gives the later Nomad slice a concrete job: launch a worker using the same work-item contract. The operator already owns the decisions about what work to request and whether the result warrants another attempt.














here i think wee need to talk achitecture. i would like the worker to be inside a container thats runs in nomad. later i could use kubernetes or docker socket directly. How do we do this ?












Worked for 21s




I’d change Slice 9 so the first real worker runs inside a container scheduled by Nomad. Build one worker image and one Nomad adapter. Keep the boundary small enough that a later Docker or Kubernetes adapter can launch the same image and the worker can use the same Harness tools.
What belongs where
Component	Responsibility
Operator	Decides what work to request, which goal revision it serves, which skills to provide, and whether another attempt is worthwhile.
Harness API	Saves the work item and each worker run. Owns authorization, pinned skill revisions, evidence, and audit history.
Execution adapter	Starts, inspects, and stops one worker run. The Nomad implementation translates those operations into a job and records its allocation IDs.
Worker container	Connects to Harness over MCP, reads its brief and assigned skills, performs the work, submits its result, and exits.


The important modeling choice is goal revision → work item → worker run. A work item says “Produce Go test cases for king safety.” A worker run is one attempt to deliver them. If the first container fails and the operator tries again, both runs belong to the same work item. Nomad job and allocation IDs belong on the run. That gives the web UI a direct path from a goal to what happened on the cluster.
How one run works
1. The operator requests the work. Under a goal-scoped grant, it calls an audited MCP tool such as start_work with the goal revision, brief, pinned skill revisions, and a retry key. One call is enough for the first slice. Harness saves the work item and allocates a run ID before contacting Nomad.
2. The adapter launches the worker. It submits a Nomad batch job with one task, a configured worker image pinned by digest, and a job ID derived from the Harness run ID. If submission times out, the adapter can look up that same job before submitting again. A repeated tool call with the same key resolves to the same run. An operator decision to try the work again creates a new run. HashiCorp Developer
3. The worker calls back to Harness. I’d use a worker-facing MCP endpoint over HTTP. The container receives its endpoint and a short-lived credential bound to that run. Harness derives the work item from the credential. The worker can read its brief, use list_skills and read_skill for its assigned revisions, and submit a result. SQLite and the Nomad credentials stay on the Harness side. The MCP server records the calls.
4. The operator reviews the outcome. Harness exposes the scheduler outcome and the submitted result separately. A container can exit successfully without submitting anything. It can also submit useful evidence and then crash. The operator needs both facts to decide whether to accept the work, retry, change the brief, or tell the owner what blocked progress.
For the first batch worker, I’d explicitly disable Nomad’s automatic task restarts and failed-allocation rescheduling. Nomad configures these separately, and batch jobs have a default reschedule attempt. This keeps a deliberate retry visible as an operator decision. HashiCorp Developer
Where the standing file-permission goal fits
There are two lifetimes in your 0600 example. The worker might run for five minutes to build and test the file-permission service. The service it hands over might run for six months. I’d give that service its own workload identity when we reach that slice. Then the operator can stop or inspect the service long after the worker has exited, and the owner can still trace which worker produced it.

My Slice 9 acceptance test: Start with the saved chess subgoal. Have the operator launch one real Nomad worker, let it read a pinned skill through MCP and return two Go test cases, then let the container exit. From a fresh operator session, start with only the goal ID and recover the brief, skill revision actually read, Nomad allocation, exit outcome, and submitted cases. The goal stays open for review. That proves the execution boundary before we add a second backend or a long-lived workload.


"is slice 9 to setup nomad (in docker) nomad agent outside of docker, create abstratction layers and test that we can create workloads ?"

Yes. **Slice 9 should prove that Harness can launch, inspect, and stop a real container through Nomad.** Slice 10 can then put an AI worker inside that container and give it scoped MCP access to its brief, skills, and result submission.

### Development topology

If you mean **Nomad server in Docker, Nomad client agent on the host, and workers in Docker**, that’s a reasonable split. For one dev machine, I’d start simpler: run **one Nomad dev agent on the host**. It serves as both server and client. Harness talks to the Nomad API, and Nomad’s Docker driver uses the host Docker daemon to run the workload. You can separate the server later without changing Harness. [HashiCorp Developer](https://developer.hashicorp.com/nomad/tutorials/get-started/gs-start-a-cluster?utm_source=chatgpt.com)

### One execution boundary

I’d introduce **one small Python interface** with a single implementation, `NomadBackend`:

| Operation | Contract |
|---|---|
| `start(run_id, spec)` | Launch the configured container for this Harness run. Repeating the same request returns the same workload handle. |
| `inspect(handle)` | Return execution state, exit code when available, and backend references. For Nomad, include the job and allocation IDs. |
| `stop(handle)` | Stop that run’s workload. Repeating the request is safe. |

Keep the initial `spec` to the image and arguments the test actually needs. The Nomad adapter builds the job specification. A future `DockerBackend` can use the Docker socket and a `KubernetesBackend` can create a Job behind the same interface. **Goals and grants should have no dependency on any of the three.**

### What proves 9 is done

Give the engineer one separately invocable `make test-nomad` that runs against real Nomad:

1. **Successful run.** Launch a small pinned image that prints a unique marker and exits `0`. Verify the marker, exit code, job ID, and allocation ID. This proves the container executed.
2. **Failed run.** Launch a command that exits `7`. Verify that `inspect` reports the failure and exact exit code. Harness records the outcome and leaves the retry decision to its caller.
3. **Stop and retry.** Launch a long-running test container. Repeat `start` with the same run ID and spec, verify there is one workload, then call `stop` twice and verify it stopped. Clean up only the jobs created by the test.

I’d keep 9 deliberately that small. **Its deliverable is a working execution backend and a reproducible dev setup.** In 10, replace the test command with the worker entry point and prove the handoff from goal → work item → container run → evidence.
