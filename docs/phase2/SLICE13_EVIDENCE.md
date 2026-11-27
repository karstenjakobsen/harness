# Slice 13 evidence — watch one worker attempt and replay its activity

Run on 2026-11-27 with Nomad 2.1.1, one host client, the `harness-worker:slice10` image and an existing Codex login. One real Codex worker ran. No AI operator sessions ran. [Checklist](SLICE13_TODO.md) · [Script](SLICE13_EVIDENCE.sh)

## Manual commands

```sh
make worker-image
workspace="$PWD/.harness/phase2/slice13-ppZBJx"   # created by mktemp
.venv/bin/python dev/phase2/experiment.py seed --workspace "$workspace"
receipt="$workspace/phase2/receipt.json"
image="$(docker image inspect --format '{{.Id}}' harness-worker:slice10)"
.venv/bin/python dev/phase2/experiment.py render --receipt "$receipt" --image "$image"
cat "$workspace/phase2/prepared.json" "$workspace/phase2/job.json"   # checkpoint
make nomad-up
.venv/bin/python dev/phase2/watch.py run --receipt "$receipt"
.venv/bin/python dev/phase2/watch.py replay --workspace "$workspace" --attempt-id phase2-4ef27800b2ea4f7fa11159b053c1d039
SLICE13_WORKSPACE="$workspace" bash docs/phase2/SLICE13_EVIDENCE.sh
```

`make test-phase2-watch` runs the same sequence. The evidence script ran `make check` (Ruff passed, 121 files formatted) and `make test` (285 passed, 14 live or Nomad tests deselected). It then rechecked the retained capture against Nomad and a fresh `operator work show`.

## Observations

- Live event: the follower displayed and saved stdout line 4, a `worker` MCP `list_skills` call, at 13:10:47.889Z. Nomad was queried independently at 13:10:47.898Z and reported `client_status: running` and `task_state: running`. The task had started at 13:10:36.849Z and finished at 13:11:00.891Z.
- Worker outcome: the allocation completed with exit code 0 and zero restarts. Nomad's outcome was recorded after a final drain and before cleanup. The capture is `complete`: 18 JSONL events, 9,996 stdout bytes, no partial last line and no stream interruptions.
- Submission: the trace claims one completed `submit_work_result`. The worker MCP audit records that call as `returned` with artifact 1 (SHA-256 `9437f83a…967d`, goal revision 1, grant 1). The claim and audit agree. The goal stays active and completion remains a separate decision.
- Stderr: 205 bytes, kept separately in a mode-0600 file and not published. It contains Codex startup diagnostics, including a skills-root walk error.
- After cleanup Nomad returned 404 for both the job and the allocation. Scratch and runtime were removed. Replay by attempt ID found the live event at the same line and SHA-256.
- Incidental: the first command (line 12) exited 127 because `python` is missing from the image. The worker then verified the file with `diff` and submitted it. This does not affect acceptance.

## Captured script output

Selected fields only. Commands are truncated at 240 characters, and credential patterns are redacted.

