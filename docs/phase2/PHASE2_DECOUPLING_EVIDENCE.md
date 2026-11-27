# Phase 2 prerequisite evidence — 2026-11-26

The prerequisite is implemented. The owner CLI prepares attempts, binds scratch,
issues credentials to private files, serves worker MCP for the selected workspace,
revokes credentials and retrieves persisted artifacts. The production Docker
launcher and its start command have been removed.

`bash docs/phase2/PHASE2_DECOUPLING_EVIDENCE.sh` exited 0. The script runs
`make check`, `make test`, documentation link and shell syntax checks, and the
README manual handoff sequence through the installed CLI and real HTTP MCP.
The acceptance tests restrict PATH to Git, point Docker and Nomad at unavailable
destinations and use an empty Codex home. The handoff reads the brief and skills,
submits real bytes, retries after scratch cleanup, retrieves the original bytes,
checks attribution and audit, revokes and replaces authority, denies the old
credential and shuts down the server. The goal remains active at its saved
revision with an empty execution outcome. Model tests also verify credential
file exclusivity and rollback after a failed grant.

| Check | Result |
| --- | --- |
| `make check` | Passed |
| `make test` | 233 passed, 14 deselected |
| README command sequence | Passed, including private credential issuance, recovery after scratch removal, revocation and shutdown |
| Local links and evidence shell syntax | Passed |
| `git diff --check` | Passed |

The existing archive move into `docs/phase1/` was verified. Relative links and
evidence-script working directories were updated. The archived Slice 10 recipe
requires its historical baseline and reports that requirement on the current
CLI. Its recorded namespace failure and unsuccessful worker handoffs remain
in the archive. The Slice 9 cluster targets and development backend proof remain
available. [Slice 10 record](../phase1/SLICE10_EVIDENCE.md)

`operator work show` returns persisted data and a null `trace_path`. Existing
container and exit metadata remain readable. The generic worker image and
entrypoint remain available for external execution. Preparation and this manual
handoff acceptance require zero model sessions. The subsequent Nomad experiment
is tracked in Slice 11. [Experiment plan](SLICE11.md)

## Signed-in checks

`make test-live` ran the eight existing operator scenarios and reported seven
passed and one failed in 226.62 seconds. The failure was in
`test_delegated_operator_decides_when_membership_evidence_is_sufficient`.
The first turn read the cited evidence, kept the goal active and made zero
completion calls. The reply said “If your membership is already active, a short
confirmation is all that’s needed to complete subgoal 2.” The existing reply
matcher rejected that wording, so the test stopped before its stronger-evidence
turn. The focused retry passed in 39.47 seconds, including the second turn after
stronger evidence arrived. The live reply matcher remains sensitive to wording.

`make test-live-extended` now invokes the same signed-in suite. The archived city
and checkout Docker handoffs are recorded separately in the Slice 10 history.

The final focused work-model check passed all 28 tests after adding an explicit
assertion that repeated preparation retains exactly one attempt. Final Ruff lint,
format and local-link checks also passed.

## Captured focused signed-in retry

```text
.
1 passed in 39.47s
```

## Captured prerequisite script output

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
108 files already formatted
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests
plugins: anyio-4.16.0
collected 247 items / 14 deselected / 233 selected

