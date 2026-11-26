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
Owner request
Break my “Build a chess game in Go” goal into subgoals and save them for review. For each subgoal, say how we could tell it was done.

Advisory reply (zero children saved)
**Build a chess game in Go** (goal #1) is active at revision 1 and has no saved subgoals. Subgoal creation is unavailable this turn, so the plan below is proposed for review and remains unsaved.

I’ve assumed a local, two-player terminal game for the first playable version.

| Proposed subgoal | How to tell it’s done |
|---|---|
| 1. Model the board and game state | Go tests verify the standard starting position, White to move, and correct board and turn updates after a move and a capture. |
| 2. Enforce ordinary moves and king safety | Table-driven tests cover each piece’s movement, blockers, captures, and check. With White’s king on e1 and rook on e2, and Black’s king on a8 and rook on e8, `e2f2` is rejected without changing the board or turn, while `e2e3` is accepted. |
| 3. Implement special moves | Tests verify both sides of each rule, including castling through an attacked square, en passant after its one-turn window, and all four promotion choices. |
| 4. Detect game endings | Known positions and move sequences produce the expected results for checkmate, stalemate, dead positions, and draws by repetition or move count. Tests distinguish claimable draws from automatic draws. |
| 5. Make a game playable in the terminal | Two players can start a game, enter moves, recover from invalid input, and finish with the correct result. A scripted Fool’s Mate verifies the full loop, and `go test ./...` passes. |

**Small next step:** Write the starting-position test. Check all 32 pieces and verify that White moves first.

Delegated reply
**#1 · Active · Build a chess game in Go**
I saved four draft subgoals and verified them in goal #1’s tree. Open each child by ID to review its saved success criteria. The plan assumes a local two-player terminal game.

- **#2 · Draft · Represent and update chess positions.** Done when Go tests verify the starting board and turn, FEN round-trips, state updates after a quiet move and a capture, and rejection of malformed FEN.
- **#3 · Draft · Generate legal moves and enforce king safety.** Done when tests verify piece movement and responses to check, count 20 legal opening moves, and show that a pinned rook can play `e2e3` while `e2f2` is rejected without changing the board or turn.
- **#4 · Draft · Implement special moves and game results.** Done when tests cover castling, en passant, all four promotion choices, checkmate, stalemate, and draw rules, and verify that play stops once the game ends.
- **#5 · Draft · Deliver a playable two-player terminal game.** Done when players can see the board and turn, enter moves, and see the result. A scripted Fool’s Mate must show Black winning by checkmate and verify that invalid input leaves the same player to move. `go test ./...` must pass.

A small first step is to write the starting-position test for #2.

/goals/1/history?view=activity → /runs/2
Operator 1, grant 1, parent 1 at revision 1 (active)
Call 6 → /goals/2/history?view=activity → revision 1, draft: Represent and update chess positions
  Table-driven Go tests verify the standard starting position and side to move, FEN round-trips preserving board, turn, castling rights, en passant target and move counters, and correct state updates after a quiet move and a capture. Malformed FEN returns an error.
Call 7 → /goals/3/history?view=activity → revision 1, draft: Generate legal moves and enforce king safety
  Separate candidate generation from king-safety filtering. Table-driven Go tests cover piece movement, blockers, captures, and responding to check. From FEN k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1, e2f2 is illegal and leaves the board and side to move unchanged when rejected, while e2e3 is legal. The starting position has 20 legal moves.
Call 8 → /goals/4/history?view=activity → revision 1, draft: Implement special moves and game results
  Table-driven Go tests cover castling on either side and rejection through check, en passant and its expiry, and promotion to each of the four valid pieces. Tests distinguish checkmate from stalemate and verify dead positions and the claimable and automatic repetition and move-count draws. Terminal games reject further moves.
Call 9 → /goals/5/history?view=activity → revision 1, draft: Deliver a playable two-player terminal game
  Two local players can start a game, see the board and whose turn it is, enter coordinate moves including promotion, and see the final result. A scripted session plays Fool’s Mate, checks that an invalid move leaves the same player to move, and verifies that Black wins by checkmate. go test ./... passes.
Call 3 list_skills → [{'id': 'chess-rules', 'revision': 2}, {'id': 'go-testing', 'revision': 2}]
Call 4 read_skill → [{'id': 'chess-rules', 'revision': 2}]
Call 5 read_skill → [{'id': 'go-testing', 'revision': 2}]
.
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
{
  "goal_id": 2,
  "work_item_id": 1,
  "delegating_call": {
    "run_id": 1,
    "sequence": 6
  },
  "brief": "Prepare exactly two pinned-rook legality fixtures on the same four-piece board, White to move: White king e1 and rook e2, Black king a8 and rook e8, all other squares empty (FEN k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1). Expect e2e3 legal because it keeps blocking the e-file, and e2f2 illegal because it exposes White's king. For rejection, note that the board and side to move should stay unchanged.",
  "assigned_skills": [
    {
      "id": "chess-rules",
      "revision": 2
    },
    {
      "id": "go-testing",
      "revision": 2
    }
  ],
  "worker_calls": [
    {
      "id": 1,
      "attempt_id": 1,
      "allocation_id": "025022c8-1a7f-a793-ee7e-7f6ca3746a11",
      "tool": "list_skills",
      "recorded_at": "2026-11-26 16:17:06.614515",
      "outcome": "returned",
      "reason": null,
      "returned_skills": [
        {
          "id": "chess-rules",
          "revision": 2
        },
        {
          "id": "go-testing",
          "revision": 2
        }
      ],
      "evidence_id": null
    },
    {
      "id": 2,
      "attempt_id": 1,
      "allocation_id": "025022c8-1a7f-a793-ee7e-7f6ca3746a11",
      "tool": "get_work_brief",
      "recorded_at": "2026-11-26 16:17:06.681687",
      "outcome": "returned",
      "reason": null,
      "returned_skills": null,
      "evidence_id": null
    },
    {
      "id": 3,
      "attempt_id": 1,
      "allocation_id": "025022c8-1a7f-a793-ee7e-7f6ca3746a11",
      "tool": "read_skill",
      "recorded_at": "2026-11-26 16:17:11.570890",
      "outcome": "returned",
      "reason": null,
      "returned_skills": [
        {
          "id": "chess-rules",
          "revision": 2
        }
      ],
      "evidence_id": null
    },
    {
      "id": 4,
      "attempt_id": 1,
      "allocation_id": "025022c8-1a7f-a793-ee7e-7f6ca3746a11",
      "tool": "read_skill",
      "recorded_at": "2026-11-26 16:17:11.599135",
      "outcome": "returned",
      "reason": null,
      "returned_skills": [
        {
          "id": "go-testing",
          "revision": 2
        }
      ],
      "evidence_id": null
    },
    {
      "id": 5,
      "attempt_id": 1,
      "allocation_id": "025022c8-1a7f-a793-ee7e-7f6ca3746a11",
      "tool": "submit_work_result",
      "recorded_at": "2026-11-26 16:17:15.599795",
      "outcome": "returned",
      "reason": null,
      "returned_skills": null,
      "evidence_id": 1
    }
  ],
  "image": "127.0.0.1:14661/harness-worker@sha256:40db34e858694fa1f43a50e4b191dcbc08410c71951903227c7d301550e27d0f",
  "allocation_id": "025022c8-1a7f-a793-ee7e-7f6ca3746a11",
  "exit_code": 0,
  "fixture": {
    "cases": [
      {
        "expected_legal": true,
        "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
        "move": "e2e3",
        "reason": "The white rook stays on the e-file and blocks the black rook on e8 from attacking the white king on e1."
      },
      {
        "expected_legal": false,
        "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
        "move": "e2f2",
        "reason": "The white rook leaves the e-file, exposing the white king on e1 to the black rook on e8. Rejection must leave the board unchanged and White to move."
      }
    ],
    "executed": false
  },
  "fresh_review": {
    "cases": [
      {
        "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
        "move": "e2e3",
        "expected_legal": true
      },
      {
        "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
        "move": "e2f2",
        "expected_legal": false
      }
    ],
    "tests_executed": false,
    "needs_correction": false,
    "explanation": "Goal 2 is active. The worker submitted both fixtures as evidence ID 1 and exited with code 0. Review confirms that e2e3 keeps the white rook between the black rook on e8 and the white king on e1, while e2f2 exposes the king to check. Both fixtures match the brief. The worker recorded that no tests ran. The proposed next step is to run both cases against the Go implementation and verify that rejecting e2f2 preserves the board and leaves White to move."
  },
  "controlled_fixture": {
    "cases": [
      {
        "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
        "move": "e2f2",
        "expected_legal": true,
        "reason": "Rooks move horizontally."
      }
    ],
    "executed": false
  },
  "review_of_error": "**Goal 2 \u00b7 Verify pinned rook legality \u00b7 Active (open).** The latest worker result, evidence #2, is incorrect and incomplete.\n\nBoth attempts used the requested four-piece position with White to move: White king on e1 and rook on e2, Black king on a8 and rook on e8.\n\n- **`e2f2` is illegal.** The latest submission correctly notes that rooks can move horizontally, but this move clears the e-file and exposes White\u2019s king on e1 to the black rook on e8. Rejecting it should preserve the board and leave White to move.\n- **`e2e3` is legal.** The rook stays on the e-file and continues to shield White\u2019s king. The latest submission omitted this required case.\n\nThe first attempt submitted both correct expectations as evidence #1 and exited with code 0. The retry submitted evidence #2 while it was still running, with no exit code recorded. Neither attempt executed the fixtures.\n\nI recommend keeping Goal 2 open and restoring the two-case fixture from evidence #1 as the corrected result.\n",
  "goal_status": "active"
}
.

================ 9 passed, 225 deselected in 322.70s (0:05:22) =================
~~~

Exit code 0. Elapsed 347 s.

## Review verification

The review moved workspace access rules into the shared model and the worker executable into the execution contract. The FIFO regression reproduced a blocked scratch write before the nonblocking regular-file check was added. The controlled chess fixture now runs in an idle allocation to prevent a competing submission.

~~~text
ty 0.0.108
ty check packages/harness_api/src packages/harness_mcp/src packages/harness_operator/src --python .venv
All checks passed!
~~~

Exit code 0.

The offline suite ran with PYTHONWARNINGS=error. All 216 tests passed. Nomad passed seven tests with the opt-in heartbeat-loss case skipped. The warm file handoff took 18.61 seconds with one worker Codex session and zero operator sessions. All nine extended live cases passed.
