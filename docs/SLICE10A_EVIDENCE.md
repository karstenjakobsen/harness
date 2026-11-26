# Slice 10a verification

Run at 2026-11-26 16:10:17 UTC.

## Pytest collection

~~~text
test-live
packages/harness_operator/tests/test_work_live.py::test_danish_city_file_handoff
test-live-extended
packages/harness_operator/tests/test_goal_plan_live.py::test_advisory_chess_plan_reads_versioned_skills
packages/harness_operator/tests/test_goal_plan_live.py::test_ask_explains_monday_progress_before_and_after_revision
packages/harness_operator/tests/test_goal_plan_live.py::test_ask_explains_saved_plan_through_mcp
packages/harness_operator/tests/test_goal_plan_live.py::test_delegated_operator_decides_when_membership_evidence_is_sufficient
packages/harness_operator/tests/test_goal_plan_live.py::test_delegated_operator_saves_subgoals
packages/harness_operator/tests/test_goal_plan_live.py::test_message_draft_sets_distinct_date_target_and_window
packages/harness_operator/tests/test_goal_plan_live.py::test_operator_creates_and_revises_draft_with_http_attribution
packages/harness_operator/tests/test_goal_plan_live.py::test_operator_reconstructs_another_operators_revision
packages/harness_operator/tests/test_work_live.py::test_operator_delegates_and_fresh_session_reviews_worker
The two selections have disjoint test IDs.
~~~

Exit code 0. Elapsed 3 s.

## Static checks

~~~text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
102 files already formatted
~~~

Exit code 0. Elapsed 0 s.

## Offline tests

~~~text
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests
plugins: anyio-4.16.0
collected 234 items / 18 deselected / 216 selected

packages/harness_api/tests/test_accounts.py .....                        [  2%]
packages/harness_api/tests/test_accounts_http.py .....                   [  4%]
packages/harness_api/tests/test_architecture.py .........                [  8%]
packages/harness_api/tests/test_delegated_completion.py ......           [ 11%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 18%]
....                                                                     [ 20%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 25%]
packages/harness_api/tests/test_goals.py ............................    [ 38%]
packages/harness_api/tests/test_http.py ...........                      [ 43%]
packages/harness_api/tests/test_nomad.py ......                          [ 46%]
packages/harness_api/tests/test_run_activity.py .....                    [ 48%]
packages/harness_api/tests/test_skill_source.py ..                       [ 49%]
packages/harness_api/tests/test_skills.py .....                          [ 51%]
packages/harness_api/tests/test_work.py .....................            [ 61%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 64%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 70%]
packages/harness_mcp/tests/test_work_mcp.py ....                         [ 72%]
packages/harness_mcp/tests/test_worker_scratch.py .                      [ 73%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 75%]
packages/harness_operator/tests/test_ask.py ........                     [ 78%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 80%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 82%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 90%]
..................                                                       [ 98%]
packages/harness_operator/tests/test_register.py ...                     [100%]

===================== 216 passed, 18 deselected in 29.34s ======================
~~~

Exit code 0. Elapsed 33 s.

## Cluster startup or reuse

~~~text
dev/nomad/cluster.sh server
 Container harness-nomad-0b269c4e35b3-server-1 Running 
 Container harness-nomad-0b269c4e35b3-server-1 Waiting 
 Container harness-nomad-0b269c4e35b3-server-1 Healthy 
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"ccc93a6d-75af-ddf3-6151-3249d138e594","name":"harness-nomad-0b269c4e35b3-client","status":"ready","docker":true}
~~~

Exit code 0. Elapsed 1 s.

## Worker image build or reuse

~~~text
dev/nomad/cluster.sh worker-image
 Container harness-nomad-0b269c4e35b3-worker-registry-1 Running 
#0 building with "default" instance using docker driver

#1 [internal] load build definition from Dockerfile
#1 transferring dockerfile: 538B done
#1 DONE 0.0s

#2 [internal] load metadata for docker.io/library/node:24-bookworm-slim
#2 ...

#3 [auth] library/node:pull token for registry-1.docker.io
#3 DONE 0.0s

#2 [internal] load metadata for docker.io/library/node:24-bookworm-slim
#2 DONE 1.2s

