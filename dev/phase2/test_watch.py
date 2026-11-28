import json

import watch


def test_truncated_last_line_keeps_earlier_events_and_labels_capture(tmp_path):
    directory = watch.activity_directory(tmp_path, "attempt-1")
    directory.mkdir(parents=True)
    command = {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "command_execution",
            "command": "curl -H 'Authorization: Bearer secret-token' x",
            "status": "completed",
            "exit_code": 0,
        },
    }
    lines = [{"type": "thread.started"}, command]
    (directory / "stdout.jsonl").write_bytes(
        b"".join(json.dumps(line).encode() + b"\n" for line in lines)
        + b'{"type": "item.started", "item": {"type": "mcp'
    )
    events, _ = watch.read_events(directory / "stdout.jsonl")
    (directory / "capture.json").write_text(
        json.dumps(
            {
                "attempt_id": "attempt-1",
                "job_id": "job-1",
                "allocation_id": "alloc-1",
                "task": "workload",
                "status": "capturing",
                "live_event": {"line": 2, "sha256": events[1][2]},
                "task_outcome": None,
                "submission": None,
            }
        )
    )
    result = watch.replay(tmp_path, "attempt-1")
    assert result["events"] == 2 and result["partial_last_line"]
    assert result["capture_status"] == "incomplete"
    assert result["live_event_located"] == {"line": 2, "sha256": events[1][2]}
    assert "secret-token" not in watch.summary(command)["command"]


def test_kiro_tool_event_keeps_status_and_redacts_the_title():
    event = {
        "type": "sessionUpdate",
        "data": {
            "sessionId": "kiro-session",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "call-1",
                "title": "Read assignment using fixture-token",
                "status": "in_progress",
                "rawInput": {"credential": "fixture-token"},
            },
        },
    }
    assert watch.summary(event, ("fixture-token",)) == {
        "event": "tool_call",
        "kind": "tool_call",
        "item_id": "call-1",
        "title": "Read assignment using [redacted]",
        "status": "in_progress",
    }
