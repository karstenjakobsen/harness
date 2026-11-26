# Slice 10a — Close the worker isolation gap and add a fast file handoff

An owner can delegate a small task to one Nomad worker and retrieve the resulting file after the container exits. A developer can run this check independently with **one signed-in Codex session**. Slice 10a also closes the two findings from the Slice 10 review: worker access to management APIs and delegation replay after a goal edit.

## 1. Close the worker isolation gap

- [x] Verify the worker can use scoped Harness MCP while Nomad management and owner HTTP access are denied. Enforce Nomad management access at the cluster boundary, including both the task socket and the host gateway observed in Slice 10.
- [x] From a real worker allocation, verify that management reads are denied or unreachable with missing credentials, invalid credentials, and the worker’s own credential. Verify that owner HTTP denies the worker and permits an authenticated owner process to read the same resource. These controls prevent a stopped service from producing a false pass.
- [x] In the same setup, verify that the trusted launcher can still register and inspect the job, the original-allocation guard still works, and the worker can read its own brief and submit its result through MCP. Run this isolation test in `make test-nomad` without a model login.

## 2. Make an identical delegation replay survive a goal edit

- [x] In the public `delegate_work` operation, check the open call, exact active grant, and target. Then look up the retry key and compare the original inputs **before** requiring the goal revision to be current.
- [x] An identical authorized replay returns the original work item, attempt, and committing call. The replay gets its own audit entry. Changed inputs under the same key conflict. A new key targeting a stale revision also conflicts.
- [x] Add one offline regression: commit a delegation for revision 1, lose the reply, edit the goal to revision 2, then replay the original request. Assert one work item, one attempt, and the original commit reference. If that attempt was still pending, dispatch records the stale revision and makes zero Nomad registrations. Withdrawing the grant still denies replay.

## 3. Let a worker deliver one small text file

- [x] Add a bounded `text_file` result alongside the existing chess fixture. Pin the expected result type on the work item so the worker knows what to return and Harness knows what to validate.
- [x] Let the worker write the file in its private scratch directory. The submission tool accepts only its filename and reads the existing file before sending its exact UTF-8 content through worker MCP. Test a missing file and an exact UTF-8 round trip. Accept a plain filename and enforce a documented byte limit. Store the content with the observation, original goal revision, attempt, and submitting call.
- [x] Remove the assumption in the worker’s startup prompt that every assignment produces chess cases. The worker reads its brief and expected deliverable from MCP. Keep Danish city names and chess rules out of Harness business logic.
- [x] An identical submission retry returns the original observation. A conflicting submission leaves the first artifact intact. The owner can retrieve the filename and exact content through HTTP after the worker exits.

## 4. Default live test — `make test-live`

`make test-live` selects exactly one test, the Danish-city file handoff. It starts exactly one signed-in Codex session inside the worker and zero operator Codex sessions. Delegate this exact brief through the public model.

> Create a UTF-8 file named `cities.txt` containing København, Aarhus, Odense, Aalborg, and Esbjerg, one city per line, in any order. Submit the file as your deliverable.

| Step | Acceptance |
|---|---|
| **Arrange** | Create an isolated workspace, active goal, registered operator, and real work grant. Bind a recorded operator call to the grant and delegate the brief with result type `text_file`. |
| **Execute** | Launch one real Nomad allocation with the pinned worker image. Verify the session counts, an audited brief read, an artifact submission, and an observed exit code of `0`. |
| **Retrieve** | After exit, start a fresh owner process with only the goal ID. Follow HTTP activity to the work item, attempt, and observation. Retrieve `cities.txt` from Harness storage. |
| **Assert** | Decode the saved content as UTF-8. Require exactly five nonblank lines and the exact set of supplied names, in any order. Verify one attempt, one submitted observation attributed to the worker, and an `active` goal. A prose claim that the file was written cannot pass. |

Run this target when changing the worker image, launcher, MCP handoff, or artifact storage. Reuse a ready cluster and an already-built worker image when available. Record elapsed time for a **warm run** and report image build or cluster startup separately. The development target is a warm handoff within 30 seconds.

## 5. Extended live tests — opt-in

Preserve all existing signed-in scenarios under `make test-live-extended`, including chess delegation, fresh-session review, and review of an incorrect result. Run this target explicitly when changing operator planning, delegation, or evidence review. Verify that the default target collects only the city handoff and that the extended target collects the existing live cases and excludes the city handoff.

## Definition of done

Report `make check`, `make test`, `make test-nomad`, and `make test-live` separately. For the Slice 10a handoff, also run `make test-live-extended` once and report whether the existing chess contract passes with the revised worker prompt and result types. Capture both live selections, observed worker and operator session counts for the default test, worker image digest, warm duration, goal-to-artifact references, and isolation outcomes in `docs/SLICE10A_EVIDENCE.md`.
