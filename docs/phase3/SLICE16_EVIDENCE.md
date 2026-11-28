# Slice 16 evidence — Delegate a work item against a specific goal revision

Initial acceptance at `5c49b06`, verified on 2026-11-28. The accepted handoff-fix results are appended below. [Checklist](SLICE16_TODO.md) · [Evidence script](SLICE16_EVIDENCE.sh)

`WorkAPI.delegate_work` saves the item, exact grant, retry identity and
committing-call link atomically. The focused acceptance tests cover one result
per call (including reuse with a different key), concurrent identical requests,
rollback after insertion, lost replies, grant withdrawal and replacement,
operator unregistration, target and ownership scope, stale revisions and
requested repository inputs. Existing owner-work-item and adapter coverage is
reused by the full suite.

The example deliberately leaves reply recording unfinished, reopens the database
and follows the item to its committing call. It creates zero attempts and leaves
the goal active at revision 1. Repository inputs are absolute path/SHA requests;
no repository access or launch authority is granted by delegation.

Production changes and new tests are confined to `packages/harness_api`. Existing
CLI and MCP callers retain their contracts. The full suite includes the existing
MCP history regression; delegation run metadata has a separate Python type so
legacy run responses retain their shape.

The schema is unversioned and incompatible with earlier workspaces. Start in a
fresh workspace; populated databases are reopened without migration. Live checks
were not required for this model-only slice: no signed-in AI session, worker
launch or scheduler acceptance was added.

Commands used `UV_CACHE_DIR=/tmp/harness-uv-cache` because the sandbox cannot write
to the default uv cache. The sandboxed full suite stalled in the existing HTTP
`TestClient` async portal. The completed full-suite run below ran outside the
sandbox; the focused evidence script and lint checks ran inside it.

## Review follow-up

The review found one inconsistent public query: `get_run_write_action` returned
`None` for a valid delegation-bound run. A regression test failed for that case
before the fix. The query now reports `delegate_work` and returns `None` when
the exact grant is withdrawn, replaced after withdrawal, or invalidated by
unregistration, or when the run finishes. Existing MCP tools remain unchanged.

The shared grant type and active-authority lookup now live in
`models/work_delegation.py`, outside activity-history serialization. Repository
input validation is shared with owner work-item creation, while delegated input
still requires an absolute path. New delegations no longer validate the same
target twice; replays still validate the current target before returning a saved
item. Lifecycle tests now assert the specific domain error for each denial.

All three production packages pass supplemental `ty 0.0.112` checks. The checker
was installed under `/tmp`; no project dependency or type-check configuration
was added. The final test and focused evidence runs below treat warnings as
errors. Import-boundary tests remain part of the full suite.

## Focused acceptance and delegate-and-reopen example

Command: `UV_CACHE_DIR=/tmp/harness-uv-cache PYTEST_ADDOPTS="-W error" bash docs/phase3/SLICE16_EVIDENCE.sh`
Exit status: 0.

```text
.............................................                            [100%]
45 passed in 2.17s
{
  "work_item_id": 1,
  "goal_id": 1,
  "goal_revision": 1,
  "operator_id": 1,
  "delegation_grant_id": 1,
  "committing_call": {
    "run_id": 1,
    "sequence": 1
  },
  "call_outcome": "unfinished",
  "reopened": true,
  "attempt_count": 0,
  "goal_status": "active"
}
Live checks: not required; Slice 16 adds Python model operations only.
```

## Lint and formatting

Command: `UV_CACHE_DIR=/tmp/harness-uv-cache make check`
Exit status: 0.

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
133 files already formatted
```

## Supplemental type check

Command (using the cached `ty 0.0.112` tool):

```sh
UV_CACHE_DIR=/tmp/harness-uv-cache UV_TOOL_DIR=/tmp/harness-uv-tools \
  uvx --offline ty check packages/harness_api/src packages/harness_mcp/src \
  packages/harness_operator/src --python .venv/bin/python --output-format concise
