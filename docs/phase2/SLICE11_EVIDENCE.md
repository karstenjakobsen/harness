# Slice 11 evidence — 2026-11-27

## Container isolation and recovery follow-up

The updated real worker acceptance passed with Codex `danger-full-access` and
Docker's default security profiles. The rendered job has no `security_opt`
exceptions. One live Codex session read its brief and skill over MCP, wrote and
submitted `cities.txt`, and exited 0. Zero AI operator sessions were started.
Harness exported the exact file after scratch and runtime cleanup. The goal
remained active at revision 1.

| Observation | Actual value |
| --- | --- |
| Receipt | `.harness/phase2/slice11-wuoDrj/first/phase2/receipt.json` |
| Attempt | `phase2-b1a3f6af5a4d45ada3b729072d284163` |
| Nomad job | `phase2-2300f017cf5e4737b93f54dc2bbab2af` |
| Allocation | `67654c33-1314-cefe-85f0-d8ee9e4f0905` |
| Worker image | `sha256:bca5b3575cd7b4ef85d9e08f5a86de8c0b35dee5e637ddf3d7e350e3ad88db81` |
| Allocations / task restarts / exit code | 1 / 0 / 0 |
| Worker sessions / AI operator sessions | 1 / 0 |
| Workload observation time | 31.644 seconds |
| Recovered file SHA-256 | `9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d` |

The live command was

```sh
HARNESS_PHASE2_MCP_URL=http://host.docker.internal:8001/mcp make test-phase2
```

Both reported recovery bugs were reproduced by failing regressions before the
fix. The completed-allocation regression obstructs the final export once,
reopens the saved receipt and verifies successful retrieval with exactly one
Nomad submission and no additional scheduler requests. It also covers the older
`running` receipt format. The allocation ID and exit are persisted before the
first scheduler cleanup request.

The interruption regression kills a real runner after MCP startup and job
submission, then recovers from another CLI process. It verifies that the old
credential is denied, the listener is gone and the private runtime directory is
removed. It uses real SQLite files, owner CLI commands and an MCP server, with
Nomad supplied by a small HTTP fixture. A separate process test checks that
cleanup preserves a process with a different kernel start time or runtime
marker. An interrupted active run is stopped during recovery. Executing again
requires a fresh attempt.

The evidence script exited 0 with 248 tests passing and all three scheduler
smoke cases verified. It reuses this completed live session, inspects its
actual trace and performs fresh CLI reads and another artifact export. It also
checks grant revocation, listener shutdown and runtime removal, runs `make check`
and `make test`, and executes the three separate scheduler smoke cases. The
signed-in AI operator suite was outside these worker changes.

```sh
SLICE11_RECEIPT="$PWD/.harness/phase2/slice11-wuoDrj/first/phase2/receipt.json" \
  bash docs/phase2/SLICE11_EVIDENCE.sh
```

## Original acceptance run

The following record preserves the earlier run with `workspace-write` and the
owner-approved Docker exceptions. The follow-up above records the current
configuration.

Required live worker acceptance passed through the separate `seed`, `render` and
`run` entry points. The successful run started one real Codex worker session and
zero AI operator sessions. The worker read the brief and assigned skill through
MCP, wrote `cities.txt`, checked its bytes, submitted it through MCP and exited.
Fresh owner CLI processes retrieved the saved file after exit and after scratch
cleanup. The goal stayed active at revision 1.

| Observation | Actual value |
| --- | --- |
| Parent goal / child goal / revision | 1 / 2 / 1 |
| Work item / artifact / original grant | 1 / 1 / 1 |
| Attempt | `phase2-fd7956480c5a4f83806ccc520bdf7cf6` |
| Nomad job | `phase2-cf4c9a7d956f4d2a87eda4f80fbdd90f` |
| Allocation | `1319c6a9-3f2e-0880-c354-811096acd16b` |
| Worker image | `sha256:f4d50fe1b0bf6cd30f7d35df1eea2a676b6310c233aac11822b9410bb32ce0ad` |
| Codex version | `0.166.0` |
| Allocations / task restarts / exit code | 1 / 0 / 0 |
| Worker sessions / AI operator sessions | 1 / 0 |
| Nomad task runtime | 24.22143 seconds |
| Experiment elapsed before cleanup | 32.044 seconds |
| Recovered file SHA-256 | `9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d` |

