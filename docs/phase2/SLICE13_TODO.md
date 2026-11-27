# Slice 13 — Watch a worker attempt while it runs

Prove that an owner can read a complete Codex event while the worker is still running and replay the same activity by attempt ID after Nomad removes the allocation. Use the existing CLI, generic worker image, city brief and worker MCP tools. Keep experiment code and tests in `dev/phase2/` and documentation in `docs/phase2/`. [Slice 13 plan](SLICE13.md) · [Slice 11 runner](../../dev/phase2/experiment.py) · [City assignment](../../dev/phase2/cities.json)

## Follow the worker

- [ ] Reuse Slice 11’s seed and render checkpoint, then explicitly submit the rendered Jinja job to Nomad once. Capture the worker’s existing `exec --json` output automatically, with no request for narration or a final summary.
- [ ] As soon as the runner learns the allocation ID, attach a manually operated host reader to the `workload` task. Follow stdout from the beginning and keep stderr separately labeled as diagnostics. Record the attempt ID, job ID, allocation ID and task together.
- [ ] Buffer bytes across transport chunks until a complete JSONL record is available. Handle a UTF-8 character split across reads and several records arriving in one read. Persist each event outside scratch and flush its readable rendering as it arrives.
- [ ] Preserve stdout order, event type, visible message text and any supplied turn or item IDs. Label host receipt time separately from any producer timestamp. Render observed turn boundaries, commands, outcomes and MCP activity. Retain unfamiliar event types by name. Leave absent text, outcomes and timestamps absent.
- [ ] Keep retained diagnostics in owner-only local files. Redact credential values from display, replay and published evidence, including values in stderr, malformed lines and unknown events. Limit the transcript to observable output.

## Prove live capture and replay

- [ ] Immediately after saving and displaying a complete event, independently query Nomad for that allocation’s `TaskStates["workload"].State`. Record the event, its display time and the subsequent timestamped task observation. Require `running` at that later check to pass live acceptance.
- [ ] After task exit, drain the reader. Before allocation cleanup, read retained stdout afresh from the beginning for the same allocation and task. Compare the full ordered records, including duplicates. Record both counts and the first difference if they disagree.
- [ ] Mark malformed records, a truncated final line or an interrupted stream as incomplete. Retain the complete events already seen and report capture status separately from the worker outcome. Preserve the runner’s credential revocation and scoped cleanup. A reader failure or replay must never submit another job.
- [ ] After cleanup, start a fresh reader with the attempt ID as its only lookup argument. Verify it reproduces the saved ordered transcript and capture status with the allocation and scratch gone.
- [ ] Use the existing Slice 11 checks to establish one worker session and zero AI operator sessions. Inspect `operator work show ATTEMPT_ID` in the seeded workspace for the authenticated brief and skill reads and successful `submit_work_result` call. Verify the saved `cities.txt` artifact. Identify which actions were visible in stdout, the MCP audit or Nomad. Attribute committed submissions to the audit and associate individual events with calls only when supported by the records.

## Verification and evidence

- [ ] Add offline reader tests using fragmented JSONL, including a split inside `København`, multiple records in a chunk, an unknown event and a run without assistant messages. Check ordered persistence, readable output and replay. Exercise malformed input, a truncated final line and stream interruption. Use a synthetic credential sentinel to verify redaction.
- [ ] Run `make check` and `make test`. Run the one-worker live experiment separately. Structured tool events can satisfy the live check even if the worker emits no assistant message.
- [ ] Create and run `docs/phase2/SLICE13_EVIDENCE.sh` and capture its sanitized output in `docs/phase2/SLICE13_EVIDENCE.md`. Include the manual commands, a short live excerpt, the subsequent running-task observation, the retained-stdout comparison, the session and artifact checks, and post-cleanup replay. Report offline and live results separately.
- [ ] Use the observed event types, missing fields and audit-only or Nomad-only facts to recommend fields for a future `get_worker_activity(attempt_id)`. Keep that tool at the design stage for this slice.
