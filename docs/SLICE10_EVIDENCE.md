# Slice 10 verification

Run at 2026-11-26 14:10:38 UTC.

## Worker image build

~~~text
dev/nomad/cluster.sh worker-image
 Container harness-nomad-0b269c4e35b3-worker-registry-1 Running
#0 building with "default" instance using docker driver

#1 [internal] load build definition from Dockerfile
#1 transferring dockerfile: 488B done
#1 DONE 0.0s

#2 [internal] load metadata for docker.io/library/node:24-bookworm-slim
#2 DONE 0.5s

#3 [internal] load .dockerignore
#3 transferring context: 70B done
#3 DONE 0.0s

#4 [internal] load build context
#4 transferring context: 36B done
#4 DONE 0.0s

#5 [1/6] FROM docker.io/library/node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530
#5 resolve docker.io/library/node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 0.0s done
#5 DONE 0.0s

#6 [3/6] RUN npm install --global @openai/codex@0.166.0 && test "$(codex --version)" = 'codex-cli 0.166.0'
#6 CACHED

#7 [5/6] WORKDIR /worker/task
#7 CACHED

#8 [4/6] RUN mkdir -p /worker/.codex /worker/task
#8 CACHED

#9 [2/6] RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
#9 CACHED

#10 [6/6] COPY --chmod=755 harness-worker /usr/local/bin/harness-worker
#10 CACHED

#11 exporting to image
#11 exporting layers done
#11 exporting manifest sha256:6159fd175584de122f81be5b6658694ef5b9eac22583368863f4d4980ec432d1 done
#11 exporting config sha256:10f572721072af0654ab33b0f30e0fcd753361f52cfc89edfcb2301017cec617 done
#11 exporting attestation manifest sha256:13db6f439b573c9ac349ecfe11fed0d51b4157eef7d0a416f3f965f7e163a29c 0.0s done
#11 exporting manifest list sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c
#11 exporting manifest list sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c 0.0s done
#11 naming to 127.0.0.1:14661/harness-worker:local done
#11 unpacking to 127.0.0.1:14661/harness-worker:local 0.0s done
#11 DONE 0.1s
The push refers to repository [127.0.0.1:14661/harness-worker]
1b1d337d4a7c: Layer already exists
fa47c2d97c6f: Layer already exists
b65f2e54b23e: Layer already exists
0efc7f2c8975: Layer already exists
bfaf5d99692a: Layer already exists
ee974a889cab: Layer already exists
4f4fb700ef54: Layer already exists
564121282df9: Pushed
e60bc0263b0b: Layer already exists
b1dd3d113aab: Layer already exists
63350cf7f178: Layer already exists
local: digest: sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c size: 856
127.0.0.1:14661/harness-worker@sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c
~~~

Exit code 0.

## Static checks

~~~text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
96 files already formatted
~~~

Exit code 0.

## Offline tests

~~~text
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests
plugins: anyio-4.16.0
collected 226 items / 17 deselected / 209 selected

packages/harness_api/tests/test_accounts.py .....                        [  2%]
packages/harness_api/tests/test_accounts_http.py .....                   [  4%]
packages/harness_api/tests/test_architecture.py .........                [  9%]
packages/harness_api/tests/test_delegated_completion.py ......           [ 11%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 19%]
....                                                                     [ 21%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 26%]
packages/harness_api/tests/test_goals.py ............................    [ 39%]
packages/harness_api/tests/test_http.py ..........                       [ 44%]
packages/harness_api/tests/test_nomad.py ......                          [ 47%]
packages/harness_api/tests/test_run_activity.py .....                    [ 49%]
packages/harness_api/tests/test_skill_source.py ..                       [ 50%]
packages/harness_api/tests/test_skills.py .....                          [ 53%]
packages/harness_api/tests/test_work.py .................                [ 61%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 64%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 70%]
packages/harness_mcp/tests/test_work_mcp.py ...                          [ 72%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 74%]
packages/harness_operator/tests/test_ask.py ........                     [ 77%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 79%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 81%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 89%]
..................                                                       [ 98%]
packages/harness_operator/tests/test_register.py ...                     [100%]

