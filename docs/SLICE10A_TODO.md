# Slice 10a — Close the worker isolation gap and deliver one text file

An owner can recover a worker’s file from goal activity after the allocation exits. The delivery check uses one signed-in Codex session, in the worker. [Slice 10a design](SLICE10a.md) · [Slice 10 review findings](SLICE10_TODO.md#post-implementation-review)

## Isolate the worker on real Nomad

- [x] Verify the worker can use scoped Harness MCP while Nomad management and owner HTTP access are denied. Enforce Nomad management access at the cluster boundary across both the task socket and the host gateway. Keep launcher credentials outside the worker. [Cluster configuration](../dev/nomad)
- [x] In `make test-nomad`, exercise both management routes from a real worker allocation. On each route, verify a management read is denied or unreachable for all three cases — missing credentials, invalid credentials and the worker’s own credential. Verify an owner process can read the running owner HTTP API and the worker is denied access to the same goal.
- [x] In the same setup, verify the trusted launcher can register and inspect the job, the original-allocation guard rejects a second placement, and the worker can read its own brief and submit a result through MCP. Run these checks in `make test-nomad` without a model login.

## Recover a delegation after a lost reply and a goal edit

- [x] First add a failing offline regression. Commit a revision 1 delegation, leave the attempt pending, discard the reply, revise the goal to revision 2 and replay the original request in a new recorded call. Assert one work item, one attempt, the original committing run and call, and a distinct audit entry for the replay. [Work model tests](../packages/harness_api/tests/test_work.py)
- [x] In the `WorkAPI.delegate_work` transaction, verify the open call, exact active grant and target. Look up the grant-scoped retry key and compare the original inputs before checking the current goal revision. An identical request retrieves the original result. Changed inputs under that key and a new key for a stale revision each conflict. [WorkAPI](../packages/harness_api/src/harness_api/models/work.py)
- [x] Dispatch the still-pending attempt after the edit. Assert history records the stale revision and the launcher makes zero Nomad registrations. Withdraw the grant and verify the original replay is denied, including after a replacement grant is issued.

## Deliver a bounded UTF-8 file

- [x] Pin the expected result type on the work item at delegation, include it in retry comparisons and expose it through `get_work_brief`. Support `text_file` alongside the chess fixture. Preserve the existing fixture contract for callers that omit the type and for chess history reads.
- [x] Give the worker writable private scratch space. Update its startup instructions to read the brief and expected deliverable through MCP. For a file assignment, write the file there, then pass only its filename to `submit_work_result`. The worker-side tool must read the existing file. Cover a missing file and an exact UTF-8 round trip. Keep city names in the smoke scenario and chess rules in the assigned guidance. [Worker entry point](../dev/worker/harness-worker) · [Worker MCP](../packages/harness_mcp/src/harness_mcp/worker.py)
- [x] Validate the pinned type in the model, require a plain filename and document the content limit in UTF-8 bytes. Test a path with directory components, a mismatched type, and multibyte content at and just over the limit. Invalid submissions leave the attempt’s evidence intact.
- [x] Atomically save the filename and exact content with the observation, original goal revision, authenticated attempt and allocation, requesting operator and committing worker call. An identical submission returns the original observation. A changed filename or content conflicts and preserves the first file. Verify the owner HTTP activity read returns the saved filename and content after reopening the workspace.

## Default live test — `make test-live`

> Create a UTF-8 file named `cities.txt` containing København, Aarhus, Odense, Aalborg, and Esbjerg, one city per line, in any order. Submit the file as your deliverable.

- [x] Make the Danish-city handoff the sole test selected by `make test-live`. Create an isolated workspace, active goal, registered operator and real work grant. Bind a recorded operator call to the grant and use the public model to delegate the exact brief above with result type `text_file`.
- [x] Launch one real allocation using the pinned image. Verify that the default run starts exactly one signed-in worker Codex session and zero operator Codex sessions. Check the audited brief read, committing submission and scheduler-observed exit code of `0`.
- [x] After exit, start a fresh owner process with only the goal ID as its lookup input. Follow `GET /goals/{id}/history?view=activity` to the work item, attempt and observation. Retrieve `cities.txt` through HTTP and decode the stored content as UTF-8. Assert exactly five nonblank lines whose set matches the five supplied names in any order. Verify one attempt, one worker-attributed observation and goal status `active`.
- [x] Reuse a ready cluster and an already-built image when available. Measure a warm run with one model session and report any cluster startup and image build times separately. Use the measured baseline to set a wall-clock target.

## Extended live tests — opt-in

- [x] Add `make test-live-extended` for all existing signed-in scenarios, including chess delegation, fresh-session review and review of an incorrect result. Exclude the city test from this target. [Makefile](../Makefile)
- [x] Check pytest collection with each target’s selector. The default selection must contain exactly one test, the city handoff. The extended selection must retain every existing live test and have no test IDs in common with the default selection.

## Handoff and evidence

- [x] Update the [README](../README.md), [command catalog](../CATALOG.md) and [terminology](../TERMINOLOGY.md) with the file contract, byte limit and retrieval path. Document `make test-live` for worker image, launcher, MCP handoff and storage changes, and `make test-live-extended` for operator planning, delegation and evidence review.
- [x] Create and run `docs/SLICE10A_EVIDENCE.sh`. Report `make check`, `make test`, `make test-nomad` and `make test-live` separately. For the 10a handoff, also run `make test-live-extended` once to verify the existing chess contract after the prompt and result-type changes.
- [x] Capture the output in `docs/SLICE10A_EVIDENCE.md`. Include both live selections, the default run’s worker and operator session counts, the image digest, warm duration, isolation outcomes and positive controls. Record the references connecting the goal and revision to the work item, attempt, allocation, submitting call and saved file observation.

## Verification

The warm city handoff took 19.08 seconds against the 30-second development target. A fresh owner process retrieved `cities.txt` from observation 1 after the worker exited with code 0. The goal stayed active. Pytest collected one default case and nine disjoint extended cases. All passed. The offline suite passed 216 tests. Nomad passed seven tests and skipped its opt-in heartbeat-loss scenario. [Captured results](SLICE10A_EVIDENCE.md) · [Evidence script](SLICE10A_EVIDENCE.sh)