#4 [internal] load .dockerignore
#4 transferring context: 86B done
#4 DONE 0.0s

#5 [internal] load build context
#5 transferring context: 4.74kB done
#5 DONE 0.0s

#6 [1/7] FROM docker.io/library/node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530
#6 resolve docker.io/library/node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 0.0s done
#6 DONE 0.0s

#7 [2/7] RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
#7 CACHED

#8 [3/7] RUN npm install --global @openai/codex@0.166.0 && test "$(codex --version)" = 'codex-cli 0.166.0'
#8 CACHED

#9 [4/7] RUN mkdir -p /worker/.codex /worker/task
#9 CACHED

#10 [5/7] WORKDIR /worker/task
#10 CACHED

#11 [6/7] COPY --chmod=755 harness-worker /usr/local/bin/harness-worker
#11 CACHED

#12 [7/7] COPY worker-mcp.mjs /usr/local/lib/worker-mcp.mjs
#12 DONE 0.0s

#13 exporting to image
#13 exporting layers 119.3s done
#13 exporting manifest sha256:c7f54ff95f4013d68f3d30c0ab9c722235edfddd64a621e7fa8fe7500d9017f4 0.0s done
#13 exporting config sha256:d1d9bfd47cfbd0e7530b1602917ce7125fdf4b60082cc64e117e9f904de53c5a 0.0s done
#13 exporting attestation manifest sha256:d988d87db6e969f8178323f1d0b91fa4f9b6241166e78c39152723820fd6f9de 0.0s done
#13 exporting manifest list sha256:40db34e858694fa1f43a50e4b191dcbc08410c71951903227c7d301550e27d0f 0.0s done
#13 naming to 127.0.0.1:14661/harness-worker:local
#13 naming to 127.0.0.1:14661/harness-worker:local done
#13 unpacking to 127.0.0.1:14661/harness-worker:local
#13 unpacking to 127.0.0.1:14661/harness-worker:local 3.2s done
#13 DONE 122.7s
The push refers to repository [127.0.0.1:14661/harness-worker]
bfaf5d99692a: Layer already exists
5303e50c4c88: Pushed
63350cf7f178: Layer already exists
0efc7f2c8975: Layer already exists
b65f2e54b23e: Layer already exists
b1dd3d113aab: Layer already exists
1b1d337d4a7c: Layer already exists
4f4fb700ef54: Layer already exists
4614efde3217: Layer already exists
fa47c2d97c6f: Layer already exists
ee974a889cab: Layer already exists
025902a6a0cd: Pushed
local: digest: sha256:40db34e858694fa1f43a50e4b191dcbc08410c71951903227c7d301550e27d0f size: 856
127.0.0.1:14661/harness-worker@sha256:40db34e858694fa1f43a50e4b191dcbc08410c71951903227c7d301550e27d0f
~~~

Exit code 0. Elapsed 10 s.

## Real Nomad isolation and execution

