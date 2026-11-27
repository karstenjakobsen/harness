# Slice 13 — Watch one worker attempt and replay its activity

Can we see what a worker did while it was running and inspect the same activity after its allocation is gone? Use the existing [Slice 11 experiment](SLICE11.md), city assignment, worker image and worker MCP. Keep the reader in `dev/phase2/` and the evidence in `docs/phase2/`. This slice needs zero changes to `packages/` or the worker prompt.

## One live acceptance run

- [ ] Manually start one real Codex worker with zero AI operator sessions. From the host, follow its Nomad task stdout from the beginning. Save the emitted JSONL outside scratch under the attempt ID, with the job, allocation and task identifiers. Keep stderr separate and raw diagnostics private.
- [ ] Display and persist a substantive event such as a command execution or MCP call. Then independently confirm the same task is still running. Retain the event and the timestamp of that observation. Show worker messages or visible reasoning summaries only when emitted.
- [ ] At exit, record Nomad's observed outcome. Check any claimed submission against the worker MCP audit. Finish reading before allocation cleanup, then replay the captured activity by attempt ID. Record the manual commands, a sanitized excerpt and the live and replay observations in `SLICE13_EVIDENCE.md`. A failed worker can demonstrate capture and replay if the live-event check passed; report its delivery outcome accurately.

## When something fails

A failed job remains a finished attempt with its own outcome, available activity and any submitted artifact. If the reader loses part of the stream, keep the readable portion and label the capture incomplete. The reader only observes. During Phase 2 we decide manually whether another execution is worthwhile. Later the operator can inspect the evidence, retry the same work with a fresh attempt ID, request a revised brief or report the blocker. A retry preserves the original attempt and its transcript.

## Test budget

Use the real run as the acceptance test. Run the existing repository checks. Add at most one small reader test if new parsing or display code introduces a specific risk, such as a truncated last line hiding earlier complete events. Skip simulated Nomad lifecycles, forced worker failures, retry policies and a crash-recovery matrix. Keep credentials out of displayed or published evidence; use selected fields for the readable excerpt.