packages/harness_api/tests/test_accounts.py .....                        [  2%]
packages/harness_api/tests/test_accounts_http.py .....                   [  4%]
packages/harness_api/tests/test_architecture.py .........                [  8%]
packages/harness_api/tests/test_delegated_completion.py ......           [ 10%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 17%]
....                                                                     [ 18%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 23%]
packages/harness_api/tests/test_goals.py ............................    [ 35%]
packages/harness_api/tests/test_http.py ..........                       [ 39%]
packages/harness_api/tests/test_nomad.py ......                          [ 42%]
packages/harness_api/tests/test_run_activity.py .....                    [ 44%]
packages/harness_api/tests/test_skill_source.py ..                       [ 45%]
packages/harness_api/tests/test_skills.py .....                          [ 47%]
packages/harness_api/tests/test_work.py ............................     [ 59%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 62%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 68%]
packages/harness_mcp/tests/test_worker.py .....                          [ 70%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 72%]
packages/harness_operator/tests/test_ask.py ........                     [ 75%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 76%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 78%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 79%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 87%]
.................                                                        [ 94%]
packages/harness_operator/tests/test_register.py ...                     [ 95%]
packages/harness_operator/tests/test_work_cli.py ..                      [ 96%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 97%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [100%]

===================== 233 passed, 14 deselected in 45.83s ======================
{
  "id": "manual-1",
  "work_item_id": 1,
  "created_at": "2026-11-26 20:51:04.984986",
  "scratch_path": null,
  "scratch_cleaned_at": null,
  "image_digest": null,
  "launched_at": null,
  "exit_code": null,
  "exited_at": null,
  "artifact_id": null,
  "grant_id": null,
  "container_id": null
}
{
  "id": "manual-1",
  "work_item_id": 1,
  "created_at": "2026-11-26 20:51:04.984986",
  "scratch_path": null,
  "scratch_cleaned_at": null,
  "image_digest": null,
  "launched_at": null,
  "exit_code": null,
  "exited_at": null,
  "artifact_id": null,
  "grant_id": null,
  "container_id": null
}
{
  "attempt": {
    "id": "manual-1",
    "work_item_id": 1,
    "created_at": "2026-11-26 20:51:04.984986",
    "scratch_path": null,
    "scratch_cleaned_at": null,
    "image_digest": null,
    "launched_at": null,
    "exit_code": null,
    "exited_at": null,
    "artifact_id": null,
    "grant_id": null,
    "container_id": null
  },
  "work_item": {
    "id": 1,
    "owner_user_id": 1,
    "goal_id": 1,
    "goal_revision": 1,
    "operator_id": 1,
    "brief": "Write a real result.txt.",
    "source_path": null,
    "base_sha": null,
    "created_at": "2026-11-26 20:51:04.470684",
    "skills": [
      {
        "id": "worker-handoff",
        "revision": 1
      }
    ]
  },
  "calls": [],
  "artifact": null,
  "trace_path": null
}
{
  "id": "manual-1",
  "work_item_id": 1,
  "created_at": "2026-11-26 20:51:04.984986",
  "scratch_path": "/tmp/tmp.WTrz3Q1sVc/scratch",
  "scratch_cleaned_at": null,
  "image_digest": null,
  "launched_at": null,
  "exit_code": null,
  "exited_at": null,
  "artifact_id": null,
  "grant_id": null,
  "container_id": null
}
{
  "id": 1,
  "attempt_id": "manual-1",
  "granted_at": "2026-11-26 20:51:06.944707",
  "revoked_at": null
}
{'attempt_id': 'manual-1', 'work_item': {'id': 1, 'owner_user_id': 1, 'goal_id': 1, 'goal_revision': 1, 'operator_id': 1, 'brief': 'Write a real result.txt.', 'skills': [{'id': 'worker-handoff', 'revision': 1}], 'source_path': None, 'base_sha': None, 'created_at': '2026-11-26 20:51:04.470684'}, 'goal': {'id': 1, 'status': 'active', 'title': 'Prepare a real file', 'revision': 1, 'operator': None, 'desired_outcome': None, 'duration': None, 'duration_days': None, 'assessment_type': None, 'success_criteria': None, 'measurement_plan': None, 'target_distinct_dates': None, 'window_start': None, 'parent_goal_id': None, 'completion': None}}
{'id': 1, 'attempt_id': 'manual-1', 'work_item_id': 1, 'goal_id': 1, 'goal_revision': 1, 'operator_id': 1, 'grant_id': 1, 'relative_path': 'result.txt', 'sha256': '16fa73046d06c33f4c8c446c998eee70f3c62e0316fb65bf966a689f778933d8', 'size_bytes': 13, 'base_sha': None, 'created_at': '2026-11-26 20:51:07.616764'}
{
  "id": 1,
  "attempt_id": "manual-1",
  "work_item_id": 1,
  "goal_id": 1,
  "goal_revision": 1,
  "operator_id": 1,
  "grant_id": 1,
  "relative_path": "result.txt",
  "sha256": "16fa73046d06c33f4c8c446c998eee70f3c62e0316fb65bf966a689f778933d8",
  "size_bytes": 13,
  "base_sha": null,
  "created_at": "2026-11-26 20:51:07.616764"
}
A real file.
{
  "attempt": {
    "id": "manual-1",
    "work_item_id": 1,
    "created_at": "2026-11-26 20:51:04.984986",
    "scratch_path": "/tmp/tmp.WTrz3Q1sVc/scratch",
    "scratch_cleaned_at": null,
    "image_digest": null,
    "launched_at": null,
    "exit_code": null,
    "exited_at": null,
    "artifact_id": 1,
    "grant_id": 1,
    "container_id": null
  },
  "work_item": {
    "id": 1,
    "owner_user_id": 1,
    "goal_id": 1,
    "goal_revision": 1,
    "operator_id": 1,
    "brief": "Write a real result.txt.",
    "source_path": null,
    "base_sha": null,
    "created_at": "2026-11-26 20:51:04.470684",
    "skills": [
      {
        "id": "worker-handoff",
        "revision": 1
      }
    ]
  },
  "calls": [
    {
      "id": 1,
      "attempt_id": "manual-1",
      "grant_id": 1,
      "tool": "get_work_brief",
      "started_at": "2026-11-26 20:51:07.563664",
      "finished_at": "2026-11-26 20:51:07.564959",
      "outcome": "returned",
      "arguments": {},
      "artifact_id": null,
      "error": null
    },
    {
      "id": 2,
      "attempt_id": "manual-1",
      "grant_id": 1,
      "tool": "tools/list",
      "started_at": "2026-11-26 20:51:07.589641",
      "finished_at": "2026-11-26 20:51:07.590386",
      "outcome": "returned",
      "arguments": {},
      "artifact_id": null,
      "error": null
    },
    {
      "id": 3,
      "attempt_id": "manual-1",
      "grant_id": 1,
      "tool": "submit_work_result",
      "started_at": "2026-11-26 20:51:07.616154",
      "finished_at": "2026-11-26 20:51:07.617125",
      "outcome": "returned",
      "arguments": {
        "relative_path": "result.txt"
      },
      "artifact_id": 1,
      "error": null
    }
  ],
  "artifact": {
    "id": 1,
    "attempt_id": "manual-1",
    "work_item_id": 1,
    "goal_id": 1,
    "goal_revision": 1,
    "operator_id": 1,
    "grant_id": 1,
    "relative_path": "result.txt",
    "sha256": "16fa73046d06c33f4c8c446c998eee70f3c62e0316fb65bf966a689f778933d8",
    "size_bytes": 13,
    "base_sha": null,
    "created_at": "2026-11-26 20:51:07.616764"
  },
  "trace_path": null
}
{
  "id": 1,
  "attempt_id": "manual-1",
  "granted_at": "2026-11-26 20:51:06.944707",
  "revoked_at": "2026-11-26 20:51:09.306586"
}
Local documentation links and evidence shell syntax passed.
README manual handoff, recovery, revocation and server shutdown passed.
```
