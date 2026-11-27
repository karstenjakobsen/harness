# Slice 12 evidence — 2026-11-27

## Engineering review follow-up — 2026-11-27

The review found six issues and fixed them with seven regression cases that
failed before the changes. The original run below had left the goal's domain
`duration` unset. Its file-mode observations remain historical evidence; the
current run explicitly creates and verifies `duration: standing` through the
existing owner CLI.

- Seed the standing goal with `--duration standing` and recheck the field before
  service deployment and after observation.
- Remove partial delivery and data directories if checkpoint creation fails.
  Reuse the same staging-removal helper during normal cleanup.
- Reject a repeated checkpoint that requests another image.
- Send the exact job bytes that passed digest validation, even if the job file
  changes while volumes are being registered.
- Convert absent Docker mount data and empty digest output into controlled
  errors that enter the existing cleanup path.
- Start the drift clock after the initial observation receipt write and directly
  before changing the target mode. Include mode-reset errors in saved failures.

Production `packages/` remain unchanged. The experiment uses the owner CLI for
Harness state and keeps scheduler, Docker, file observation and receipt handling
under `dev/phase2/`. Existing public API names, attribution and error contracts
remain in place. The repository has no configured type checker; lint, formatting,
pytest and live integration checks were used.

### Fresh live acceptance

The updated implementation passed in a fresh workspace with one actual Codex
worker session, zero AI operator sessions, worker exit 0 and zero restarts.
After worker exit, grant revocation and scratch removal, the service consumed
the exact submitted script through its read-only delivery mount. The goal stayed
active at revision 1 with `duration: standing`.

| Observation | Actual value |
| --- | --- |
| Worker receipt | `.harness/phase2/slice12-w3CAZJ/phase2/receipt.json` |
| Service receipt | `.harness/phase2/slice12-w3CAZJ/phase2/service/receipt.json` |
| Attempt | `phase2-37a339b3c71d4a1d939e75e152d6e9b0` |
| Worker job / allocation | `phase2-d260526c73044e0aa16dd942b916fa35` / `2743e88d-9aa8-720f-3c3c-4024b80208a6` |
| Service job / allocation | `phase2-service-efdc3e9a374a4dc58a64297ef77e351c` / `b3a4cd9f-654f-1474-ca55-96b22b9fffdf` |
| Artifact SHA-256 | `482ff57dbf35f007361d9666ec7dc2295effcea2c3ca807c51abec8e7521315e` |
| Startup first sample | `0600` at 0.013575 seconds after observer start |
| Deliberate drift correction | 0.115610 seconds, 2 samples |
| Stopped service window | 4.070451 seconds, 38 samples, all `0644` |

Both file contents and the sibling's `0644` mode were preserved throughout.
Fresh CLI retrieval after cleanup matched the artifact identity and digest.
Fresh Nomad reads confirmed both jobs and their host-volume registrations were
removed. The evidence script exited 0 after lint, formatting and all 274 offline
tests passed, including 26 Slice 12 cases. The signed-in AI operator suite was
outside these changes. Repeat the current evidence checks with

```sh
SLICE12_RECEIPT="$PWD/.harness/phase2/slice12-w3CAZJ/phase2/receipt.json" \
  bash docs/phase2/SLICE12_EVIDENCE.sh
```

### Captured review verification output

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
119 files already formatted
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests, dev/phase2
plugins: anyio-4.16.0
collected 288 items / 14 deselected / 274 selected

packages/harness_api/tests/test_accounts.py .....                        [  1%]
packages/harness_api/tests/test_accounts_http.py .....                   [  3%]
packages/harness_api/tests/test_architecture.py .........                [  6%]
packages/harness_api/tests/test_delegated_completion.py ......           [  9%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 14%]
....                                                                     [ 16%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 20%]
packages/harness_api/tests/test_goals.py ............................    [ 30%]
packages/harness_api/tests/test_http.py ..........                       [ 33%]
packages/harness_api/tests/test_nomad.py ......                          [ 36%]
packages/harness_api/tests/test_run_activity.py .....                    [ 37%]
packages/harness_api/tests/test_skill_source.py ..                       [ 38%]
packages/harness_api/tests/test_skills.py .....                          [ 40%]
packages/harness_api/tests/test_work.py ................................ [ 52%]
                                                                         [ 52%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 54%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 59%]
