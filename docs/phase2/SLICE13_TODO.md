# Slice 13 — Watch one worker attempt and replay its activity

Use the Slice 11 city assignment, worker image, prompt and MCP tools as they are. Keep the host reader in `dev/phase2/`. [Slice 13 plan](SLICE13.md) · [Slice 11 runner](../../dev/phase2/experiment.py)

- [ ] Seed and render the city job, then submit it directly to Nomad. Run one real Codex worker with zero AI operator sessions.
- [ ] When the allocation ID is available, follow the `workload` task’s stdout from the beginning. Save its JSONL outside scratch under the attempt ID, alongside the job, allocation and task identifiers. Keep stderr separate and raw diagnostics private.
- [ ] Display and save a substantive event, such as a command execution or MCP call. Then query Nomad independently and record the time it reports that same task still running. Select credential-free fields for display. Include worker messages or visible reasoning summaries only when emitted.
- [ ] At exit, record Nomad’s task outcome and drain stdout before cleanup. Check any claimed artifact submission against the worker MCP audit using `operator work show ATTEMPT_ID`. If capture is interrupted, retain readable events and label the capture incomplete.
- [ ] After allocation cleanup, replay the activity by attempt ID and locate the event seen live. A failed worker can still demonstrate capture and replay. Record its delivery outcome and any saved artifact. Leave any decision to run a fresh attempt to the person operating the experiment.
- [ ] Run `make check` and `make test`. Use the single real run for acceptance. Add at most one small reader test if needed, for example to verify that a truncated final line preserves earlier events.
- [ ] Create and run `docs/phase2/SLICE13_EVIDENCE.sh`. In `docs/phase2/SLICE13_EVIDENCE.md`, record the manual commands, a sanitized event excerpt, the subsequent running-task observation, the worker and submission outcomes, and the post-cleanup replay.
