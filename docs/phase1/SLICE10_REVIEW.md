# Slice 10 implementation review

Reviewed on 2026-11-26 against baseline `157346c`. Fixes are in `470ce80` on
`slice-10-docker-worker`. This review covers the new domain model, schema, CLI,
worker MCP, Docker launcher, entrypoint and acceptance tests.

## Findings fixed

| Finding | Fix and regression coverage |
| --- | --- |
| Different databases in one directory shared attempt runtime files, risking deletion of another attempt's scratch. | Key runtime state by the canonical database path. Separate databases retain independent scratch; database and directory symlink aliases recover the same attempt. |
| Authorization failures inherited `OSError`, so the database connection wrapper mislabeled them as storage failures. | Make `WorkAuthorizationError` a domain `RuntimeError`. Six cases cover stale revisions and unregistered operators during attempt creation, grants and launch recording, with no writes. |
| Launch replay recopied the original login, overwriting private session state or failing if the source login disappeared. | Preserve the private copy and require login preparation only before container creation/start. Recovery of running/exited containers requires no original login. |
| Git failures and Docker timeouts/log failures could escape as raw subprocess exceptions. | Bound Git commands and map failures at the infrastructure boundary to launcher errors. Keep the timeout subtype so an expired worker deadline still stops the container, records exit and cleans scratch. |
| Artifact export created an empty owner file before a failed database read. | Read saved bytes before exclusively creating the output. CLI tests cover failed reads, existing output preservation, retrieval after cleanup and current-workspace selection. |

The new bug regressions were run against the failing behavior before the fixes.

## Review checklist

| Area | Assessment |
| --- | --- |
| Boundaries and dependencies | Models own authority, validation, transactions, file validation and persisted artifacts. CLI and MCP use the public API; Docker, Git, login mounts and runtime paths remain in the launcher. Architecture import checks pass. |
| Naming and API shape | Kept existing work terminology and public response fields. Worker MCP now uses public `WorkBrief`, `SkillRevision` and `WorkArtifact` result types, with the existing `skills` wrapper shape. |
| Low-risk cleanup | Removed an unused authentication alias and discarded audit-message argument. Centralized repeated Git execution and Docker timeout handling without introducing a generic execution framework. |
| Contracts and failures | Authoritative same-path retries, conflicting-path rejection, live grant/revision checks and separate process/artifact outcomes remain intact. Recovery and failure errors now follow the documented contracts. |
| Existing conventions | Retained `*API` public models, typed dictionaries, domain-specific errors, thin Click/MCP adapters, SQLite transactions and real-file/database tests with a narrow Docker seam. |
| Verification and limits | Lint, formatting and all offline tests pass. No Python type-checker target/configuration is present, so no static type-check result is claimed. Live Docker handoff acceptance remains incomplete due to the previously observed host namespace restriction. |

## Verification

Command: `make check && make test && git diff --check` (exit 0).

```text
uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
104 files already formatted
uv run --locked --all-packages pytest -m "not live and not nomad"
collected 271 items / 16 deselected / 255 selected
255 passed, 16 deselected in 45.64s
```

The suite includes 26 WorkAPI cases, five worker MCP protocol cases, 32 launcher
cases, two CLI handoff cases and the two checkout acceptance-oracle cases. No
warnings were reported. No earlier acceptance containers remained running.

The runtime state directory layout changed. Use a fresh POC workspace for current
acceptance; pre-review attempt directories cannot be resumed by the revised
launcher. Saved artifact bytes remain in their original database.

No Docker security settings were relaxed. Signed-in tests were not repeated in
this review because the known Bubblewrap namespace restriction is unchanged.
The previous eight passing signed-in scenarios and two failing Docker handoffs
are historical results, not acceptance of these review changes.
[Captured live evidence and proposed host configuration](SLICE10_EVIDENCE.md).