===================== 209 passed, 17 deselected in 28.23s ======================
~~~

Exit code 0.

## Real Nomad tests

~~~text
dev/nomad/cluster.sh server
 Container harness-nomad-0b269c4e35b3-server-1 Running
 Container harness-nomad-0b269c4e35b3-server-1 Waiting
 Container harness-nomad-0b269c4e35b3-server-1 Healthy
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"3fcc1e83-b1f0-98a0-4cd0-169ac9f61b1b","name":"harness-nomad-0b269c4e35b3-client","status":"ready","docker":true}
HARNESS_NOMAD_ADDR=http://127.0.0.1:14646 uv run --locked --all-packages pytest -q -s -m nomad
WorkloadStatus(state='succeeded', job_id='harness-6455020d55709727b657ca8b51b9b4d7509775169f7c117587445d29bbcc82fe', allocation_id='80901527-8e8a-33da-f6b7-2b851bb51a6d', exit_code=0, replacement_allocation_ids=()) allocations=1 restarts=0
stdout=slice9-5db2e869-cb1b-4cd5-9851-c9d90945b82d image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
.WorkloadStatus(state='failed', job_id='harness-e056e73c768259493ce7b2e04197282388304a430012358a7c292f86502fc357', allocation_id='8494a0cf-94c9-4f4d-6adf-36fc2c2e35da', exit_code=7, replacement_allocation_ids=()) allocations=1 restarts=0
.concurrent handles: harness-4bc0739a88e075f8bc29be55e5819e3a337df7645a71bd0b6e04fd5d39f6378e harness-4bc0739a88e075f8bc29be55e5819e3a337df7645a71bd0b6e04fd5d39f6378e
WorkloadStatus(state='stopped', job_id='harness-4bc0739a88e075f8bc29be55e5819e3a337df7645a71bd0b6e04fd5d39f6378e', allocation_id='72085730-0127-0685-41b3-446e6698b423', exit_code=137, replacement_allocation_ids=()) allocations=1 restarts=0
.Verified literal argv including ${NOMAD_ALLOC_ID} on allocation 3b6b3938-20b2-1290-f4ba-94fe9dcb958a
.WorkloadStatus(state='unknown', job_id='harness-03491a17ed5d458bafed34bcf003b8d3a897fecd6be5aaf464ac158318112c63', allocation_id='535ca9f1-a348-62c2-6794-f8328d44b99c', exit_code=None, replacement_allocation_ids=('6a4ed200-7d57-aea5-224a-0943bd61760d',)) additional workload starts=0
.ssame-image workload 127.0.0.1:14661/harness-worker@sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c allocation=172db06c-912d-941f-0a3d-56d5d9acb8ce has no login mount
.controlled transport fixture image=127.0.0.1:14661/harness-worker@sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c job=harness-24fadf1095615ea2adec82a1b1bfafa0dace118a16dc681be13c37efff147431 allocation=43866963-6455-887c-b063-d1e9ca775917 observation=1 read-only login mount verified
.
7 passed, 1 skipped, 218 deselected in 36.31s
~~~

Exit code 0.

## Signed-in acceptance

~~~text
uv run --locked --all-packages pytest -m live
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests
plugins: anyio-4.16.0
collected 226 items / 217 deselected / 9 selected

packages/harness_operator/tests/test_goal_plan_live.py ........          [ 88%]
packages/harness_operator/tests/test_work_live.py .                      [100%]

================ 9 passed, 217 deselected in 324.67s (0:05:24) =================
~~~

Exit code 0.

## Saved handoff

The successful signed-in handoff saved the following records. The test checked the fresh review against both cases and its execution flag, then checked that a fresh reviewer identified the controlled incorrect result and left the goal active.