~~~text
dev/nomad/cluster.sh server
 Container harness-nomad-0b269c4e35b3-server-1 Running 
 Container harness-nomad-0b269c4e35b3-server-1 Waiting 
 Container harness-nomad-0b269c4e35b3-server-1 Healthy 
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"ccc93a6d-75af-ddf3-6151-3249d138e594","name":"harness-nomad-0b269c4e35b3-client","status":"ready","docker":true}
HARNESS_NOMAD_TOKEN_FILE="/home/karsten/projects/github/karstenjakobsen/harness/.harness/nomad/acl/launcher" HARNESS_NOMAD_ADDR=http://127.0.0.1:14646 uv run --locked --all-packages pytest -q -s -m nomad
WorkloadStatus(state='succeeded', job_id='harness-da36122ead8a7a3032f263cc3f1c40e586c659026d9a3561595f080254598821', allocation_id='5ced8e7b-d03f-f02f-27d8-394f69fd14f9', exit_code=0, replacement_allocation_ids=()) allocations=1 restarts=0
stdout=slice9-0f973026-a2cd-4507-90a0-85949f36914f image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
.WorkloadStatus(state='failed', job_id='harness-ed81f0aa016894258386233ebca2b825051ad71aaaa61f8b7afa21635fbabaff', allocation_id='cbd9fa7e-0c60-a680-6986-ec035c7b994c', exit_code=7, replacement_allocation_ids=()) allocations=1 restarts=0
.concurrent handles: harness-f6438f8c309b60e08ecfb43d75eaba2bd83ad0c7a462c3fbfe24452cfc895a03 harness-f6438f8c309b60e08ecfb43d75eaba2bd83ad0c7a462c3fbfe24452cfc895a03
WorkloadStatus(state='stopped', job_id='harness-f6438f8c309b60e08ecfb43d75eaba2bd83ad0c7a462c3fbfe24452cfc895a03', allocation_id='3ae5d3d4-b396-5e91-ce81-49b482bb9ba1', exit_code=137, replacement_allocation_ids=()) allocations=1 restarts=0
.Verified literal argv including ${NOMAD_ALLOC_ID} on allocation ee1e8a03-7f18-fad6-7581-88b7cd4073a5
.WorkloadStatus(state='unknown', job_id='harness-fd1e8abf6322e35fdb61fddf8acfa89bf9d5eff4ee60208ba193f809d7635182', allocation_id='830a66b1-46c0-b514-2af7-1752dbad25fb', exit_code=None, replacement_allocation_ids=('b5addced-75e6-24d8-3ae9-d48311396a25',)) additional workload starts=0
.smake[1]: Entering directory '/home/karsten/projects/github/karstenjakobsen/harness'
make[1]: '.harness/nomad/worker-image' is up to date.
make[1]: Leaving directory '/home/karsten/projects/github/karstenjakobsen/harness'
same-image workload 127.0.0.1:14661/harness-worker@sha256:40db34e858694fa1f43a50e4b191dcbc08410c71951903227c7d301550e27d0f allocation=7d5b62bd-92cb-5958-7115-45196017e3d1 has no login mount
.task_socket missing 401
task_socket invalid 403
task_socket worker 403
host_gateway missing 403
host_gateway invalid 403
host_gateway worker 403
worker_service_host missing unreachable
worker_service_host invalid unreachable
worker_service_host worker unreachable
owner HTTP host.docker.internal missing 401
owner HTTP host.docker.internal worker 401
owner HTTP 172.26.180.200 missing unreachable
owner HTTP 172.26.180.200 worker unreachable
owner HTTP 127.0.0.1 missing unreachable
owner HTTP 127.0.0.1 worker unreachable
worker MCP brief and submission succeeded
launcher registered and inspected harness-0489bd40efd7179ff209ee79f84a736283999a8c53dbcd9c983ba4fcb223509c allocation=e633e3c8-6046-531a-d80a-27bd881f9ec7 observation=1 owner HTTP=200
.
7 passed, 1 skipped, 226 deselected in 48.11s
~~~

Exit code 0. Elapsed 53 s.

## Warm Danish-city file handoff

~~~text
HARNESS_NOMAD_TOKEN_FILE="/home/karsten/projects/github/karstenjakobsen/harness/.harness/nomad/acl/launcher" uv run --locked --all-packages pytest -m "live and city_file"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests
plugins: anyio-4.16.0
collected 234 items / 233 deselected / 1 selected

packages/harness_operator/tests/test_work_live.py make[1]: Entering directory '/home/karsten/projects/github/karstenjakobsen/harness'
dev/nomad/cluster.sh server
 Container harness-nomad-0b269c4e35b3-server-1 Running 
 Container harness-nomad-0b269c4e35b3-server-1 Waiting 
 Container harness-nomad-0b269c4e35b3-server-1 Healthy 
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"ccc93a6d-75af-ddf3-6151-3249d138e594","name":"harness-nomad-0b269c4e35b3-client","status":"ready","docker":true}
make[1]: Leaving directory '/home/karsten/projects/github/karstenjakobsen/harness'
make[1]: Entering directory '/home/karsten/projects/github/karstenjakobsen/harness'
make[1]: '.harness/nomad/worker-image' is up to date.
make[1]: Leaving directory '/home/karsten/projects/github/karstenjakobsen/harness'
{"goal": 1, "revision": 1, "item": 1, "attempt": 1, "allocation": "ab5902c3-1e50-7bca-b550-f40cc8945299", "image": "127.0.0.1:14661/harness-worker@sha256:40db34e858694fa1f43a50e4b191dcbc08410c71951903227c7d301550e27d0f", "result": {"worker_call_id": 3, "evidence_id": 1, "recorded_at": "2026-11-26 16:12:16.869838", "text_file": {"content": "København\nAarhus\nOdense\nAalborg\nEsbjerg\n", "filename": "cities.txt"}}, "status": "active"}
warm handoff=18.61s worker Codex sessions=1 operator Codex sessions=0
.

