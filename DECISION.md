1. **The operator owns the outcome.** The owner talks to the operator through the UI and sets its mission, tasks, and standing goals. The operator decides what work to delegate, submits it to the harness, and uses the returned evidence to explain what happened. Only the owner and their authorized standing goals can direct work. Content from files, logs, and tool responses carries no authority to start work or expand its scope.

2. **The harness owns the run.** It creates the run ID, resolves the approved catalog revision, workspace, volumes, and connectors, and submits a job from a template it controls. It also owns standing-goal schedules and worker access for each run. The operator can request capabilities through the API. Arbitrary Nomad job specs, host paths, and privilege settings are prohibited inputs.

3. **Nomad owns execution.** Nomad places and supervises the job, and Docker runs the worker container. Each execution gets a fresh worker. A standing goal lives in the harness and can produce many runs. If an interrupted run may have changed external state, the harness checks what happened before it authorizes another attempt.

4. **The worker owns how it does the work.** Codex can use a shell, create files, and author and test skills in its writable workspace. It starts with a pinned, read-only catalog snapshot and gets only the connectors and project volumes assigned to that run. Workers must never receive the Docker socket, Nomad credentials, host administration access, or write access to harness state. Connector credentials stay with the harness, and the worker’s access ends with the run.

5. **The harness owns evidence and verification.** It saves launch details, observed tool calls, worker output, and independent checks under the run ID, outside the worker. A successful exit or a worker’s claim of success must never be enough to mark an outcome verified. The operator can turn the trace into a readable memory entry and link back to it. The trace remains available after the worker is removed and covers the actions the harness actually observed.

## First end-to-end flow

**The owner asks for an outcome. The operator delegates it, the harness controls the run, Nomad launches the worker, and the worker chooses how to complete the task with the tools it receives.**

1. **The owner gives the operator a task.** “Create `ALICE.md` in my workspace with 100 distinct animal names starting with A.” The operator searches the catalog for relevant skills and connectors. For this task, it finds a web research connector and uses the built-in workspace write tool.

2. **The operator requests a run.** It calls `start_run` with the desired outcome, the destination workspace, the requested tools, and the success criteria. The harness checks the request against the owner’s policy, creates a run ID, and submits a Nomad batch job from its own template. The worker gets read-only web search and fetch, plus `write_file` scoped to `ALICE.md`. The harness enforces those grants for that run.

3. **The worker does the work.** Nomad launches a fresh Codex container. Codex gets the goal and chooses how to research and compile the list. It writes the result through `write_file`, which saves the file to the persistent workspace outside the container. The harness records the research calls and file write under the run ID. If the worker needs another capability, it reports what’s missing so the operator can request it.

4. **The harness verifies the result.** After the worker exits, the harness opens `ALICE.md` itself and checks that it has exactly 100 distinct entries and that each starts with A. If the run also needs to verify that every entry is a real animal name, the harness checks against an agreed reference. It records the worker’s exit status and the verification result separately, then closes the worker’s access.

5. **The operator reports back.** It calls `get_run`, updates the task from the harness’s verdict, and writes a short memory entry linked to the evidence. The owner gets the file location, what was verified, and anything still unresolved. The evidence remains available after the worker is removed.

**What this should prove:** Codex gets the outcome and the tools, with the sequence of calls left up to it. The harness can then show what the worker was allowed to use, what it actually called, and what the harness independently verified.