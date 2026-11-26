# Slice 10 — Delegate a goal revision to a Docker worker on Nomad

An owner asks for two pinned-rook test cases. The operator chooses the brief and skills, a Codex worker returns the cases, and a fresh operator session can review them from the goal ID alone. The deliverable includes the worker image and a real run on the local Slice 9 cluster. [Slice 10 design](SLICE10.md) · [Slice 9 execution contract](SLICE9_TODO.md#execution-contract)

## Save and launch the work

- [x] Add `operator goal grant-work GOAL_ID OPERATOR_ID`, `operator goal withdraw-work GRANT_ID` and `operator ask --work-grant GRANT_ID`. Expose `delegate_work(goal_id, expected_revision, brief, skill_revisions, retry_key)` through audited operator MCP. The operator chooses the brief and exact skill revisions.
- [x] In one public Harness model operation, check the open run and call, the exact active grant, target goal, expected revision and selected snapshots. Atomically save the work item, first attempt with its execution run ID, and link to the committing call. Use the shared SQLite schema. Keep the brief and pinned inputs on the work item and the image digest, execution identity and outcome on each attempt.
- [x] Commit the attempt as pending before dispatch. On startup or an authorized replay, a dispatcher can claim the pending attempt under the active grant. In one transaction, claim it once and record that dispatch may have begun. Only the dispatcher that committed the claim may send the first Nomad registration request, using the saved execution ID. An identical delegation replay retrieves the original work item and attempt. Changed inputs under the same key conflict.
- [x] Once dispatch may have begun, recovery looks up the Nomad job by the saved execution ID and verifies its spec before recording the observed allocation and outcome. Keep this lookup read-only, including when Harness crashed between committing the claim and sending the request. If the saved observations and retained Nomad records cannot establish the outcome, retain `unknown`. Only an explicit operator retry can launch a new attempt.
- [x] Expose audited `retry_work(work_item_id, expected_latest_attempt_id, retry_key)`. In one transaction recheck the exact grant and target, then look up the key before checking the latest attempt. An identical authorized replay returns the attempt created by the original call. Changed inputs under that key conflict. For a new key, compare the reviewed attempt ID with the work item’s latest attempt and append one attempt only if they match. A stale decision returns a conflict so the operator can reread history. Each attempt uses the original brief and pinned inputs. A changed brief requires a new work item.

- [x] When claiming a pending attempt or authorizing an intentional retry, recheck that the work item’s goal revision is current. If it changed, preserve the work item and record why the launch was declined. An already dispatched, still-authorized attempt may submit evidence against its original revision.

## Build the Docker worker and reuse local Codex auth

- [x] Check in a Dockerfile and worker executable. Pin the Codex CLI version and add a Make target that builds the image and yields a pullable `repository@sha256:…` reference for the local Nomad Docker driver. Configure that digest in Harness. Set the executable explicitly in `WorkloadSpec.argv[0]` because the adapter supplies the container entrypoint. The worker starts one noninteractive Codex session, reads its assignment through MCP, submits its result and exits. [Execution adapter](../packages/harness_api/src/harness_api/nomad.py)
- [x] For trusted local development only, have the worker launcher select the configured digest and mount the developer’s `${CODEX_HOME:-$HOME/.codex}/auth.json` read-only into a private worker Codex home at runtime. The worker process can read the developer’s login credential and cannot persist a refreshed login to that file. Give it writable scratch space and its own MCP configuration. If the login is missing, expired or keyring-only, report how to sign in or refresh on the host. Keep credential contents out of the build context, image layers, job spec, logs and evidence. [Codex authentication and credential storage](https://learn.chatgpt.com/docs/auth#credential-storage)
- [x] Reject image overrides and host paths at the delegation tool boundary. Attach the mount only when the trusted launcher dispatches an authorized worker attempt. Add a worker MCP endpoint reachable from the container in the selected workspace and configure it in the launcher.
- [x] Keep the owner HTTP endpoints, workspace database, Nomad management API and Docker socket outside the worker’s access.

## Authorize inputs and record the result

- [x] Authenticate the worker to Harness with an allocation-bound credential, such as a verified Nomad workload identity for the worker task. Check the expected job, task and original allocation against the saved attempt. The local Codex sign-in authenticates model calls only. On **every** worker read, write and replay, enforce the exact grant, work item and attempt. Withdrawal takes effect for open sessions. A replacement allocation or later grant cannot revive the old binding.
- [x] Expose the pinned brief and goal definition, `list_skills` and `read_skill` scoped to the assigned revisions, and result submission. Put the name and description in each repo-local `SKILL.md` alongside its instructions. Publish the edited chess and Go skills as new revisions and retain the existing manifest IDs and historical snapshots. Audit assignment, listing and an actual instruction read separately. [Skill importer](../packages/harness_api/src/harness_api/skill_source.py) · [Seed skills](../skills)
- [x] Define a bounded JSON fixture with position (FEN), candidate move, expected legality, reason, and whether the cases were executed. Set and test byte, case-count and field-length limits. Validate structure and leave chess correctness to the reviewer. Derive the submitting worker from the authenticated session and the requesting operator from the delegation. Atomically save one observation per attempt, its original goal revision and the committing call. Identical retries return that observation, and conflicting submissions leave it intact.
- [x] Accept a late result from attempt 1 after attempt 2 starts if attempt 1’s original allocation and session are still authorized. Record the submission time and observation under attempt 1. Attempt 2 remains latest and retains its own outcome and evidence. Present both attempts in creation order and let the reviewer judge their results.
- [x] Extend goal activity and run reads so a fresh operator and the owner over HTTP can follow the goal ID to the brief, delegating call, attempts, allocation IDs, image digest, assigned and read skill revisions, fixture, observation and exit status. Persist the observed scheduler outcome before Nomad collects it. Show a submitted fixture even if the container later failed, and an exit without a submission if that is what happened. Keep the pinned and current goal definitions inspectable after an edit. Completion continues to require its own decision and grant.

## Acceptance

- [x] **Offline authority.** Exercise a valid grant, assignment alone, a different goal, a different work item, an unassigned skill and a replacement allocation. Withdraw after worker authentication, regrant to the same operator, and verify that old sessions remain denied on reads, writes and retries. Check MCP discovery and direct invocation from an advisory session, and rejection of image and host-path overrides from a granted session. A denied call appends an audit entry and leaves the work item, attempts, observations, and goal state unchanged.
- [x] **Edit before dispatch.** Save work at revision 1, edit the goal to revision 2, then claim the attempt. Verify zero Nomad registrations and an inspectable reason naming both revisions. A new retry decision is also declined.
- [x] **Crash before dispatch.** Stop after committing the pending attempt and before claiming it. Reopen the database and race two recovery calls. Verify exactly one registration request for the saved execution ID, one attempt and the original committing call.
- [x] **Crash after dispatch may have begun.** Have a Nomad fixture accept registration, then interrupt Harness before it saves the reply. Reopen and recover by lookup. Verify the original job and allocation and zero additional registrations. Repeat with the fixture’s job record removed, and with an interruption immediately after the claim but before the request. Both recoveries must show `unknown` and issue zero registrations.
- [x] **Concurrent retry decisions.** Have two granted sessions review attempt 1 and retry with different keys. Exactly one creates attempt 2. Replay its key against expected attempt 1 and verify it returns attempt 2 and its original committing call. The other key conflicts. Assert exactly two attempts. After attempt 2 starts, submit results from both allocations, with attempt 1’s result arriving last. Verify goal history shows both observations under their respective attempts and still identifies attempt 2 as latest.
- [x] **Offline persistence.** Cover concurrent duplicate delegation and submission, changed payloads, rollback on a failed commit link, and a lost MCP reply followed by reopen. Verify one original committer per write. Edit the goal and import newer skills during execution, then read the assigned instructions and save the result against the original revision. Exercise an exit with no submission.
- [x] **Local login on real Nomad.** Record the worker image digest and verify that `codex --version` inside it matches the pin. Make a signed-in model call in the worker, then make one on the host using the same local login after the worker exits. Using the ordinary Slice 9 launch path, run the **same image digest** and inspect its mounts to verify the login file was never attached. Record outcomes without printing credentials.
- [x] **Real handoff.** In a temporary CLI workspace create an active chess subgoal, register an operator and grant delegation. Ask “Prepare two test cases showing when a pinned rook may move and when it may not.” Supply no skill IDs or expected moves. Verify the chosen brief and revisions, one real allocation running the built digest with the local login, audited reads, both submitted cases and the observed exit. The goal stays active.
- [x] **Fresh review.** End the delegating session. Give a fresh advisory session only the goal ID and ask what the worker delivered, what was verified and whether the cases need correction. Check the position, move and expected outcome it reports for each case against the saved fixture and the owner’s HTTP reads. For a fixture marked unexecuted and an exit of `0`, the review must still identify that the move generator was never run.
- [x] **Judgment.** In a separate controlled handoff, submit a well-formed case that incorrectly allows the rook to expose its king. Verify the reviewer identifies the error from the saved position and leaves the goal open. Let the operator decide whether to request a correction.
- [x] Document the build, local auth prerequisite, delegation commands and review path in the [README](../README.md), [command catalog](../CATALOG.md) and [terminology](../TERMINOLOGY.md). Run and report `make check`, `make test`, `make test-nomad` and signed-in `make test-live` separately. Create and run `docs/SLICE10_EVIDENCE.sh`, capture its output in `docs/SLICE10_EVIDENCE.md`, and include the digest and goal-to-result references before cleaning up the test jobs.

## Verification

`make check` and all 209 offline tests passed. Real Nomad verification passed
seven cases, with the existing opt-in heartbeat-loss case skipped. All nine
signed-in scenarios passed, including the real worker, fresh review and the
controlled incorrect fixture. The [evidence script](SLICE10_EVIDENCE.sh) and
[captured records](SLICE10_EVIDENCE.md) include the pinned image, brief, skill
reads, allocations, both fixtures and the goal's active status.


## Post-implementation review

The review fixed stale inspection results overwriting a finished attempt,
preserved `GoalConflictError` for conflicting submissions, and moved SQLite
operations off the worker MCP event loop. Shared call and delegation types now
pass type checking. Test SQLite connections are closed explicitly and the live
fixtures reserve their listening sockets and verify service shutdown.

At the Slice 10 review, one original boundary remained open. With ACLs disabled, the development
Nomad task API returned HTTP 200 for `GET /v1/jobs` with an invalid token.
Docker Desktop also exposed the loopback-published server at
`host.docker.internal:14646` to the worker without authentication. The passing
MCP grant tests establish the Harness authorization contract. Cluster/API
isolation requires further hardening.

- [x] From a real worker, deny management requests through both the task socket
  and the host gateway. Cover invalid credentials and the worker's own
  credential, while keeping the trusted launcher and original-allocation guard
  working. Verify owner HTTP isolation as part of the infrastructure change.

Slice 10a verified denied management reads through both routes, a successful owner HTTP read with the host credential, denial from the worker, and scoped worker MCP access. [Slice 10a isolation results](SLICE10A_EVIDENCE.md#real-nomad-isolation-and-execution)
