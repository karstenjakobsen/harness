# Slice 12 — Run a worker-delivered file-mode service

Implement the [Slice 12 plan](SLICE12.md) as a development experiment under
`dev/phase2/`. Reuse the installed CLI, generic worker image and MCP artifact
handoff. Keep `packages/` unchanged. Harness prepares attempts and preserves
artifacts; we render Jinja jobs and submit them directly to Nomad.

The acceptance boundary is one live Codex worker session, zero AI operator
sessions and one submitted shell script that maintains a designated disposable
file at mode `0600` after the worker has exited, its credential is revoked and
its scratch is gone. We inspect the saved delivery before explicitly submitting
a separate service job. The standing goal stays active at its original revision
throughout. Owner CLI commands read Harness records without an AI operator.

## Prepare and build

- [x] Provide a documented command sequence with separate preparation, worker submission, retrieval, service checkpoint, service submission, observation and stop steps. The service checkpoint must be a distinct command that returns without submitting a job.
- [x] Seed an empty workspace through the CLI with a named operator, standing goal, work item and attempt. Save the returned identifiers and goal revision.
- [x] Put the target-file argument, required mode `0600` and agreed shell `/bin/sh` in the worker brief. Ask for polling once per second and require externally observed correction within three seconds. Specify that the script changes only the supplied file's mode and preserves file contents and sibling files.
- [x] Ask the worker for exactly one artifact, a shell script that keeps enforcing the required mode while it runs. Supply the service Nomad template ourselves.
- [x] Render and retain the worker job and prepared-attempt inspection before submission, with no worker running at that checkpoint.
- [x] Manually submit the pinned generic worker image to Nomad. Verify one real Codex session, successful MCP brief reads and script submission, and allocation exit code 0. Preserve the actual trace and audit results.
- [x] Revoke the worker credential, stop worker MCP and remove worker scratch and private runtime files before deploying the delivered script.

## Retrieve and deploy

- [x] Retrieve the saved script through `operator work show` and `operator work artifact` after worker exit and scratch cleanup, using the same explicit workspace. Save both JSON responses. Match the prepared attempt, work item, goal revision and artifact ID, and verify the exported file's SHA-256 against the saved artifact digest. Stop on any mismatch, including a newer artifact from another attempt.
- [x] Stage the verified script in a dedicated delivery directory separate from the writable test data. Keep the script read-only and mount its delivery directory read-only into the service. Retain the original retrieved bytes.
- [x] Create a disposable writable test directory containing the designated regular file and a sibling file, both initially `0644`, with known contents. Record their original bytes and modes. Keep both directories separate from the worker's removed scratch and private runtime.
- [x] Render a second Jinja job with its own job ID using a digest-pinned shell image. Invoke `/bin/sh /delivery/maintain-mode.sh /data/target` with the delivery mount read-only and test-data mount writable. Supply no Codex login, worker credential or MCP dependency.
- [x] Make the distinct service checkpoint command preserve the verified script, its provenance and digest, and the exact rendered job. It must leave no service running, allowing manual inspection and a decision to submit or request a corrected delivery.
- [x] Submit the service job directly to Nomad only through an explicit subsequent command. Recheck the checkpoint's job and script digests before submission and record the allocation and running state independently of the worker job.
- [x] Independently hash the script visible at `/delivery/maintain-mode.sh` inside the running service allocation and require it to match the Harness artifact digest before perturbing the target. Do not edit or replace the delivered script.
- [x] Link the artifact ID and digest, producing attempt, goal revision, worker job and consuming service job in the experiment receipt. Record the one-second polling interval, three-second correction deadline and external sampling cadence separately from observed outcomes.

## Observe and stop

- [x] Startup observation: without changing the target's initial `0644` mode, wait for the external observer to see the service bring it to `0600`. Use a bounded startup wait and record its deadline, samples and elapsed time. Require this observation to succeed before deliberately introducing drift.
- [x] Drift observation: only after observing startup `0600`, deliberately set the target back to `0644` and start a new three-second clock. Observe a second correction to `0600` using independent `stat` checks. Measure actual elapsed time with a monotonic clock and retain sample timestamps and modes.
- [x] After both startup and drift correction, require the target's original contents to be unchanged and the sibling to remain `0644` with its original contents. Fail acceptance if a recursive mode change affects the sibling.
- [x] Stop the service and confirm through Nomad that its allocation is stopped and no replacement is running. Then set the target to `0644` again and sample it for at least four seconds, longer than the same three-second correction deadline. Require every sample to remain `0644`, preserve both files' contents and the sibling's mode, and confirm no service replacement ran during the window. Save actual elapsed time and samples.
- [x] Verify through fresh CLI reads that the standing goal remains active at the saved revision and the submitted script remains retrievable.
- [x] Clean up the experiment's two jobs, volume registrations and disposable directories, including failure and interruption paths. Preserve the receipt, script digest, logs and observations.
- [x] Preserve Slice 11 recovery behavior when reusing its runner. Retrying a failed retrieval or observation must not launch another worker for the same attempt; record ownership needed to recover each job and runtime.

## Verification and evidence

- [x] Add focused tests under `dev/phase2/` for artifact-ID and digest mismatches, read-only exact-byte deployment, a checkpoint that does not submit, independent job identities, sibling/content preservation, distinct polling and correction timing, stopped-service observation failures and scoped cleanup. Include rejection of a script that changes the mode once at startup and then sleeps: startup can pass, but the subsequent drift check must fail. Reuse existing public CLI entry points.
- [x] Document the manual sequence and update the command catalog and terminology where the experiment adds commands or meanings.
- [x] Run `make check` and `make test`. Report the required live worker and service run separately from offline checks and any optional smoke tests.
- [x] Create and run `docs/phase2/SLICE12_EVIDENCE.sh`. Capture actual output in `docs/phase2/SLICE12_EVIDENCE.md`, including the one-worker/zero-operator counts, CLI provenance comparisons, service-visible script digest, read-only mount and both files' modes and content checks. Record startup, deliberate drift and shutdown as three distinct observations with actual elapsed times and samples.

Defer `/metrics`, `goal_success`, notifications, goal completion and a Harness
deployment model. This slice records an independently observed experiment in
development code and evidence.

Verified on 2026-11-27. `make check` passed and `make test` passed 274 tests after engineering review.
The required live worker and separate service run passed all three observations.
[Captured evidence](SLICE12_EVIDENCE.md) · [Evidence script](SLICE12_EVIDENCE.sh)

## Engineering review

- [x] Persist and verify the goal's `standing` duration through the existing CLI.
- [x] Remove failed checkpoint staging and reject image changes on retry.
- [x] Submit the exact validated job bytes and handle incomplete Docker inspection results through cleanup.
- [x] Start the drift clock directly before the mode reset, after recording observation intent.
- [x] Reproduce seven regression failures before fixing them. Verify all 26 Slice 12 cases, the 274-test offline suite and a fresh live worker/service run.
