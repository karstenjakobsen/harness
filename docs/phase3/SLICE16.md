# Slice 16 — Delegate a work item against a specific goal revision

## Active Phase 3 decision

Implement only `WorkAPI.delegate_work(...)`: an authorized operator saves one
immutable work item against a specific goal revision. A later reader can follow
the item to that revision, the operator, the exact grant and the committing call.
Delegation creates zero attempts and leaves the goal unchanged.
[Implementation checklist](SLICE16_TODO.md)

The initial model-only implementation belongs in `packages/harness_api`.
The accepted follow-up below extends worker discovery and the shared run response.
Acceptance uses public Python operations and temporary SQLite; no MCP server,
Nomad cluster or AI session is required. Launch, worker/model/effort selection,
provider credentials and new transport operations remain future work.

Each recorded call can commit at most one work item, enforced by a uniqueness
constraint on the committing call. A call that already committed an item cannot
commit another, even with a different retry key while its reply is unfinished.
A genuine retry uses a new call and records retrieval of the original item.

Repository input requires an absolute source path and a full commit SHA. These
describe the requested input; accepting them authorizes no repository access.
Delegation does not read the repository or create a checkout. Repository access
authorization belongs to a future launch operation; no repository catalog is
needed here.

Recheck authority and the current goal revision before returning any replay.
A goal revision change rejects even an identical replay. The committed item
remains discoverable through history, which may be needed to recover after a
lost reply.

## Accepted follow-up

The accepted follow-up on 2026-11-28 addresses two handoff gaps. Delegated workers
can discover the workspace owner's current catalog and choose exact revisions
to read, without a required skill-selection argument on delegation. Brief hints
remain optional, and each successful read retains its exact revision in worker
audit. Owner-created items retain their explicit skill restrictions. Catalog
removal or replacement changes delegated workers' permission on the next call;
past reads retain their original audit.

Run inspection now shares a nullable `delegation_grant_id` through Python, HTTP
and MCP. Worker protocol descriptions and tests are included in this follow-up;
launch and provider credentials remain future work.

## Earlier discussion and future capabilities

The discussion below supplies context. The active decision above and its
checklist define Slice 16's implementation scope.

I’d separate what the operator requests, what the owner authorizes, and how the launcher supplies the credential. The operator should be able to say “use my work account for this attempt” using a credential reference. A Nomad Variable path, a host file path, and the secret itself can all stay outside the operator’s interface.

1. Give the operator two work operations

delegate_work(
    goal_id,
    expected_revision,
    brief,
    workspace_input,
    retry_key,
) -> WorkItem
launch_attempt(
    work_item_id,
    worker,          # "codex" | "kiro"
    model,
    effort,
    credential_ref,  # owner-managed ID, e.g. "work-kiro"
    retry_key,
) -> Attempt

The work item describes the assignment. The attempt describes one execution of it. Slice 14 demonstrated why this split matters: Codex and Kiro delivered the same work item under different attempts. A changed brief creates a new work item. Trying the same brief with another model, credential, or worker creates a new attempt.

I’d make launch_attempt return a durable attempt ID as soon as Harness accepts the request. The operator can inspect that ID after a lost reply. Repeating the same request with the same key returns the same attempt. Starting another worker is an explicit operator decision.

2. Make credentials first-class, owner-managed records

Field	Example	Why it belongs here
id and label	cred_42, “Work Kiro account”	Gives the operator a stable reference and a human-readable choice.
auth_method	api_key or saved_login	Describes what the credential contains.
service	kiro or openai	Identifies where the credential is valid. Two services can both issue API keys.
secret_ref	An internal reference to a Nomad Variable or private file	Lets the trusted runtime retrieve the secret. Only the runtime needs this field.

Independent selection still requires compatibility. A worker image has no permanent credential attached to it. The operator selects a credential for each attempt, and Harness checks whether that worker supports the credential’s service and auth method. Slice 15 demonstrated that the same Codex API-key method can use different storage sources without changing the assignment.

3. Let the operator request a credential without receiving the secret

I’d start with list_credentials() returning authorized IDs, labels, services, and auth methods. If nothing fits, the operator can tell the owner: “This attempt needs a Kiro API key. Add one through the owner CLI or UI and grant this operator permission to use it.” The owner enters the secret there. The operator then launches with the returned reference.