```

Exit status: 0.

```text
All checks passed!
```

## Full offline suite

Command: `UV_CACHE_DIR=/tmp/harness-uv-cache PYTEST_ADDOPTS="-W error" make test`
Exit status: 0.

```text
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests, dev/phase2
plugins: anyio-4.16.0
collected 353 items / 14 deselected / 339 selected

packages/harness_api/tests/test_accounts.py .....                        [  1%]
packages/harness_api/tests/test_accounts_http.py .....                   [  2%]
packages/harness_api/tests/test_architecture.py .........                [  5%]
packages/harness_api/tests/test_delegated_completion.py ......           [  7%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 11%]
....                                                                     [ 12%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 16%]
packages/harness_api/tests/test_goals.py ............................    [ 24%]
packages/harness_api/tests/test_http.py ..........                       [ 27%]
packages/harness_api/tests/test_nomad.py ......                          [ 29%]
packages/harness_api/tests/test_run_activity.py .....                    [ 30%]
packages/harness_api/tests/test_skill_source.py ..                       [ 31%]
packages/harness_api/tests/test_skills.py .....                          [ 32%]
packages/harness_api/tests/test_work.py ................................ [ 42%]
                                                                         [ 42%]
packages/harness_api/tests/test_work_delegation.py ..................... [ 48%]
........................                                                 [ 55%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 57%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 61%]
packages/harness_mcp/tests/test_worker.py .....                          [ 62%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 64%]
packages/harness_operator/tests/test_ask.py ........                     [ 66%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 66%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 68%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 69%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 74%]
.................                                                        [ 79%]
packages/harness_operator/tests/test_register.py ...                     [ 80%]
packages/harness_operator/tests/test_work_cli.py ....                    [ 81%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 82%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [ 83%]
dev/phase2/test_experiment.py .................                          [ 88%]
dev/phase2/test_standing.py ....................................         [ 99%]
dev/phase2/test_watch.py ..                                              [100%]

================ 339 passed, 14 deselected in 168.46s (0:02:48) ================
```


## Accepted handoff fixes — 2026-11-28

Both reported gaps were reproduced by failing regressions before implementation:
a delegated worker received an empty skill list, and HTTP dropped the delegation
grant ID returned by Python. Both are now fixed, without a schema change or a
required skill-selection argument on delegation.

Delegated workers use the workspace owner's current discoverable catalog,
including on items saved before import. Workers choose which revisions to read;
brief hints are optional. Catalog removal or replacement changes permission on
the next call, while previous successful reads retain their exact ID, revision,
attempt and credential grant in worker audit. Owner-created work items retain
their explicit revision restrictions. Tests cover catalog updates, foreign
skills, withdrawn credentials and immutable work-item data.

All run responses share `OperatorRun.delegation_grant_id`, nullable on other run
types. `WorkDelegationRun` remains a compatibility name. HTTP and MCP parity
assertions preserve the exact grant and committing work item, including an
unfinished committing call and attribution after withdrawal.

The first signed-in run reported seven passes and one existing gym-answer
matcher failure; a focused retry reproduced it. In both runs, progress retrieval,
zero completion attempts, and the active goal were verified before the matcher
rejected valid conditional confirmation wording. Positive regressions for both
observed phrasings failed before the matcher correction. The corrected test
helper passes 22 positive/negative cases, including rejection of day-pass
confirmation substituted for membership confirmation. Production operator
behavior was not changed. The final signed-in suite below passes all eight
scenarios, including both evidence turns and saved-state inspection.

### Focused model, HTTP and MCP evidence

Command: `UV_CACHE_DIR=/tmp/harness-uv-cache PYTEST_ADDOPTS="-W error" bash docs/phase3/SLICE16_EVIDENCE.sh`
Exit status: 0. Run outside the sandbox for HTTP `TestClient` support.

```text
.......................................................                  [100%]
55 passed in 3.97s
{
  "work_item_id": 1,
  "goal_id": 1,
  "goal_revision": 1,
  "operator_id": 1,
  "delegation_grant_id": 1,
  "committing_call": {
    "run_id": 1,
    "sequence": 1
  },
  "call_outcome": "unfinished",
  "reopened": true,
  "attempt_count": 0,
  "goal_status": "active"
}
Signed-in operator checks run separately with make test-live.
```

### Lint, formatting and types

Command: `UV_CACHE_DIR=/tmp/harness-uv-cache make check`
Exit status: 0.

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
133 files already formatted
```

Supplemental `ty 0.0.112` command (no project dependency change):

```sh
UV_CACHE_DIR=/tmp/harness-uv-cache UV_TOOL_DIR=/tmp/harness-uv-tools \
  uvx --offline ty check packages/harness_api/src packages/harness_mcp/src \
  packages/harness_operator/src --python .venv/bin/python --output-format concise
```

Exit status: 0.

```text
All checks passed!
```

### Final offline suite

Command: `UV_CACHE_DIR=/tmp/harness-uv-cache PYTEST_ADDOPTS="-W error" make test`
Exit status: 0. Run outside the sandbox for HTTP `TestClient` support.

```text
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests, dev/phase2
plugins: anyio-4.16.0
collected 361 items / 14 deselected / 347 selected

packages/harness_api/tests/test_accounts.py .....                        [  1%]
packages/harness_api/tests/test_accounts_http.py .....                   [  2%]
packages/harness_api/tests/test_architecture.py .........                [  5%]
packages/harness_api/tests/test_delegated_completion.py ......           [  7%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 11%]
....                                                                     [ 12%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 15%]
packages/harness_api/tests/test_goals.py ............................    [ 23%]
packages/harness_api/tests/test_http.py ..........                       [ 26%]
packages/harness_api/tests/test_nomad.py ......                          [ 28%]
packages/harness_api/tests/test_run_activity.py .....                    [ 29%]
packages/harness_api/tests/test_skill_source.py ..                       [ 30%]
packages/harness_api/tests/test_skills.py .....                          [ 31%]
packages/harness_api/tests/test_work.py ................................ [ 41%]
                                                                         [ 41%]
packages/harness_api/tests/test_work_delegation.py ..................... [ 47%]
...........................                                              [ 55%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 56%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 60%]
packages/harness_mcp/tests/test_worker.py .......                        [ 62%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 63%]
packages/harness_operator/tests/test_ask.py ........                     [ 66%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 66%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 68%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 69%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 74%]
....................                                                     [ 79%]
packages/harness_operator/tests/test_register.py ...                     [ 80%]
packages/harness_operator/tests/test_work_cli.py ....                    [ 81%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 82%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [ 84%]
dev/phase2/test_experiment.py .................                          [ 89%]
dev/phase2/test_standing.py ....................................         [ 99%]
dev/phase2/test_watch.py ..                                              [100%]

================ 347 passed, 14 deselected in 174.68s (0:02:54) ================
```

### Signed-in results

Initial full-suite result before correcting the test-only matcher:

```text
FAILED packages/harness_operator/tests/test_goal_plan_live.py::test_delegated_operator_decides_when_membership_evidence_is_sufficient
=========== 1 failed, 7 passed, 350 deselected in 213.94s (0:03:33) ============
```

The focused retry failed the same matcher before correction:

```text
FAILED packages/harness_operator/tests/test_goal_plan_live.py::test_delegated_operator_decides_when_membership_evidence_is_sufficient
1 failed in 16.98s
```

Final command: `UV_CACHE_DIR=/tmp/harness-uv-cache PYTEST_ADDOPTS="-W error" make test-live`
Exit status: 0. Run outside the sandbox using the existing Codex login.
The final summary is captured below; verbose synthetic goal/HTTP excerpts are
omitted from this report.

```text
collected 361 items / 353 deselected / 8 selected
================ 8 passed, 353 deselected in 236.03s (0:03:56) =================
```
