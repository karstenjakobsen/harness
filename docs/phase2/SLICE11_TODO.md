# Slice 11 — Manually start one real Codex worker

Implement the seed, render and explicit run steps in the development experiment.
The owner CLI seeds the goal, brief and attempt. The real worker reads its brief,
writes the deliverable and submits it through worker MCP. [Slice 11 plan](SLICE11.md)

- [x] Provide independent `seed`, `render` and `run` commands outside the installable packages.
- [x] Seed a new empty workspace through the installed CLI and retain all returned IDs and revisions in a receipt.
- [x] Render one Jinja job with strict undefined variables and JSON encoding. Preserve the prepared attempt and exact job as the checkpoint before submission.
- [x] Bind scratch, issue a private credential and serve worker MCP through the documented CLI commands. Supply the worker's model login privately at runtime.
- [x] Submit the rendered job directly to Nomad from the development script. Disable restarts and rescheduling and retain the allocation outcome and worker logs.
- [x] Verify one real worker session, zero AI operator sessions, successful MCP brief and skill reads, and a successful file submission with its original attribution.
- [x] Retrieve exact `cities.txt` bytes through Harness after worker exit and after scratch cleanup. Preserve the goal's active status and revision.
- [x] Revoke the credential and clean up the experiment's server, job, volumes and runtime files, including on failure.
- [x] Keep deterministic success and exit-7 commands available as optional Nomad smoke tests with separate results.
- [x] Add Make targets, update the command catalog and terminology, and document the individual steps and a receipt in the README.
- [x] Run `make check` and `make test`. Create and run `SLICE11_EVIDENCE.sh`, capture actual output in `SLICE11_EVIDENCE.md`, and report required live acceptance separately from smoke tests.

Verified on 2026-11-27. Updated live worker acceptance passed with Codex
`danger-full-access` and Docker default security profiles. `make check` passed
and `make test` passed 248 tests. Optional scheduler smoke tests also passed. [Captured evidence](SLICE11_EVIDENCE.md) · [Evidence script](SLICE11_EVIDENCE.sh)

## Container isolation and recovery review

- [x] Run the container worker with Codex full access and default Docker security profiles.
- [x] Persist the observed allocation and exit before cleanup. Retry a failed final export through Harness while retaining one Nomad submission.
- [x] Record runtime grant and MCP process ownership before execution. Recover interruption by revoking the old credential, stopping its listener and removing the private directory.
- [x] Exercise both regressions with real CLI processes, SQLite files and MCP listeners, including older failed-export receipts and process identity mismatches.
- [x] Capture the updated live and offline evidence.