I wouldn’t add a request_credential workflow yet. A conversation plus an owner provisioning command is enough until you need pending requests or notifications. The important authority check is that permission to delegate work and permission to use a particular credential are separate. Validate both when accepting the attempt and recheck before dispatch if launch was delayed.

4. Keep the runtime interface small

render_worker_job(attempt, runtime_binding) -> NomadJobSpec

The attempt supplies the chosen worker, model, effort, and credential ID. Trusted configuration resolves the pinned image and the credential delivery mechanism. Jinja renders the job with the appropriate reference or mount. The worker still starts with harness-worker run --attempt-id ID and reads its brief through MCP.

There are two credentials at runtime. The selected provider credential authorizes model use. Harness issues a separate, short-lived attempt credential for worker MCP. Record the provider credential ID, authorizing grant, and committing operator call on the attempt so the owner can answer “Which account did this run use, and who authorized it?”

For the first slice, I’d prove this cold: seed two credential references for the same worker, launch two attempts against one work item with different references, and inspect the rendered specs and audit. Then try an unauthorized reference and verify it produces no dispatch. That tests the new design decision directly.

delegate_work(          # Save an assignment for a worker to carry out later.
    goal_id,            # The goal or subgoal this assignment serves.
    expected_revision,  # The goal revision the operator read when writing the brief.
    brief,              # What to deliver, including constraints and any skill hints.
    workspace_input,    # Starting material, e.g. an empty workspace or a repo at a pinned commit.
    retry_key,          # Reuse this key if the delegation reply is lost.
) -> WorkItem           # The saved assignment and its ID. Creating it starts no worker.
launch_attempt(         # Request one execution of a saved assignment.
    work_item_id,       # Identifies the assignment containing the brief and starting inputs.
    worker,             # The worker engine to run, e.g. "codex" or "kiro".
    model,              # The model this worker should use for this attempt.
    effort,             # The reasoning effort requested for that model.
    credential_ref,     # Owner-managed credential ID. The runtime supplies the secret.
    retry_key,          # Reuse this key if the launch reply is lost.
) -> Attempt            # The durable execution request and its ID. Completion is observed later.

delegate_work defines what should be done. launch_attempt records a decision to try it once. One work item can have several attempts, each with its own worker, model, effort, credential, and outcome.

Operator’s intent	Which call to make
“I lost the reply. Did my launch go through?”	Repeat launch_attempt with the same key and inputs to recover the original attempt.
“Codex failed. Let Kiro try the same assignment.”	Call launch_attempt with the same work item, a compatible credential, and a fresh key. Both attempts stay visible.
“I’ve changed what I want delivered.”	Call delegate_work with the revised brief and a fresh key to create a new work item.

Yes. The operator calls delegate_work and launch_attempt as tools on the operator MCP server. I’d implement the underlying operations in harness_api so the CLI and tests can use the same rules.

Layer	Responsibility
Operator MCP	Exposes the two tools, binds each call to the authenticated operator session, and records the call and its outcome.
WorkAPI	Checks the goal revision, grants, credential-use permission, and retry key. Saves the work item or attempt together with its link to the originating call.
Nomad adapter	Takes an accepted attempt, renders the Jinja spec, and submits the job.

Worker MCP is separate. Once launched, the worker can read its brief, consult skills, and submit its result. The authority to delegate work or launch another attempt stays with the operator.

I’d choose packages/harness_api and make Slice 16 “Delegate a work item against a specific goal revision.” Implement the first of the two proposed operations, WorkAPI.delegate_work(...). That gives the future operator MCP tool a tested function to call.

The package already supports creating work items. The new behavior is delegation under an operator’s authority. In one transaction, check the recorded operator call, its active grant, the target goal and expected revision. Save the brief and workspace input, and link the work item to the call that created it. An authorized replay with the same key and inputs returns the original work item.

Acceptance can run entirely in Python against temporary SQLite:

* Delegate once, reopen the workspace, and follow the work item back to its goal revision, operator, grant, and committing call.
* Replay the request and recover the same ID. Reusing the key with a changed brief produces a conflict.
* Verify that a withdrawn grant or a new request against a stale revision creates no work item. The successful delegation itself creates zero attempts.

I’d stop there. Model, effort, worker engine, and provider credential belong to launch_attempt. Slice 14 gave you the reason: Codex and Kiro can execute the same assignment. Keeping Slice 16 focused on the assignment preserves that choice for each attempt and requires no MCP server, Nomad cluster, or AI session to test.