~~~json
{
  "goal_id": 2,
  "goal_status": "active",
  "work_item_id": 1,
  "grant_id": 1,
  "operator_id": 1,
  "pinned_goal_revision": 1,
  "brief": "Prepare two contrasting pinned-rook move legality test cases for review. Give a shared FEN, side to move, king and rook squares, candidate moves, expected legality, and king-safety reasoning. For rejection, specify that the position and side to move stay unchanged.",
  "assigned_skills": [
    {
      "id": "chess-rules",
      "revision": 1
    },
    {
      "id": "go-testing",
      "revision": 1
    }
  ],
  "latest_attempt_id": 2,
  "attempts": [
    {
      "id": 1,
      "image": "127.0.0.1:14661/harness-worker@sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c",
      "state": "succeeded",
      "job_id": "harness-0ac03ef7704eb308bb3cfcb70711fbed68516fc631459c0612f4591a22398c08",
      "allocation_id": "4d3ddf91-31fb-c601-a3c6-1780eea15cf5",
      "exit_code": 0,
      "committing_call": {
        "run_id": 1,
        "sequence": 6
      },
      "worker_calls": [
        {
          "id": 1,
          "attempt_id": 1,
          "allocation_id": "4d3ddf91-31fb-c601-a3c6-1780eea15cf5",
          "tool": "get_work_brief",
          "recorded_at": "2026-11-26 14:16:32.278336",
          "outcome": "returned",
          "reason": null,
          "returned_skills": null,
          "evidence_id": null
        },
        {
          "id": 2,
          "attempt_id": 1,
          "allocation_id": "4d3ddf91-31fb-c601-a3c6-1780eea15cf5",
          "tool": "list_skills",
          "recorded_at": "2026-11-26 14:16:32.291144",
          "outcome": "returned",
          "reason": null,
          "returned_skills": [
            {
              "id": "chess-rules",
              "revision": 1
            },
            {
              "id": "go-testing",
              "revision": 1
            }
          ],
          "evidence_id": null
        },
        {
          "id": 3,
          "attempt_id": 1,
          "allocation_id": "4d3ddf91-31fb-c601-a3c6-1780eea15cf5",
          "tool": "read_skill",
          "recorded_at": "2026-11-26 14:16:35.726106",
          "outcome": "returned",
          "reason": null,
          "returned_skills": [
            {
              "id": "chess-rules",
              "revision": 1
            }
          ],
          "evidence_id": null
        },
        {
          "id": 4,
          "attempt_id": 1,
          "allocation_id": "4d3ddf91-31fb-c601-a3c6-1780eea15cf5",
          "tool": "read_skill",
          "recorded_at": "2026-11-26 14:16:35.743745",
          "outcome": "returned",
          "reason": null,
          "returned_skills": [
            {
              "id": "go-testing",
              "revision": 1
            }
          ],
          "evidence_id": null
        },
        {
          "id": 5,
          "attempt_id": 1,
          "allocation_id": "4d3ddf91-31fb-c601-a3c6-1780eea15cf5",
          "tool": "submit_work_result",
          "recorded_at": "2026-11-26 14:16:43.149994",
          "outcome": "returned",
          "reason": null,
          "returned_skills": null,
          "evidence_id": 1
        }
      ],
      "result": {
        "worker_call_id": 5,
        "evidence_id": 1,
        "recorded_at": "2026-11-26 14:16:43.150328",
        "fixture": {
          "cases": [
            {
              "expected_legal": false,
              "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
              "move": "e2f2",
              "reason": "White to move. White king e1, white rook e2, black king a8, black rook e8. Moving the rook to f2 opens the e-file, allowing the black rook on e8 to attack the white king on e1. Reject the move and preserve the original position and White to move."
            },
            {
              "expected_legal": true,
              "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
              "move": "e2e3",
              "reason": "White to move. White king e1, white rook e2, black king a8, black rook e8. Moving the rook to e3 keeps it between the black rook on e8 and the white king on e1, so the king remains safe."
            }
          ],
          "executed": false
        }
      }
    },
    {
      "id": 2,
      "image": "127.0.0.1:14661/harness-worker@sha256:16d722f3449962ff253783de8e4c0bfbf1bf781c4a691bff28d3a7c0429e953c",
      "state": "stopped",
      "job_id": "harness-aee255a2c289f19d98edcacce5265b934b5f2c08fc2133f409b58d48660c5c3b",
      "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
      "exit_code": 137,
      "committing_call": {
        "run_id": 3,
        "sequence": 1
      },
      "worker_calls": [
        {
          "id": 6,
          "attempt_id": 2,
          "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
          "tool": "submit_work_result",
          "recorded_at": "2026-11-26 14:17:19.364656",
          "outcome": "returned",
          "reason": null,
          "returned_skills": null,
          "evidence_id": 2
        },
        {
          "id": 7,
          "attempt_id": 2,
          "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
          "tool": "list_skills",
          "recorded_at": "2026-11-26 14:17:30.565351",
          "outcome": "returned",
          "reason": null,
          "returned_skills": [
            {
              "id": "chess-rules",
              "revision": 1
            },
            {
              "id": "go-testing",
              "revision": 1
            }
          ],
          "evidence_id": null
        },
        {
          "id": 8,
          "attempt_id": 2,
          "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
          "tool": "get_work_brief",
          "recorded_at": "2026-11-26 14:17:30.578622",
          "outcome": "returned",
          "reason": null,
          "returned_skills": null,
          "evidence_id": null
        },
        {
          "id": 9,
          "attempt_id": 2,
          "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
          "tool": "read_skill",
          "recorded_at": "2026-11-26 14:17:38.216037",
          "outcome": "returned",
          "reason": null,
          "returned_skills": [
            {
              "id": "go-testing",
              "revision": 1
            }
          ],
          "evidence_id": null
        },
        {
          "id": 10,
          "attempt_id": 2,
          "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
          "tool": "read_skill",
          "recorded_at": "2026-11-26 14:17:38.232643",
          "outcome": "returned",
          "reason": null,
          "returned_skills": [
            {
              "id": "chess-rules",
              "revision": 1
            }
          ],
          "evidence_id": null
        },
        {
          "id": 11,
          "attempt_id": 2,
          "allocation_id": "732f4b34-767e-bc39-6e2b-9afb26ce8ae7",
          "tool": "submit_work_result",
          "recorded_at": "2026-11-26 14:17:44.512618",
          "outcome": "denied",
          "reason": "This attempt already submitted a different result.",
          "returned_skills": null,
          "evidence_id": null
        }
      ],
      "result": {
        "worker_call_id": 6,
        "evidence_id": 2,
        "recorded_at": "2026-11-26 14:17:19.364923",
        "fixture": {
          "cases": [
            {
              "expected_legal": true,
              "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
              "move": "e2f2",
              "reason": "Rooks move horizontally."
            }
          ],
          "executed": false
        }
      }
    }
  ]
}
~~~