packages/harness_mcp/tests/test_worker.py .....                          [ 61%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 62%]
packages/harness_operator/tests/test_ask.py ........                     [ 65%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 66%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 67%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 69%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 75%]
.................                                                        [ 81%]
packages/harness_operator/tests/test_register.py ...                     [ 82%]
packages/harness_operator/tests/test_work_cli.py ....                    [ 84%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 85%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [ 87%]
dev/phase2/test_experiment.py .........                                  [ 90%]
dev/phase2/test_standing.py ..........................                   [100%]

================ 274 passed, 14 deselected in 173.24s (0:02:53) ================
Required live Slice 12 acceptance verified from retained traces, observations and fresh owner CLI reads
{
  "worker_receipt": "/home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/slice12-w3CAZJ/phase2/receipt.json",
  "service_receipt": "/home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/slice12-w3CAZJ/phase2/service/receipt.json",
  "worker_job_id": "phase2-d260526c73044e0aa16dd942b916fa35",
  "service_job_id": "phase2-service-efdc3e9a374a4dc58a64297ef77e351c",
  "worker_allocation_id": "2743e88d-9aa8-720f-3c3c-4024b80208a6",
  "service_allocation_id": "b3a4cd9f-654f-1474-ca55-96b22b9fffdf",
  "goal_id": 2,
  "goal_revision": 1,
  "goal_duration": "standing",
  "attempt_id": "phase2-37a339b3c71d4a1d939e75e152d6e9b0",
  "artifact": {
    "id": 1,
    "attempt_id": "phase2-37a339b3c71d4a1d939e75e152d6e9b0",
    "work_item_id": 1,
    "goal_id": 2,
    "goal_revision": 1,
    "operator_id": 1,
    "grant_id": 1,
    "relative_path": "maintain-mode.sh",
    "sha256": "482ff57dbf35f007361d9666ec7dc2295effcea2c3ca807c51abec8e7521315e",
    "size_bytes": 493,
    "base_sha": null,
    "created_at": "2026-11-27 07:05:00.320005"
  },
  "worker_image": "sha256:bca5b3575cd7b4ef85d9e08f5a86de8c0b35dee5e637ddf3d7e350e3ad88db81",
  "service_image": "docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec",
  "worker_sessions": 1,
  "ai_operator_sessions": 0,
  "observations": {
    "startup": {
      "deadline_seconds": 10,
      "passed": true,
      "elapsed_seconds": 0.013575166987720877,
      "sample_count": 1
    },
    "drift": {
      "deadline_seconds": 3,
      "passed": true,
      "elapsed_seconds": 0.11561022599926218,
      "sample_count": 2
    },
    "shutdown": {
      "deadline_seconds": 4,
      "passed": true,
      "elapsed_seconds": 4.070450577011798,
      "sample_count": 38
    }
  },
  "cleanup": {
    "job_removed": true,
    "volumes_removed": true,
    "directories_removed": true
  }
}
Retrieved exact script after both jobs and their directories were removed
#!/bin/sh

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    printf 'Usage: %s TARGET\n' "$0" >&2
    exit 2
fi

case $1 in
    /*) target=$1 ;;
    *) target=./$1 ;;
esac

trap 'exit 0' HUP INT TERM

while :; do
    if [ ! -f "$target" ] || [ -L "$target" ]; then
        printf 'Expected a regular file: %s\n' "$target" >&2
        exit 1
    fi

    mode=$(stat -c '%a' "$target") || exit 1
    if [ "$mode" != 600 ]; then
        chmod 0600 "$target" || exit 1
    fi

    sleep 1 || exit 1
done
```

## Original run before engineering review

Required live acceptance passed with one real Codex worker session and zero AI
operator sessions. The worker read its brief and skill through MCP, wrote and
submitted `maintain-mode.sh`, and exited 0. Its credential was revoked, MCP was
stopped and scratch was removed before the owner CLI retrieved the script.

The distinct service checkpoint saved the artifact inspection, exported metadata,
read-only script and exact Jinja-rendered service job. An explicit subsequent
command submitted the service. Docker inspection confirmed `/delivery` read-only
and `/data` writable. `sha256sum` inside that allocation matched the Harness
artifact digest. The service used a pinned BusyBox shell image without Codex or
worker MCP credentials. The producing worker and consuming service have separate
job and allocation IDs.

| Observation | Actual value |
| --- | --- |
| Worker receipt | `.harness/phase2/slice12-ijXp9E/phase2/receipt.json` |
| Service receipt | `.harness/phase2/slice12-ijXp9E/phase2/service/receipt.json` |
| Attempt | `phase2-336274e7d08449cdaaaba4b81ef71c04` |
| Goal / revision / work item / artifact | 2 / 1 / 1 / 1 |
| Worker job | `phase2-69ddaf3ea47148858c9af9b879fb488c` |
| Worker allocation | `1a3d0145-abcc-88e3-cbda-460bf804c04d` |
| Service job | `phase2-service-f5f50d79bd4f420ba37aa3dea7105d5f` |
| Service allocation | `05b1e9b1-6763-ba12-9736-ff0b37d6ee4a` |
| Worker image | `sha256:bca5b3575cd7b4ef85d9e08f5a86de8c0b35dee5e637ddf3d7e350e3ad88db81` |
| Service image | `docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec` |
| Script SHA-256 | `2285a11c9eed72d3bdb2774e62be1fe9d1cd36197975054bdf80819d8fa3ba76` |
| Script size | 498 bytes |
| Worker exit / restarts / sessions / AI operator sessions | 0 / 0 / 1 / 0 |

## Three independent observations

The target and sibling were recorded at `0644` with known contents before
submission. The brief specifies one-second polling and a three-second correction
deadline. External samples use `stat`, content digests and a monotonic clock.

| Stage | Observed result | Elapsed time | Samples |
| --- | --- | --- | --- |
| Startup | First external sample observed `0600` before deliberate drift | 0.012551 seconds | 1 |
| Drift | Observer reset `0644`, then observed a second correction to `0600` | 1.105458 seconds | 11 |
| Shutdown | After confirmed Nomad stop, every reset-target sample stayed `0644` | 4.044037 seconds | 37 |

Startup time above is measured from the observer's first check, after placement
and script inspection; it is not container startup latency. The drift clock
begins before the observer's deliberate `chmod`. All samples preserved both
files' content digests and the sibling's `0644` mode. Nomad inspections required
the original allocation, zero task restarts and no running replacement. During
the shutdown window the job was stopped and that allocation was terminal.

The goal remained active at revision 1. A further owner CLI
export after both jobs and disposable directories were removed matched the
original artifact identity and digest. Fresh Nomad reads confirmed both job IDs
absent and no host-volume registrations belonging to either job remained. Saved
worker trace, MCP audit, script, service mount inspection and timestamped samples
are retained under the receipt paths above.

## Verification

The live command exited 0

```sh
HARNESS_PHASE2_MCP_URL=http://host.docker.internal:8001/mcp make test-phase2-standing
```

The evidence script then exited 0 using that completed live session and fresh
owner CLI reads, with `make check` passing and `make test` reporting 268 passed
and 14 deselected. This original capture used the command below. Current
verification requires the standing-goal receipt in the follow-up above.

```sh
SLICE12_RECEIPT="$PWD/.harness/phase2/slice12-ijXp9E/phase2/receipt.json" \
  bash docs/phase2/SLICE12_EVIDENCE.sh
```

The 20 Slice 12 offline cases use real CLI-seeded SQLite workspaces, real files
and shell processes, with small scheduler and Docker protocol fixtures where
needed. They cover changed artifact identities and digests, changed checkpoint
files, read-only mounts, service-visible digests, separate job identities,
sibling and content damage, scoped cleanup and replacement detection. The
startup-only `chmod` regression passes startup and fails deliberate drift. A
complete local observation flow covers startup, drift, shutdown and cleanup.
Receipt recovery discovers owned volumes even when their registration IDs were
not saved. A rejected repeat submission preserves the completed receipt.

No files under `packages/` changed. The signed-in AI operator suite was outside
this slice; the required live worker acceptance is reported separately above.
Service inspection currently requires Docker CLI access to the same single
Nomad client's Docker daemon. Metrics, notifications and a Harness deployment
model remain deferred.

## Captured evidence script output

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
118 files already formatted
uv run --locked --all-packages pytest -m "not live and not nomad"
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/karsten/projects/github/karstenjakobsen/harness
configfile: pyproject.toml
testpaths: packages/harness_api/tests, packages/harness_mcp/tests, packages/harness_operator/tests, dev/phase2
plugins: anyio-4.16.0
collected 282 items / 14 deselected / 268 selected

packages/harness_api/tests/test_accounts.py .....                        [  1%]
packages/harness_api/tests/test_accounts_http.py .....                   [  3%]
packages/harness_api/tests/test_architecture.py .........                [  7%]
packages/harness_api/tests/test_delegated_completion.py ......           [  9%]
packages/harness_api/tests/test_delegated_definitions.py ............... [ 14%]
....                                                                     [ 16%]
packages/harness_api/tests/test_goal_progress.py ...........             [ 20%]
packages/harness_api/tests/test_goals.py ............................    [ 30%]
packages/harness_api/tests/test_http.py ..........                       [ 34%]
packages/harness_api/tests/test_nomad.py ......                          [ 36%]
packages/harness_api/tests/test_run_activity.py .....                    [ 38%]
packages/harness_api/tests/test_skill_source.py ..                       [ 39%]
packages/harness_api/tests/test_skills.py .....                          [ 41%]
packages/harness_api/tests/test_work.py ................................ [ 53%]
                                                                         [ 53%]
packages/harness_api/tests/test_workspace_ids.py ......                  [ 55%]
packages/harness_mcp/tests/test_list_goals.py ..............             [ 60%]
packages/harness_mcp/tests/test_worker.py .....                          [ 62%]
packages/harness_operator/tests/test_accounts_cli.py ....                [ 64%]
packages/harness_operator/tests/test_ask.py ........                     [ 67%]
packages/harness_operator/tests/test_checkout_fixture.py ..              [ 67%]
packages/harness_operator/tests/test_create_goal.py ....                 [ 69%]
packages/harness_operator/tests/test_goal_cli.py ....                    [ 70%]
packages/harness_operator/tests/test_goal_plan_live.py ................. [ 77%]
.................                                                        [ 83%]
packages/harness_operator/tests/test_register.py ...                     [ 84%]
packages/harness_operator/tests/test_work_cli.py ....                    [ 86%]
packages/harness_operator/tests/test_work_handoff.py ..                  [ 86%]
packages/harness_operator/tests/test_worker_entrypoint.py ......         [ 89%]
dev/phase2/test_experiment.py .........                                  [ 92%]
dev/phase2/test_standing.py ....................                         [100%]

================ 268 passed, 14 deselected in 154.57s (0:02:34) ================
Required live Slice 12 acceptance verified from retained traces, observations and fresh owner CLI reads
{
  "worker_receipt": "/home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/slice12-ijXp9E/phase2/receipt.json",
  "service_receipt": "/home/karsten/projects/github/karstenjakobsen/harness/.harness/phase2/slice12-ijXp9E/phase2/service/receipt.json",
  "worker_job_id": "phase2-69ddaf3ea47148858c9af9b879fb488c",
  "service_job_id": "phase2-service-f5f50d79bd4f420ba37aa3dea7105d5f",
  "worker_allocation_id": "1a3d0145-abcc-88e3-cbda-460bf804c04d",
  "service_allocation_id": "05b1e9b1-6763-ba12-9736-ff0b37d6ee4a",
  "goal_id": 2,
  "goal_revision": 1,
  "attempt_id": "phase2-336274e7d08449cdaaaba4b81ef71c04",
  "artifact": {
    "id": 1,
    "attempt_id": "phase2-336274e7d08449cdaaaba4b81ef71c04",
    "work_item_id": 1,
    "goal_id": 2,
    "goal_revision": 1,
    "operator_id": 1,
    "grant_id": 1,
    "relative_path": "maintain-mode.sh",
    "sha256": "2285a11c9eed72d3bdb2774e62be1fe9d1cd36197975054bdf80819d8fa3ba76",
    "size_bytes": 498,
    "base_sha": null,
    "created_at": "2026-11-27 06:38:42.527354"
  },
  "worker_image": "sha256:bca5b3575cd7b4ef85d9e08f5a86de8c0b35dee5e637ddf3d7e350e3ad88db81",
  "service_image": "docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec",
  "worker_sessions": 1,
  "ai_operator_sessions": 0,
  "observations": {
    "startup": {
      "deadline_seconds": 10,
      "passed": true,
      "elapsed_seconds": 0.012551252031698823,
      "sample_count": 1
    },
    "drift": {
      "deadline_seconds": 3,
      "passed": true,
      "elapsed_seconds": 1.1054576309979893,
      "sample_count": 11
    },
    "shutdown": {
      "deadline_seconds": 4,
      "passed": true,
      "elapsed_seconds": 4.04403715999797,
      "sample_count": 37
    }
  },
  "cleanup": {
    "job_removed": true,
    "volumes_removed": true,
    "directories_removed": true
  }
}
Retrieved exact script after both jobs and their directories were removed
#!/bin/sh

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    printf 'Usage: %s target-file\n' "$0" >&2
    exit 2
fi

case $1 in
    /*) target=$1 ;;
    *) target=./$1 ;;
esac

trap 'exit 0' HUP INT TERM

while :; do
    if [ ! -f "$target" ] || [ -L "$target" ]; then
        printf 'Expected a regular file: %s\n' "$target" >&2
        exit 1
    fi

    mode=$(stat -c '%a' "$target") || exit 1
    if [ "$mode" != 600 ]; then
        chmod 0600 "$target" || exit 1
    fi

    sleep 1 || exit 1
done
```