```text
Nomad after cleanup: job 404, allocation 404
replay: {"line": 3, "event": "item.completed", "item_id": "item_0", "kind": "agent_message", "text": "I’ll check worker MCP for the assignment and skill revisions before starting work in the workspace."}
replay: {"line": 4, "event": "item.started", "item_id": "item_1", "kind": "mcp_tool_call", "server": "worker", "tool": "list_skills", "status": "in_progress", "argument_names": [], "error": null}
replay: {"line": 5, "event": "item.started", "item_id": "item_2", "kind": "mcp_tool_call", "server": "worker", "tool": "get_work_brief", "status": "in_progress", "argument_names": [], "error": null}
replay: {"line": 6, "event": "item.completed", "item_id": "item_1", "kind": "mcp_tool_call", "server": "worker", "tool": "list_skills", "status": "completed", "argument_names": [], "error": null}
replay: {"line": 7, "event": "item.completed", "item_id": "item_2", "kind": "mcp_tool_call", "server": "worker", "tool": "get_work_brief", "status": "completed", "argument_names": [], "error": null}
replay: {"line": 8, "event": "item.completed", "item_id": "item_3", "kind": "agent_message", "text": "I’ll use the assigned Workspace deliverable handoff skill, revision 1, to prepare the file for review."}
replay: {"line": 9, "event": "item.started", "item_id": "item_4", "kind": "mcp_tool_call", "server": "worker", "tool": "read_skill", "status": "in_progress", "argument_names": ["id", "revision"], "error": null}
replay: {"line": 10, "event": "item.completed", "item_id": "item_4", "kind": "mcp_tool_call", "server": "worker", "tool": "read_skill", "status": "completed", "argument_names": ["id", "revision"], "error": null}
replay: {"line": 11, "event": "item.started", "item_id": "item_5", "kind": "command_execution", "command": "/usr/bin/bash -lc \"printf '%s\\\\n' 'København' Aarhus Odense Aalborg Esbjerg > cities.txt &&\npython -c 'from pathlib import Path; p = Path(\\\"cities.txt\\\"); assert p.is_file() and not p.is_symlink(); assert p.read_bytes() == \\\"København\\\\nAar…", "status": "in_progress", "exit_code": null}
replay: {"line": 12, "event": "item.completed", "item_id": "item_5", "kind": "command_execution", "command": "/usr/bin/bash -lc \"printf '%s\\\\n' 'København' Aarhus Odense Aalborg Esbjerg > cities.txt &&\npython -c 'from pathlib import Path; p = Path(\\\"cities.txt\\\"); assert p.is_file() and not p.is_symlink(); assert p.read_bytes() == \\\"København\\\\nAar…", "status": "failed", "exit_code": 127}
replay: {"line": 13, "event": "item.started", "item_id": "item_6", "kind": "command_execution", "command": "/usr/bin/bash -lc 'test -f cities.txt && test ! -L cities.txt && diff -u <(printf '\"'%s\\\\n' 'København' Aarhus Odense Aalborg Esbjerg) cities.txt\"", "status": "in_progress", "exit_code": null}
replay: {"line": 14, "event": "item.completed", "item_id": "item_6", "kind": "command_execution", "command": "/usr/bin/bash -lc 'test -f cities.txt && test ! -L cities.txt && diff -u <(printf '\"'%s\\\\n' 'København' Aarhus Odense Aalborg Esbjerg) cities.txt\"", "status": "completed", "exit_code": 0}
replay: {"line": 15, "event": "item.started", "item_id": "item_7", "kind": "mcp_tool_call", "server": "worker", "tool": "submit_work_result", "status": "in_progress", "argument_names": ["relative_path"], "error": null}
replay: {"line": 16, "event": "item.completed", "item_id": "item_7", "kind": "mcp_tool_call", "server": "worker", "tool": "submit_work_result", "status": "completed", "argument_names": ["relative_path"], "error": null}
replay: {"line": 17, "event": "item.completed", "item_id": "item_8", "kind": "agent_message", "text": "Created [cities.txt](/workspace/cities.txt) and submitted it for operator review as artifact **1**. A `diff` check confirmed that all five city names appear in the requested order, one per line."}
Slice 13 acceptance verified from the retained capture, Nomad and a fresh owner CLI read
{
  "workspace": "/home/jakokar/projects/github/karstenjakobsen/harness/.harness/phase2/slice13-ppZBJx",
  "attempt_id": "phase2-4ef27800b2ea4f7fa11159b053c1d039",
  "job_id": "phase2-6b27d938c89443c7af0ffe6576ff5f58",
  "allocation_id": "837ef709-f50f-0ba4-632d-f1282bbed0a7",
  "task": "workload",
  "image": "sha256:6e01ee6710558a40bd4b5ed2e6ba1ab6e5f551b5c824f7f49d1fe73c36e9a222",
  "capture_status": "complete",
  "stdout_events": 18,
  "stderr_bytes": 205,
  "live_event": {
    "line": 4,
    "sha256": "12644fc291c55322d3a55cab27cbb433f65ce9ff3b88595a7bb040bdd61fdf3e",
    "displayed_at": "2026-11-27T13:10:47.889+00:00",
    "summary": {
      "event": "item.started",
      "item_id": "item_1",
      "kind": "mcp_tool_call",
      "server": "worker",
      "tool": "list_skills",
      "status": "in_progress",
      "argument_names": [],
      "error": null
    },
    "running_confirmed": true
  },
  "running_observation": {
    "line": 4,
    "observed_at": "2026-11-27T13:10:47.898+00:00",
    "client_status": "running",
    "task_state": "running",
    "task_started_at": "2026-11-27T13:10:36.849098236Z",
    "allocation_modify_time": 1795785037040831163
  },
  "task_outcome": {
    "observed_at": "2026-11-27T13:11:10.715+00:00",
    "client_status": "complete",
    "task_state": "dead",
    "failed": false,
    "restarts": 0,
    "exit_code": 0,
    "finished_at": "2026-11-27T13:11:00.891109847Z"
  },
  "worker_outcome": {
    "state": "complete",
    "exit_code": 0,
    "task_restarts": 0,
    "verified": true,
    "error": null
  },
  "submission": {
    "claimed_calls": 1,
    "claimed_success": true,
    "audited_calls": [
      {
        "tool": "submit_work_result",
        "outcome": "returned",
        "artifact_id": 1,
        "finished_at": "2026-11-27 13:10:57.199736"
      }
    ],
    "artifact": {
      "id": 1,
      "sha256": "9437f83af86c3ef8a1b091b44cc915bc38e8fac637a345b4c7c6ac7dc552967d",
      "attempt_id": "phase2-4ef27800b2ea4f7fa11159b053c1d039",
      "goal_revision": 1,
      "grant_id": 1
    },
    "consistent": true
  }
}
Sanitized replay excerpt (selected fields only)
{"line": 3, "event": "item.completed", "item_id": "item_0", "kind": "agent_message", "text": "I’ll check worker MCP for the assignment and skill revisions before starting work in the workspace."}
{"line": 6, "event": "item.completed", "item_id": "item_1", "kind": "mcp_tool_call", "server": "worker", "tool": "list_skills", "status": "completed", "argument_names": [], "error": null}
{"line": 7, "event": "item.completed", "item_id": "item_2", "kind": "mcp_tool_call", "server": "worker", "tool": "get_work_brief", "status": "completed", "argument_names": [], "error": null}
{"line": 8, "event": "item.completed", "item_id": "item_3", "kind": "agent_message", "text": "I’ll use the assigned Workspace deliverable handoff skill, revision 1, to prepare the file for review."}
{"line": 10, "event": "item.completed", "item_id": "item_4", "kind": "mcp_tool_call", "server": "worker", "tool": "read_skill", "status": "completed", "argument_names": ["id", "revision"], "error": null}
{"line": 12, "event": "item.completed", "item_id": "item_5", "kind": "command_execution", "command": "/usr/bin/bash -lc \"printf '%s\\\\n' 'København' Aarhus Odense Aalborg Esbjerg > cities.txt &&\npython -c 'from pathlib import Path; p = Path(\\\"cities.txt\\\"); assert p.is_file() and not p.is_symlink(); assert p.read_bytes() == \\\"København\\\\nAar…", "status": "failed", "exit_code": 127}
{"line": 14, "event": "item.completed", "item_id": "item_6", "kind": "command_execution", "command": "/usr/bin/bash -lc 'test -f cities.txt && test ! -L cities.txt && diff -u <(printf '\"'%s\\\\n' 'København' Aarhus Odense Aalborg Esbjerg) cities.txt\"", "status": "completed", "exit_code": 0}
{"line": 16, "event": "item.completed", "item_id": "item_7", "kind": "mcp_tool_call", "server": "worker", "tool": "submit_work_result", "status": "completed", "argument_names": ["relative_path"], "error": null}
{"line": 17, "event": "item.completed", "item_id": "item_8", "kind": "agent_message", "text": "Created [cities.txt](/workspace/cities.txt) and submitted it for operator review as artifact **1**. A `diff` check confirmed that all five city names appear in the requested order, one per line."}
```
