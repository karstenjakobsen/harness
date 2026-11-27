# Slice 11 — Run a workload ourselves from a cold workspace

We want to change a brief, command or mount and try it on the local Slice 9 cluster in minutes. The first experiment writes a file. The deliverable is a repeatable experiment and a short record of what the workload actually required. Phase 3 can use that record to design the eventual integration.

## The smallest test kit

- [ ] Put one Python experiment script, one Jinja job template and one city fixture under `dev/phase2/`. Give the script three independently invocable steps: `seed`, `render` and `run`. A Make target can compose them. Keep this directory outside the installable Harness packages. Use the installed owner CLI as subprocesses, Jinja with strict undefined variables, and a small HTTP client for Nomad. Cluster setup stays in the existing `make nomad-up` and `make nomad-down` targets.
- [ ] **Seed from cold.** Resolve the CLI executable first. Run every command with the same new, empty workspace as its working directory. Use the sequence below and parse the returned JSON IDs and revision. Write a small local receipt so render/run can be invoked in a later process. This step runs with Nomad down and requires zero model sessions. Fail clearly if the supplied workspace already contains a database.
- [ ] **Render offline.** Render a single batch job as JSON from the fixture, pinned image, attempt ID and per-run scratch location. JSON-encode substituted values and parse the rendered document before submission. Give the job a unique ID and label it with the attempt ID. The template defines one task and disables restarts and rescheduling for this experiment. Keep the brief, expected filename and city list in fixture data. Rendering alone has no side effects on the cluster.
- [ ] **Run explicitly.** From the test script submit the rendered job directly to the configured Nomad HTTP API, poll its allocation to a bounded deadline and capture task outcome and logs. All scheduler requests originate here. Use the local single-client setup and a dedicated attempt directory mounted at `/workspace`. Copy the result to the evidence directory before cleanup. Clean up only the job and scratch owned by this run, including on failure. If submission times out, inspect the same job ID before reporting an unknown outcome.
- [ ] **Make the boundary visible.** Record goal ID/revision, work item and attempt ID from the CLI alongside job ID, allocation ID, image digest, exit code and file digest from the experiment. Keep observed scheduler facts in the experiment receipt. Preparing an attempt or discovering a file does not imply the worker submitted an artifact through MCP.

## Proposed seed sequence

| CLI operation | Value consumed by the next step |
| --- | --- |
| `operator register phase2-fixture` | Registered operator ID required by the work model |
| `operator goal create --title "Deliver a city list"` | Parent goal ID |
| `operator goal create --parent PARENT_ID --title "Write cities.txt"` | Child goal ID and current revision |
| `operator work create --goal-id CHILD_ID --revision REV --operator-id OP_ID --brief BRIEF` | Immutable work item ID |
| `operator work prepare WORK_ID --attempt-id ATTEMPT_ID` | Prepared attempt, with no recorded launch |

Use the explicit title form of goal creation. Named registration creates a workspace record. Neither operation starts an AI operator. The final command is introduced in the [decoupling TODO](PHASE2_DECOUPLING_TODO.md).

## Acceptance

- [ ] **Default, fast.** Use a deterministic container command to write the five supplied names, one per line: København, Aarhus, Odense, Aalborg and Esbjerg. Run seed and render without a cluster, then run the rendered job against a real local Nomad client. Require one allocation, exit 0, and exact five-line contents recoverable after scratch cleanup. Read the goal back through the CLI and verify its original revision and active status. Repeat from a second empty workspace. Report warm workload time separately from cluster startup. No Codex login is required for this path.
- [ ] **Failure.** With the same script and template, change the fixture command to exit 7. Verify the actual exit code, missing deliverable and bounded cleanup. The prepared attempt alone and a failed allocation must both remain distinguishable from successful delivery.
- [ ] **Optional worker MCP experiment.** When testing brief delivery, run the generic worker image with `harness-worker run --attempt-id ID` through this same direct submission path. Start worker MCP against the seeded workspace and bind its credential and scratch to that attempt. Pass only the worker credential and the model access it needs. Check its audited brief read and, if it submits a file, retrieve that file by goal ID after cleanup. Report this signed-in result separately. The deterministic case proves the scheduler and file path only.
- [ ] Add `make test-phase2` for the fast real-Nomad experiment. Document its three individual steps, prerequisites and a sample receipt in the README. Record actual outputs in `docs/phase2/SLICE11_EVIDENCE.md` via `docs/phase2/SLICE11_EVIDENCE.sh`. Capture which inputs, mounts, permissions, outputs and observations the next workload needs to vary. Use those findings to choose the second experiment, such as a standing file-mode workload.
