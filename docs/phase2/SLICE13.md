# Slice 13 — Watch a worker attempt while it runs

Can we watch a live Codex worker act, then inspect the same activity after its allocation is gone? Reuse the Slice 11 city assignment and generic worker image. The image already starts Codex with `exec --json`. Slice 11 reads stdout after termination. This experiment follows that output during execution and saves an owner-readable transcript outside the allocation.

## Scope

Experiment code and tests live under `dev/phase2/` and documentation under `docs/phase2/`. Use the existing CLI, worker image, brief and MCP tools. Keep `packages/` unchanged. We operate the reader manually. A future operator activity tool can use the results when we design its contract.

Capture observable execution events automatically. The worker needs no instruction to narrate, publish logs or submit a summary. A visible assistant message is available only if emitted. Private model reasoning is unavailable. Treat this as a diagnostic transcript: the MCP server audit remains the source for authenticated reads and committed submissions.

## Experiment

- [ ] Start one real worker through the Phase 2 experiment with zero AI operator sessions. As soon as the allocation ID is known, have a reader outside the container follow the Nomad allocation's worker-task stdout from the beginning. Keep stderr separately labeled as diagnostic output.
- [ ] Associate the capture with the attempt, job, allocation and task. Incrementally assemble complete JSONL records across transport chunks, including split UTF-8 characters. Save events outside scratch as they arrive and show them as readable text. Preserve event order, visible message text, and turn or item IDs when supplied. Label host receipt times separately from producer timestamps.
- [ ] Inspect which event types the pinned worker actually emits. Show observed turn boundaries, commands and outcomes, MCP activity and visible messages where present. Preserve unknown event types as such. Do not invent missing text, outcomes or links between log events and audit calls.
- [ ] Use private local files for retained diagnostics and exclude credential values from the rendered transcript and published evidence. Record malformed or truncated output and an interrupted stream as incomplete. Capture failure must never submit another job.
- [ ] After task exit, drain the stream before allocation cleanup. For this short run, compare the ordered captured stdout records with a fresh read of retained allocation stdout before teardown. After cleanup, replay the saved transcript using the attempt ID alone.

## Acceptance

- [ ] During the live run, persist and display at least one complete Codex event, then independently observe the same Nomad task still running. Record both observations. A transcript first produced after exit cannot pass this check.
- [ ] Verify one worker session, zero AI operator sessions, and a successful city artifact submission in the existing MCP audit. Show the actual events available to the reader and identify any actions visible only in MCP or Nomad. The test can pass with a silent worker that emits structured tool events.
- [ ] Offline, feed representative fragmented records and a truncated final line through the reader. Check ordering, readable output, explicit incomplete status and credential redaction using a synthetic sentinel.
- [ ] Record the manual commands, a short sanitized live excerpt, the pre-exit observation, post-cleanup replay and comparison result in `docs/phase2/SLICE13_EVIDENCE.md`. Report offline and live checks separately. Use the findings to decide which fields a future `get_worker_activity(attempt_id)` should expose.