The prepared inspection and exact Jinja-rendered job were saved before
submission. Worker-mode job arguments contain the generic worker bootstrap.
The assignment and expected city lines are kept in the fixture, and execution
results come from Nomad, the actual Codex JSONL trace and Harness reads. Current
worker receipts exclude the smoke-test command. The experiment records the
owner CLI command sequence as evidence that seeding used zero AI operator
sessions.

The worker recovered from an unavailable `python` executable by verifying the
file with `cmp` before its MCP submission. The image provides `python3`.

## Host configuration observed

The container's UID/GID was `1000:1000`. A credential-free container with that
identity successfully wrote through a mounted directory. The initial real
worker's file tools failed during Bubblewrap namespace creation under the
container's default profiles.

The owner explicitly approved per-job namespace exceptions. Docker rejected
`systempaths=unconfined` through Nomad's Docker API before that container could
start. The successful job used the approved subset `seccomp=unconfined` and
`apparmor=unconfined`. Its `harness-worker` entrypoint continued to select Codex's
`workspace-write` sandbox.

Docker Desktop's host network and the WSL process serving MCP had different
loopback interfaces. A credential-free probe established that
`http://host.docker.internal:8006/mcp` reached the WSL service. The final job used
that endpoint, an authenticated listener on `0.0.0.0:8006`, a writable scratch
volume and a read-only private runtime volume. Nomad dynamic host-volume
registration required server-generated volume IDs and matching reader/writer
capabilities. The experiment revoked its credential and removed its MCP server,
job, volume registrations, scratch and private runtime files.

The existing local cluster was reused. An idle client with a stale ACL
configuration was restarted from the checked-in configuration after confirming
there were no other registered workloads. The first smoke allocation had exited
0 but its filesystem recovery failed during that mismatch. Its failed receipt
was preserved. Cold cluster startup time was unmeasured. The smoke evidence
records the readiness check separately from each warm workload duration.

## Verification

`SLICE11_EVIDENCE.sh` exited 0. This evidence run reused the completed successful
worker's receipt, checked its actual JSONL trace, read the Harness audit and
artifact metadata again, and retrieved the file into another new file. It ran
`make check`, `make test` and `make test-phase2-smoke`. The optional smoke suite
proved two fresh successful city-file workspaces and one exit-7 allocation with
an absent deliverable and bounded cleanup. Those scheduler cases have their own
receipts. The signed-in operator suite was outside this slice's changes.

To repeat these evidence checks for the captured worker run, use the command
below from the repository root.

```sh
SLICE11_RECEIPT="$PWD/.harness/phase2/live-supported-namespace/phase2/receipt.json" \
  bash docs/phase2/SLICE11_EVIDENCE.sh
```

## Inputs for the next workload

The experiment needed a pinned image, task user identity, explicit MCP address,
private runtime credentials, reader/writer volume capabilities and a durable
Harness submission before scratch cleanup. Scheduler exit and artifact submission
were independent observations.

Choose a standing file-mode workload next. Its brief can ask the same worker to
set a file's mode and submit a report containing the path, observed mode and check
time. Reuse seed, render, manual submission and Harness retrieval, with the goal's
criteria defining how the report will be assessed.

## Captured evidence script output

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
112 files already formatted
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests, dev/phase2
plugins: anyio-4.16.0
collected 258 items / 14 deselected / 244 selected

