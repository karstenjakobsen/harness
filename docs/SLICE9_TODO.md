# Slice 9 — Run a container through Nomad

From a Linux development host, a developer can run `make test-nomad` to start a local Nomad cluster and prove that Harness can launch, inspect and stop a container. Slice 10 can use the same execution interface for a worker that reads a brief and skills over MCP and submits evidence against a goal revision. [Slice 9 design](SLICE9.md)

## Start the server and agent from the Makefile

The [Compose service](../dev/nomad/compose.yaml) owns the server image, ports, storage and leader health check. The [systemd user unit](../dev/nomad/harness-nomad-client@.service) runs the matching client binary on the host. Make starts both and waits for Docker driver readiness.

- [x] Add `make nomad-server` to start a single Nomad server in Docker and wait for leader election. Add `make nomad-agent` to start a Nomad client agent on the host. The client joins that server and uses the host Docker daemon to run workload containers. Check in both configurations, use a matching Nomad release for server and client, and assign local listen addresses and ports that let both run on one machine. [Nomad server configuration](https://developer.hashicorp.com/nomad/docs/configuration/server) · [Nomad client configuration](https://developer.hashicorp.com/nomad/docs/configuration/client)
- [x] Add `make nomad-up` to run those targets in order. Return success once the server reports the expected client ready with a healthy Docker driver. A second invocation reuses the same server and agent. Use a bounded readiness check and show the failed prerequisite or the relevant log path on failure.
- [x] Add `make nomad-down` to stop the project’s host agent and server container. Track their identities so teardown also works after a partial startup and a second teardown is safe. Document the host Nomad binary, Docker access, required host privileges, local API address and startup/test/teardown commands in the README. Add the targets to [CATALOG.md](../CATALOG.md).

## Execution contract

Construct `NomadBackend` with the API address of an already-running cluster. The development Make targets own cluster startup and teardown. The adapter’s three operations act on individual workloads at the supplied address and are callable from a plain Python test. For each attempt, the caller supplies a run ID and a spec containing a digest-pinned image and its argument vector. Keep Nomad job construction and API calls in the adapter, independent of goal, grant and operator-session models.

| Operation | Observable behavior |
| --- | --- |
| `start(run_id, spec)` | Return a handle for one batch job with a prestart allocation check and one workload task. Preserve every literal argument through Nomad’s driver configuration. Concurrent calls and retries with the same ID and spec resolve to the same job. A different spec under that ID returns a conflict. A deliberate new attempt uses a fresh ID. |
| `inspect(handle)` | Return execution state, job ID, allocation ID once placed, and the task’s exit code when reported. Distinguish pending placement, running and successful exit. Report `failed` for an unsuccessful exit and `stopped` once a requested stop has terminated the allocation. Preserve an unknown exit code when the task never started. Client loss or conflicting placements return `unknown`, with the identifiable original allocation ID and the observed replacement IDs. |
| `stop(handle)` | Request termination of that job with `purge=false`. Repeating the request is safe. The caller polls `inspect` to observe the outcome. |

Retries resolve to the original job while Nomad retains its registration. Inspection of the task outcome also requires the retained allocation. Once Nomad purges or garbage-collects the job, its ID can be reused. Capture the final inspection and required stdout before test cleanup. Slice 10 can persist the execution run and final observation in Harness when they need to outlive Nomad retention. [Nomad Jobs API](https://developer.hashicorp.com/nomad/api-docs/jobs)

- [x] Derive the job ID from the run ID and record the run identity and spec fingerprint in job metadata. Set `EnforceIndex=true` and `JobModifyIndex=0` for create-only registration. After a submission timeout or a concurrent registration, look up that exact job and compare its metadata before returning the handle. If the submit outcome is still unknown, surface that uncertainty so the caller can retry with the same ID. [Nomad job registration](https://developer.hashicorp.com/nomad/api-docs/jobs#register-or-update-job)
- [x] Disable automatic task restarts and failed-allocation rescheduling in the batch job. Read the exit code from the task termination event. Use the allocation’s stdout to verify the success marker. [Restart policy](https://developer.hashicorp.com/nomad/docs/job-specification/restart) · [Reschedule policy](https://developer.hashicorp.com/nomad/docs/job-specification/reschedule) · [Task logs](https://developer.hashicorp.com/nomad/api-docs/client#stream-logs)

## Acceptance

- [x] **Offline.** Exercise the adapter against a small Nomad HTTP fixture. Cover an accepted registration whose response is lost, conflicting reuse of a run ID, inspection before allocation, and an unreachable API. Add a dedicated pytest marker for real Nomad tests and exclude it from the existing offline selection in the [Makefile](../Makefile).
- [x] **Real Nomad.** Make `test-nomad` depend on `nomad-up`. From a stopped setup, run the cases below through the Python interface. Use a unique run ID per case, bound polling time, and clean up only the jobs created by the test, including after failure. Running the target again against the same cluster must pass.

| Case | Required observations |
| --- | --- |
| Successful exit | Print a unique marker from the container. Read it back from the allocation’s stdout and verify that inspection returns the job ID, allocation ID, successful state and exit code `0`. |
| Failed exit | Run a container that exits `7`. Assert that `inspect` reports `failed` with exit code `7`. Verify one allocation and zero workload restarts. |
| Concurrent start and repeated stop | Release two callers from a barrier so their first `start` calls use the same fresh run ID and long-running spec concurrently. Assert both return the same handle. Wait for `inspect` to report `running` and record the allocation ID. Call `stop` twice, then poll until `inspect` reports `stopped` for that same allocation. Verify in Nomad that the run created one job and one allocation with zero task restarts. |
| Literal arguments | Run `printf` with a literal `${NOMAD_ALLOC_ID}`, HCL template syntax, an empty argument and a spaced argument. Compare the container output against the caller’s vector. |
| Extra placement | Ask the scheduler to place a second allocation. Verify that the prestart check refuses it, the workload task records zero starts, and inspection reports `unknown` with both IDs. |
| Client heartbeat loss | On the disposable evidence cluster, suspend the client’s heartbeats during a running workload. Observe `unknown` and no exit code. Resume the client and verify the same allocation returns to `running` with zero restarts. |

- [x] Start only the Compose server without a systemd user session. Verify teardown removes the server and volume and reports the unverified client cleanup.
- [x] Run `make check`, `make test` and `make test-nomad` and report each result separately. Create and run `docs/SLICE9_EVIDENCE.sh` and capture its output in `docs/SLICE9_EVIDENCE.md`. Before cleanup, record server and client readiness, the pinned image, per-case job and allocation IDs, the observed marker and exit codes. For the concurrent case, capture both returned handles, the allocation count, task restart count and final `stopped` state. Verify `make nomad-down` against the setup the evidence script started. [Engineering guidelines](../AGENTS.md#tests-and-verification)

## Verification

`make check` passed and `make test` passed 188 offline tests, including the lost allocation followed by a successful legacy replacement. The [evidence script](SLICE9_EVIDENCE.sh) exercises the Nomad 2.1.1 container lifecycle and the review regressions on a disposable local cluster. [Captured output](SLICE9_EVIDENCE.md)
