# Slice 9 verification

On 2026-11-26 the evidence script ran on Linux under WSL2 with Docker Desktop. Compose started the pinned Nomad 2.1.1 server and waited for leader election. The checked-in systemd user unit started the matching Nomad client on the host. The captured unit invocation and Compose container ID identify both processes across the two test runs. [Evidence script](SLICE9_EVIDENCE.sh)

| Check | Result |
| --- | --- |
| `make check` | Ruff lint and format checks passed. |
| `make test` | 188 offline tests passed. |
| `make test-nomad` | Five cases passed from a cold start. Six passed on the warm cluster including heartbeat loss and reconnect. The extra placement recorded zero workload starts. |
| `make nomad-down` | After server-only startup, teardown removed Compose and reported unverified client cleanup. Normal and repeated teardown succeeded. |

After the cold-start test, the existing development cluster was migrated onto the Compose volume. The restored server reported the original Raft peer ID as leader at `127.0.0.1:14647`, and the systemd client registered with its original node ID. A separate `make test-nomad` passed all three workload cases on that cluster. It was left running.

## Review verification

The review run used the same configuration on ports 24646–24651 in a disposable checkout-scoped project. The heartbeat test ran only on its dedicated client during the warm run.

```text
Server-only startup and teardown without a systemd user session
dev/nomad/cluster.sh server
 Network harness-nomad-1029328aa686_default Creating
 Network harness-nomad-1029328aa686_default Created
 Volume harness-nomad-1029328aa686_server-data Creating
 Volume harness-nomad-1029328aa686_server-data Created
 Container harness-nomad-1029328aa686-server-1 Creating
 Container harness-nomad-1029328aa686-server-1 Created
 Container harness-nomad-1029328aa686-server-1 Starting
 Container harness-nomad-1029328aa686-server-1 Started
 Container harness-nomad-1029328aa686-server-1 Waiting
 Container harness-nomad-1029328aa686-server-1 Healthy
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh down
Missing XDG_RUNTIME_DIR for the systemd user session.
Nomad client cleanup could not be verified. Retry from the checkout's systemd user session.
 Container harness-nomad-1029328aa686-server-1 Stopping
 Container harness-nomad-1029328aa686-server-1 Stopped
 Container harness-nomad-1029328aa686-server-1 Removing
 Container harness-nomad-1029328aa686-server-1 Removed
 Network harness-nomad-1029328aa686_default Removing
 Volume harness-nomad-1029328aa686_server-data Removing
 Volume harness-nomad-1029328aa686_server-data Removed
 Network harness-nomad-1029328aa686_default Removed
make: *** [Makefile:33: nomad-down] Error 1
Cold start and real workloads
dev/nomad/cluster.sh server
 Network harness-nomad-1029328aa686_default Creating
 Network harness-nomad-1029328aa686_default Created
 Volume harness-nomad-1029328aa686_server-data Creating
 Volume harness-nomad-1029328aa686_server-data Created
 Container harness-nomad-1029328aa686-server-1 Creating
 Container harness-nomad-1029328aa686-server-1 Created
 Container harness-nomad-1029328aa686-server-1 Starting
 Container harness-nomad-1029328aa686-server-1 Started
 Container harness-nomad-1029328aa686-server-1 Waiting
 Container harness-nomad-1029328aa686-server-1 Healthy
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"38817c43-015d-cc91-a814-5fac2a67c46e","name":"harness-nomad-1029328aa686-client","status":"ready","docker":true}
HARNESS_NOMAD_ADDR=http://127.0.0.1:24646 uv --directory /home/karsten/projects/github/karstenjakobsen/harness run --locked --all-packages pytest -q -s -m nomad
WorkloadStatus(state='succeeded', job_id='harness-15471958c4805e7b09d5dbaf3d0317964b35e118798c964178abc1e054540a09', allocation_id='3444c7f4-4151-1339-fd70-a4aef0fa82df', exit_code=0, replacement_allocation_ids=()) allocations=1 restarts=0
stdout=slice9-7f613198-8838-4e6f-bf28-3e293507ef5c image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
.WorkloadStatus(state='failed', job_id='harness-1fdf131dfbfa234a93b5c9171708d8a29b7fb303413a18273a5dbc5dba17c4da', allocation_id='d21561be-6413-b729-1a0b-a8f3352987ac', exit_code=7, replacement_allocation_ids=()) allocations=1 restarts=0
.concurrent handles: harness-7c6412dab1be37603f45fd32d35dda47adc4186a2370e5ac93d6840885fea70a harness-7c6412dab1be37603f45fd32d35dda47adc4186a2370e5ac93d6840885fea70a
WorkloadStatus(state='stopped', job_id='harness-7c6412dab1be37603f45fd32d35dda47adc4186a2370e5ac93d6840885fea70a', allocation_id='30ffde43-b768-bf56-05ca-3dbbed6df5b1', exit_code=137, replacement_allocation_ids=()) allocations=1 restarts=0
.Verified literal argv including ${NOMAD_ALLOC_ID} on allocation dddfd73a-21bc-f15a-e000-123d99b9eeb6
.WorkloadStatus(state='unknown', job_id='harness-3ac318c529c11681faf8af32bf450d57c03b215ee567b0817d79e679fb60e8a9', allocation_id='f32579d0-5543-afb6-78a5-5e266402babd', exit_code=None, replacement_allocation_ids=('f4dcfaf2-0012-1dad-7762-c3d760364da8',)) additional workload starts=0
.s
5 passed, 1 skipped, 196 deselected in 24.25s
Repeat on the running cluster and test loss of the disposable client’s heartbeat
dev/nomad/cluster.sh server
 Container harness-nomad-1029328aa686-server-1 Running
 Container harness-nomad-1029328aa686-server-1 Waiting
 Container harness-nomad-1029328aa686-server-1 Healthy
Nomad v2.1.1
BuildDate 2026-10-29T14:48:23Z
Revision d0f21042997689c7690421ede8849be694e2ce46
dev/nomad/cluster.sh agent
{"node":"38817c43-015d-cc91-a814-5fac2a67c46e","name":"harness-nomad-1029328aa686-client","status":"ready","docker":true}
HARNESS_NOMAD_ADDR=http://127.0.0.1:24646 uv --directory /home/karsten/projects/github/karstenjakobsen/harness run --locked --all-packages pytest -q -s -m nomad
WorkloadStatus(state='succeeded', job_id='harness-7c8d81f13f8ca271227c1727bea615d95814321bbb30e26114ee5b8ac3a26544', allocation_id='8e653041-a4a4-2252-fd61-9f6c713ddd3c', exit_code=0, replacement_allocation_ids=()) allocations=1 restarts=0
stdout=slice9-6c22c54e-efbe-422e-bc32-b1efd39d916f image=docker.io/library/busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec
.WorkloadStatus(state='failed', job_id='harness-8d0dcaba4b2ebf358634156c849d34e149d2ee610700d8ce717220f4ab0af8d2', allocation_id='06bf5b29-0e43-ba59-5b1d-868201b83d3a', exit_code=7, replacement_allocation_ids=()) allocations=1 restarts=0
.concurrent handles: harness-463c1ff8123f1acba250a0d3ae3006ae3f340d900c8ec05c31091203c39a3a02 harness-463c1ff8123f1acba250a0d3ae3006ae3f340d900c8ec05c31091203c39a3a02
WorkloadStatus(state='stopped', job_id='harness-463c1ff8123f1acba250a0d3ae3006ae3f340d900c8ec05c31091203c39a3a02', allocation_id='32d3ddd7-5f68-840b-9131-5a404d82f564', exit_code=137, replacement_allocation_ids=()) allocations=1 restarts=0
.Verified literal argv including ${NOMAD_ALLOC_ID} on allocation 56c10565-b5e6-b7b0-95eb-4273bb9bb08c
.WorkloadStatus(state='unknown', job_id='harness-f0d0440ba1edde0e3fa6027a68464e10b570d844cb6985d0596f689cc28451fc', allocation_id='c4e25853-f811-de20-5202-6d08cc7b73ab', exit_code=None, replacement_allocation_ids=('f62f4031-2f0c-5a41-a7c0-d8062fe7392b',)) additional workload starts=0
.Missed client heartbeats: WorkloadStatus(state='unknown', job_id='harness-d4cc7014630f8605c24f056efa3114f098c86c7322d8581bcf00827431bd9b11', allocation_id='52797aa6-4d76-88f9-3bdc-9d830661aa40', exit_code=None, replacement_allocation_ids=())
WorkloadStatus(state='running', job_id='harness-d4cc7014630f8605c24f056efa3114f098c86c7322d8581bcf00827431bd9b11', allocation_id='52797aa6-4d76-88f9-3bdc-9d830661aa40', exit_code=None, replacement_allocation_ids=()) allocations=1 restarts=0
.
6 passed, 196 deselected in 57.72s
Reused server=bcb3a1c2029134e1b48fd07feefa2f67e46fe4cc5c03b76a74dca0f0e79289b6 client_unit=harness-nomad-client@1029328aa686.service client_invocation=ca0f95a950334cd9b3af3418e276cdc4
Teardown and repeat teardown
dev/nomad/cluster.sh down
 Container harness-nomad-1029328aa686-server-1 Stopping
 Container harness-nomad-1029328aa686-server-1 Stopped
 Container harness-nomad-1029328aa686-server-1 Removing
 Container harness-nomad-1029328aa686-server-1 Removed
 Network harness-nomad-1029328aa686_default Removing
 Volume harness-nomad-1029328aa686_server-data Removing
 Volume harness-nomad-1029328aa686_server-data Removed
 Network harness-nomad-1029328aa686_default Removed
dev/nomad/cluster.sh down
Verified the project server and host client are down.
```