====================== 1 passed, 233 deselected in 21.03s ======================
~~~

Exit code 0. Elapsed 25 s.

## Extended signed-in scenarios

~~~text
HARNESS_NOMAD_TOKEN_FILE="/home/karsten/projects/github/karstenjakobsen/harness/.harness/nomad/acl/launcher" uv run --locked --all-packages pytest -m "live and not city_file"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests
plugins: anyio-4.16.0
collected 234 items / 225 deselected / 9 selected

packages/harness_operator/tests/test_goal_plan_live.py .....
Owner's question
Goal ID 1.
Who changed the success criteria for this goal, what changed, and which run and call saved it?

Signed-in operator B's reply
**Goal 1, “Join the library,” is active at revision 2.** Registered operator **ID 1** changed the success criteria under definition grant **ID 1**. The run record identifies the operator by ID only.

- **Revision 1** required active library membership.
- **Revision 2** kept that requirement and added successful completion of the first checkout.

**Run 1, call 3** (`revise_goal`) saved revision 2 on November 26, 2026, at 16:14:28. The run log confirms that the call targeted revision 1, committed revision 2, and returned successfully.

Verified HTTP response excerpts
{
  "/goals/1/history?view=activity": {
    "revision_1_criteria": "Membership is active",
    "revision_2_criteria": "Library membership is active and the first checkout has been completed successfully.",
    "committing_call": {
      "run_id": 1,
      "sequence": 3
    },
    "activity_read": {
      "run_id": 2,
      "sequence": 2
    }
  },
  "/runs/1": {
    "operator_id": 1,
    "definition_grant": {
      "id": 1,
      "operator_id": 1,
      "action": "revise_goal",
      "goal_id": 1
    },
    "call": {
      "sequence": 3,
      "tool": "revise_goal",
      "outcome": "returned",
      "committed_revision": {
        "goal_id": 1,
        "revision": 2
      }
    }
  },
  "/runs/2": {
    "operator_id": 2,
    "granted_goal_id": 3,
    "calls": [
      {
        "sequence": 2,
        "tool": "get_goal_activity",
        "outcome": "returned",
        "returned_history": {
          "goal_id": 1,
          "timeline": [
            {
              "kind": "revision",
              "revision": 1,
              "committing_call": null
            },
            {
              "run_id": 1,
              "sequence": 1,
              "kind": "call",
              "at": "2026-11-26 16:14:26.047010",
              "tool": "get_goal_tree",
              "outcome": "returned",
              "relationship": "requested"
            },
            {
              "run_id": 1,
              "sequence": 3,
              "kind": "call",
              "at": "2026-11-26 16:14:28.297301",
              "tool": "revise_goal",
              "outcome": "returned",
              "relationship": "revision_target"
            },
            {
              "kind": "revision",
              "revision": 2,
              "committing_call": {
                "run_id": 1,
                "sequence": 3
              }
            },
            {
              "run_id": 2,
              "sequence": 1,
              "kind": "call",
              "at": "2026-11-26 16:14:38.620163",
              "tool": "list_goals",
              "outcome": "returned",
              "relationship": "listed"
            }
          ]
        }
      },
      {
        "sequence": 3,
        "tool": "get_run",
        "outcome": "returned",
        "returned_history": {
          "run_id": 1,
          "outcome": "succeeded",
          "calls": [
            {
              "run_id": 1,
              "sequence": 1,
              "outcome": "returned",
              "committed_event_id": null,
              "retrieved_event_id": null,
              "committed_revision": null,
              "retrieved_revision": null
            },
            {
              "run_id": 1,
              "sequence": 2,
              "outcome": "returned",
              "committed_event_id": null,
              "retrieved_event_id": null,
              "committed_revision": null,
              "retrieved_revision": null
            },
            {
              "run_id": 1,
              "sequence": 3,
              "outcome": "returned",
              "committed_event_id": null,
              "retrieved_event_id": null,
              "committed_revision": {
                "goal_id": 1,
                "revision": 2
              },
              "retrieved_revision": null
            }
          ]
        }
      }
    ]
  }
}
B's run made no goal changes.
.
Owner's question
For my ‘Build a chess game in Go’ goal, what subgoals would you propose, and how would you verify that a move cannot leave your own king in check?