packages/harness_api/tests/test_accounts.py .....                        [  2%]
packages/harness_api/tests/test_accounts_http.py .....                   [  4%]
packages/harness_api/tests/test_architecture.py .........                [  7%]
packages/harness_api/tests/test_delegated_completion.py ......           [ 10%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 16%]
....                                                                     [ 18%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 22%]
packages/harness_api/tests/test_goals.py ............................    [ 34%]
packages/harness_api/tests/test_http.py ..........                       [ 38%]
packages/harness_api/tests/test_nomad.py ......                          [ 40%]
packages/harness_api/tests/test_run_activity.py .....                    [ 42%]
packages/harness_api/tests/test_skill_source.py ..                       [ 43%]
packages/harness_api/tests/test_skills.py .....                          [ 45%]
packages/harness_api/tests/test_work.py ................................ [ 58%]
                                                                         [ 58%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 61%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 66%]
packages/harness_mcp/tests/test_worker.py .....                          [ 68%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 70%]
packages/harness_operator/tests/test_ask.py ........                     [ 73%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 74%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 76%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 77%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 84%]
.................                                                        [ 91%]
packages/harness_operator/tests/test_register.py ...                     [ 93%]
packages/harness_operator/tests/test_work_cli.py ....                    [ 94%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 95%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [ 97%]
dev/phase2/test_experiment.py .....                                      [100%]

===================== 244 passed, 14 deselected in 57.73s ======================
Required real worker acceptance, verified from retained trace and fresh CLI reads
{
  "receipt": "/home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/live-supported-namespace/phase2/receipt.json",
  "goal_id": 2,
  "goal_revision": 1,
  "work_item_id": 1,
  "attempt_id": "phase2-fd7956480c5a4f83806ccc520bdf7cf6",
  "job_id": "phase2-cf4c9a7d956f4d2a87eda4f80fbdd90f",
  "image": "sha256:f4d50fe1b0bf6cd30f7d35df1eea2a676b6310c233aac11822b9410bb32ce0ad",
  "allocation_id": "1319c6a9-3f2e-0880-c354-811096acd16b",
  "exit_code": 0,
  "file_sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d",
  "verified": true,
  "state": "complete",
  "allocation_count": 1,
  "task_restarts": 0,
  "worker_sessions": 1,
  "ai_operator_sessions": 0,
  "artifact_id": 1,
  "grant_id": 1,
  "workload_seconds": 32.044,
  "cleanup": {
    "job_removed": true,
    "scratch_removed": true
  }
}
Retrieved file after worker exit and scratch cleanup
København
Aarhus
Odense
Aalborg
Esbjerg
Optional scheduler smoke results
{"case": "first", "job_id": "phase2-2e011ee47217456295079f02a4136e6b", "allocation_id": "8509622c-bb6b-0d07-1d00-c2c4134e2a23", "exit_code": 0, "file_sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d", "verified": true, "state": "complete", "allocation_count": 1, "task_restarts": 0, "workload_seconds": 2.644, "cleanup": {"job_removed": true, "scratch_removed": true}}
{"case": "second", "job_id": "phase2-737e8b1bc621428ab50422c2f67319c0", "allocation_id": "34f5dbc9-84f8-ab0f-54cd-a26db14649e9", "exit_code": 0, "file_sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d", "verified": true, "state": "complete", "allocation_count": 1, "task_restarts": 0, "workload_seconds": 2.461, "cleanup": {"job_removed": true, "scratch_removed": true}}
{"case": "failure", "job_id": "phase2-fbe9421baba841ad811a8d48fc8e4a66", "allocation_id": "1f7f38d6-7eed-467b-d2f0-fd4c85a93ac0", "exit_code": 7, "file_sha256": null, "verified": true, "state": "failed", "allocation_count": 1, "task_restarts": 0, "workload_seconds": 4.016, "cleanup": {"job_removed": true, "scratch_removed": true}}
Fresh retrieval and smoke log saved under /home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/evidence-EGxF4g
```

## Captured container isolation and recovery evidence output

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
114 files already formatted
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests, dev/phase2
plugins: anyio-4.16.0
collected 262 items / 14 deselected / 248 selected

packages/harness_api/tests/test_accounts.py .....                        [  2%]
packages/harness_api/tests/test_accounts_http.py .....                   [  4%]
packages/harness_api/tests/test_architecture.py .........                [  7%]
packages/harness_api/tests/test_delegated_completion.py ......           [ 10%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 16%]
....                                                                     [ 17%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 22%]
packages/harness_api/tests/test_goals.py ............................    [ 33%]
packages/harness_api/tests/test_http.py ..........                       [ 37%]
packages/harness_api/tests/test_nomad.py ......                          [ 39%]
packages/harness_api/tests/test_run_activity.py .....                    [ 41%]
packages/harness_api/tests/test_skill_source.py ..                       [ 42%]
packages/harness_api/tests/test_skills.py .....                          [ 44%]
packages/harness_api/tests/test_work.py ................................ [ 57%]
                                                                         [ 57%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 60%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 65%]
packages/harness_mcp/tests/test_worker.py .....                          [ 67%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 69%]
packages/harness_operator/tests/test_ask.py ........                     [ 72%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 73%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 75%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 76%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 83%]
.................                                                        [ 90%]
packages/harness_operator/tests/test_register.py ...                     [ 91%]
packages/harness_operator/tests/test_work_cli.py ....                    [ 93%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 93%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [ 96%]
dev/phase2/test_experiment.py .........                                  [100%]

================ 248 passed, 14 deselected in 81.78s (0:01:21) =================
Required real worker acceptance, verified from retained trace and fresh CLI reads
{
  "receipt": "/home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/slice11-wuoDrj/first/phase2/receipt.json",
  "goal_id": 2,
  "goal_revision": 1,
  "work_item_id": 1,
  "attempt_id": "phase2-b1a3f6af5a4d45ada3b729072d284163",
  "job_id": "phase2-2300f017cf5e4737b93f54dc2bbab2af",
  "image": "sha256:bca5b3575cd7b4ef85d9e08f5a86de8c0b35dee5e637ddf3d7e350e3ad88db81",
  "allocation_id": "67654c33-1314-cefe-85f0-d8ee9e4f0905",
  "exit_code": 0,
  "file_sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d",
  "verified": true,
  "state": "complete",
  "allocation_count": 1,
  "task_restarts": 0,
  "worker_sessions": 1,
  "ai_operator_sessions": 0,
  "artifact_id": 1,
  "grant_id": 1,
  "workload_seconds": 31.644,
  "cleanup": {
    "job_removed": true,
    "scratch_removed": true
  }
}
Retrieved file after worker exit and scratch cleanup
København
Aarhus
Odense
Aalborg
Esbjerg
Optional scheduler smoke results
{"case": "first", "job_id": "phase2-c7ba6b35931d48159814bf6fce973251", "allocation_id": "6fe2ec25-2b0a-f33e-2dda-5d0deac0aff9", "exit_code": 0, "file_sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d", "verified": true, "state": "complete", "allocation_count": 1, "task_restarts": 0, "workload_seconds": 2.644, "cleanup": {"job_removed": true, "scratch_removed": true}}
{"case": "second", "job_id": "phase2-a6cf717107764f2b923c9716921530b8", "allocation_id": "85f9d516-e8f5-1f46-c07f-bb9fe5732cee", "exit_code": 0, "file_sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d", "verified": true, "state": "complete", "allocation_count": 1, "task_restarts": 0, "workload_seconds": 3.11, "cleanup": {"job_removed": true, "scratch_removed": true}}
{"case": "failure", "job_id": "phase2-ebd3bc76035d46bfbc876bc4620ac5a4", "allocation_id": "9ca13243-e6b2-93fa-7551-1aa8b3432e3c", "exit_code": 7, "file_sha256": null, "verified": true, "state": "failed", "allocation_count": 1, "task_restarts": 0, "workload_seconds": 3.107, "cleanup": {"job_removed": true, "scratch_removed": true}}
Fresh retrieval and smoke log saved under /home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/evidence-AF6aOO
```