## Follow-up verification

After tightening selected-skill input validation, `make check` and `make test` passed again with 209 offline tests. The local client was restarted successfully with the login path generated from the calling shell.

Editing this script during execution started a redundant live invocation after the complete nine-test live run had passed. That duplicate invocation was stopped. The completed run is captured above.


## Post-implementation review

The review added three failing regressions before the fixes. They demonstrated
a delayed inspection overwriting a completed attempt, a submission conflict
being converted to `GoalValidationError`, and SQLite blocking the MCP event
loop. All three now pass.

The reviewed source passed `make check`, all 212 offline tests with warnings
treated as errors, and `ty check` for the three source packages. The real
Nomad suite passed seven cases with the opt-in heartbeat-loss case skipped.
All nine signed-in scenarios passed after the behavior and type fixes.

A subsequent security regression exposed an open infrastructure boundary.

~~~text
GET /v1/jobs through /secrets/api.sock with X-Nomad-Token: hw_invalid
HTTP 200

GET http://host.docker.internal:14646/v1/jobs without authentication
HTTP 200

test_trusted_worker_mount_and_signed_mcp
Expected management status 401, 403, or an unreachable endpoint
Observed management status 200
~~~

No job-list response bodies or credential contents were captured. This failure
reopens the infrastructure-isolation requirement. The current full Nomad suite reports six passing cases, one failing isolation
case, and one skipped opt-in heartbeat-loss case. The scope decision for cluster
ACLs and network/API hardening is pending.