Signed-in operator's reply
**Build a chess game in Go** · Goal #1 · Active at revision 1, with no saved subgoals or success criteria.

I’d start with a two-player terminal game and propose four subgoals:

1. **Represent a position.** Store the board, side to move, castling rights, en passant target, and move counters. Verify that a FEN fixture loads the expected state.
2. **Generate legal moves.** Implement piece movement and attack detection, then filter candidates for king safety. Cover promotion, en passant, and castling with focused tests.
3. **Determine game outcomes.** Verify checkmate, stalemate, and draw conditions with known positions or move sequences.
4. **Make a game playable.** Accept coordinate moves in the terminal, display the board, and report invalid moves and the result. Verify a complete game through that interface.

### Verify king safety

Apply each candidate move to a copy of the position, including any capture, then ask whether the opponent attacks the **moving side’s king** on the resulting board. Use a square-attack function so pawn attacks and attacks by pinned pieces are handled correctly. For castling, also check the king’s starting and transit squares.

Start with a table-driven Go test using `k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1`. White’s rook on e2 shields its king on e1 from Black’s rook on e8.

| Candidate | Expected result | Why |
|---|---|---|
| `e2f2` | Illegal | Moving sideways opens the e-file and exposes White’s king. |
| `e2e3` | Legal | The rook still blocks the e-file. |

Use a fresh position for each case. Through the public move API, also verify that rejecting `e2f2` preserves the board and leaves White to move. If the engine exposes a legal move list, check that it excludes `e2f2` and includes `e2e3`.

**Small next step:** Build enough position handling to load that fixture, then make both cases pass with `go test ./...`.

Verified HTTP response excerpts
{
  "/runs/1": {
    "mode": "advisory",
    "outcome": "succeeded",
    "calls": [
      {
        "sequence": 1,
        "tool": "list_skills",
        "outcome": "returned",
        "returned_skills": [
          {
            "id": "chess-rules",
            "revision": 2
          },
          {
            "id": "go-testing",
            "revision": 2
          }
        ]
      },
      {
        "sequence": 4,
        "tool": "read_skill",
        "outcome": "returned",
        "returned_skills": [
          {
            "id": "chess-rules",
            "revision": 2
          }
        ]
      },
      {
        "sequence": 5,
        "tool": "read_skill",
        "outcome": "returned",
        "returned_skills": [
          {
            "id": "go-testing",
            "revision": 2
          }
        ]
      }
    ]
  },
  "/skills/chess-rules/revisions/2": {
    "source_path": "skills/chess-rules",
    "commit_sha": "406f55bcbabefec7eb208b48667ffa70d7952387",
    "content_hash": "6ec1c969094073364daa44f741e41cf1cef1152bc594fe2252b9753342a38f1a",
    "instructions_excerpt": "---\nname: chess-rules\ndescription: Plan legal move generation and verify check, pins and king safety.\n---\n\n# Verify king safety"
  },
  "/skills/chess-rules/revisions/2/reads": [
    {
      "run_id": 1,
      "sequence": 4
    }
  ],
  "/skills/go-testing/revisions/2": {
    "source_path": "skills/go-testing",
    "commit_sha": "406f55bcbabefec7eb208b48667ffa70d7952387",
    "content_hash": "cc5ec757f99961664ed2f12abdec6974044e8aa5a3c105f90ddad17dff97ed3c",
    "instructions_excerpt": "---\nname: go-testing\ndescription: Turn rules and counterexamples into table-driven Go tests with explicit expected results.\n---\n\n# Test a move rule in Go"
  },
  "/skills/go-testing/revisions/2/reads": [
    {
      "run_id": 1,
      "sequence": 5
    }
  ]
}
Goal 1 after the run: revision 1, 0 descendants.
.