# Slice 9 verification

On 2026-11-26 the evidence script ran on Linux under WSL2 with Docker Desktop. Compose started the pinned Nomad 2.1.1 server and waited for leader election. The checked-in systemd user unit started the matching Nomad client on the host. The captured unit invocation and Compose container ID identify both processes across the two test runs. [Evidence script](SLICE9_EVIDENCE.sh)

| Check | Result |
| --- | --- |
| `make check` | Ruff lint and format checks passed. |
| `make test` | 186 offline tests passed. |
| `make test-nomad` | All three cases passed from a cold start and again on the same server container and host client process. Each workload had one allocation and zero restarts. |
| `make nomad-down` | Both teardown calls succeeded. The script verified that the project server and client were down. |

After the cold-start test, the existing development cluster was migrated onto the Compose volume. The restored server reported the original Raft peer ID as leader at `127.0.0.1:14647`, and the systemd client registered with its original node ID. A separate `make test-nomad` passed all three workload cases on that cluster. It was left running.

## Captured output

```text
Cold start and three real workloads
dev/nomad/cluster.sh server
 Network harness-nomad-0b269c4e35b3_default Creating
 Network harness-nomad-0b269c4e35b3_default Created
 Volume harness-nomad-0b269c4e35b3_server-data Creating
 Volume harness-nomad-0b269c4e35b3_server-data Created
 Container harness-nomad-0b269c4e35b3-server-1 Creating
 Container harness-nomad-0b269c4e35b3-server-1 Created
 Container harness-nomad-0b269c4e35b3-server-1 Starting
 Container harness-nomad-0b269c4e35b3-server-1 Started
 Container harness-nomad-0b269c4e35b3-server-1 Waiting
 Container harness-nomad-0b269c4e35b3-server-1 Healthy
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"b3a66d65-c90e-6580-c9b9-d983e7f3a4a9","name":"harness-nomad-0b269c4e35b3-client","status":"ready","docker":true}
HARNESS_NOMAD_ADDR=http://127.0.0.1:14646 uv run --locked --all-packages pytest -q -s -m nomad
WorkloadStatus(state='succeeded', job_id='harness-ac962371b71ebc9773696f371f92589dd8cfabc841616046bad44f307bacaab6', allocation_id='7211f3e3-6fdf-25cf-b20e-33a6a2e9372b', exit_code=0) allocations=1 restarts=0
stdout=slice9-4c1d5dc2-1393-4386-a1f7-4a45ac8047f7 image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
.WorkloadStatus(state='failed', job_id='harness-c01f4e38f6567c2716ec4624e22b80daf5ed8b8f29da4b46232da67b9927a022', allocation_id='941d4a40-ac30-fd76-25cd-a111ef883031', exit_code=7) allocations=1 restarts=0
.concurrent handles: harness-4678facb3bd04be5f0a6f2f39430e596ec6b4348b3555d7f97a686de64f7d722 harness-4678facb3bd04be5f0a6f2f39430e596ec6b4348b3555d7f97a686de64f7d722
WorkloadStatus(state='stopped', job_id='harness-4678facb3bd04be5f0a6f2f39430e596ec6b4348b3555d7f97a686de64f7d722', allocation_id='778702c6-0cbd-67fe-3d20-f95b3492757d', exit_code=137) allocations=1 restarts=0
.
3 passed, 194 deselected in 10.71s
Repeat on the running cluster
dev/nomad/cluster.sh server
 Container harness-nomad-0b269c4e35b3-server-1 Running
 Container harness-nomad-0b269c4e35b3-server-1 Waiting
 Container harness-nomad-0b269c4e35b3-server-1 Healthy
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"b3a66d65-c90e-6580-c9b9-d983e7f3a4a9","name":"harness-nomad-0b269c4e35b3-client","status":"ready","docker":true}
HARNESS_NOMAD_ADDR=http://127.0.0.1:14646 uv run --locked --all-packages pytest -q -s -m nomad
WorkloadStatus(state='succeeded', job_id='harness-ccc156f2bfd8a9011eae0243e1d527c4ce7409af48c55cd8d443326163010f8e', allocation_id='37a4e98a-249e-596b-1752-e54b674dadf3', exit_code=0) allocations=1 restarts=0
stdout=slice9-b6986962-28ce-448c-8874-d618cbd1f803 image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
.WorkloadStatus(state='failed', job_id='harness-a9e0635b48951ee8670622d80e34daea7fbb243236c0cfd856fac2dc0f598941', allocation_id='ba62921c-1f24-0ab7-b93d-913c232c1bdb', exit_code=7) allocations=1 restarts=0
.concurrent handles: harness-2a45b09b27da9be616af08e20992fc0556774fed4cf2b84138a5b7f1fb0801dc harness-2a45b09b27da9be616af08e20992fc0556774fed4cf2b84138a5b7f1fb0801dc
WorkloadStatus(state='stopped', job_id='harness-2a45b09b27da9be616af08e20992fc0556774fed4cf2b84138a5b7f1fb0801dc', allocation_id='b669f606-0e39-de34-2378-978addd58cdb', exit_code=137) allocations=1 restarts=0
.
3 passed, 194 deselected in 10.66s
Reused server=772f8de538c3149549ab47e857ee6585f57de37d094fb259453ca65ac78f4740 client_unit=harness-nomad-client@0b269c4e35b3.service client_invocation=7b9b122c15e246c3888bdceb468e1304
Teardown and repeat teardown
dev/nomad/cluster.sh down
 Container harness-nomad-0b269c4e35b3-server-1 Stopping
 Container harness-nomad-0b269c4e35b3-server-1 Stopped
 Container harness-nomad-0b269c4e35b3-server-1 Removing
 Container harness-nomad-0b269c4e35b3-server-1 Removed
 Network harness-nomad-0b269c4e35b3_default Removing
 Volume harness-nomad-0b269c4e35b3_server-data Removing
 Volume harness-nomad-0b269c4e35b3_server-data Removed
 Network harness-nomad-0b269c4e35b3_default Removed
dev/nomad/cluster.sh down
Verified the project server and host client are down.
```
