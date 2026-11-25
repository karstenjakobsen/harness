import csv
import json
import subprocess
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

QUESTION = (
    "For my Lose 20 lb goal, list each subgoal, tell me which is complete and how "
    "we know, give the current food-tracking duration, and tell me whether the "
    "parent goal is complete. Return only CSV, one row for the parent and each "
    "subgoal, with the header title,status,evidence_kind,evidence,duration_days. "
    "Use the exact current goal title and report the status as open or complete. "
    "Copy the saved completion evidence kind and text, and give the current duration "
    "in whole days. Leave fields empty when there is no value."
)


def assert_tool_result(trace, tool, goal_id, expected):
    for line in trace.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        item = event.get("item", {})
        if (
            event["type"] == "item.completed"
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "harness_mcp"
            and item.get("tool") == tool
            and item.get("arguments", {}).get("goal_id") == goal_id
            and item.get("status") == "completed"
            and not item.get("error")
        ):
            result = item.get("result")
            if result and not (result.get("isError") or result.get("is_error")):
                record = result.get("structuredContent") or result.get(
                    "structured_content"
                )
                if record is None:
                    record = json.loads(result["content"][0]["text"])
                if record == expected:
                    return
    pytest.fail(
        f"No successful {tool} call returned the expected record for goal {goal_id}"
    )


def test_trace_accepts_a_matching_read_after_an_earlier_revision(tmp_path):
    trace = tmp_path / "reads.jsonl"
    with trace.open("w", encoding="utf-8") as stream:
        for revision in (1, 2):
            item = {
                "type": "mcp_tool_call",
                "server": "harness_mcp",
                "tool": "get_goal_progress",
                "arguments": {"goal_id": 7, "revision": revision},
                "status": "completed",
                "result": {"structuredContent": {"revision": revision}},
            }
            print(json.dumps({"type": "item.completed", "item": item}), file=stream)
    assert_tool_result(trace, "get_goal_progress", 7, {"revision": 2})


def assert_plan_answer(answer):
    lines = answer.strip().splitlines()
    if lines and lines[0] in ("```", "```csv") and lines[-1] == "```":
        lines = lines[1:-1]
    reader = csv.reader(lines)
    assert next(reader, None) == [
        "title",
        "status",
        "evidence_kind",
        "evidence",
        "duration_days",
    ]
    assert sorted(reader) == [
        ["Build a personal tracker", "open", "", "", ""],
        [
            "Get a gym membership",
            "complete",
            "owner_confirmation",
            "I confirm my gym membership is active.",
            "",
        ],
        ["Lose 20 lb", "open", "", "", ""],
        ["Track food for fourteen days", "open", "", "", "14"],
    ]


PLAN_ROWS = """\
title,status,evidence_kind,evidence,duration_days
Track food for fourteen days,open,,,14
Build a personal tracker,open,,,
Lose 20 lb,open,,,
Get a gym membership,complete,owner_confirmation,I confirm my gym membership is active.,
"""


def test_answer_accepts_goal_rows_in_any_order():
    assert_plan_answer(PLAN_ROWS)


@pytest.mark.parametrize(
    "correct,wrong",
    [
        ("membership,complete", "membership,open"),
        ("tracker,open", "tracker,complete"),
        ("days,open", "days,complete"),
        ("lb,open", "lb,complete"),
        ("owner_confirmation", "owner_supplied_reference"),
        ("I confirm my gym membership is active.", ""),
        ("open,,,14", "open,,,7"),
        ("Build a personal tracker,open,,,\n", ""),
        ("Lose 20 lb,open,,,", "Lose 20 lb,open,,,\nLose 20 lb,open,,,"),
    ],
)
def test_answer_rejects_incorrect_or_missing_goal_facts(correct, wrong):
    with pytest.raises(AssertionError):
        assert_plan_answer(PLAN_ROWS.replace(correct, wrong))


@pytest.fixture
def live_directory(tmp_path):
    with TemporaryDirectory(dir=tmp_path, prefix="live-") as directory:
        yield Path(directory)


@pytest.fixture
def workspace(live_directory):
    workspace = live_directory / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def run(workspace):
    operator = Path(sysconfig.get_path("scripts")) / "operator"

    def invoke(*args):
        result = subprocess.run(
            [operator, *map(str, args)],
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    return invoke


@pytest.fixture
def goal(run):
    def invoke(*args):
        return json.loads(run("goal", *args))

    return invoke


@pytest.mark.live
def test_ask_explains_saved_plan_through_mcp(live_directory, workspace, run, goal):
    database = workspace / ".harness/goals.sqlite3"
    assert not database.exists()
    parent = goal("create", "--title", "Lose 20 lb")
    parent_id = parent["id"]
    assert parent["status"] == "active"
    assert database.is_file()

    def child(title, criteria, method, *options):
        return goal(
            "create",
            "--title",
            title,
            "--parent",
            parent_id,
            "--success-criteria",
            criteria,
            "--measurement-plan",
            method,
            *options,
        )

    tracker = child(
        "Build a personal tracker", "Can save an entry", "Manual entry check"
    )
    gym = child("Get a gym membership", "Membership is active", "Owner confirmation")
    food = child(
        "Track food for seven days",
        "A food entry each day",
        "Review the log",
        "--duration-days",
        7,
    )
    assert len({parent_id, tracker["id"], gym["id"], food["id"]}) == 4
    goal(
        "complete",
        gym["id"],
        "--revision",
        gym["revision"],
        "--confirmation",
        "I confirm my gym membership is active.",
    )
    goal(
        "revise",
        food["id"],
        "--title",
        "Track food for fourteen days",
        "--duration-days",
        14,
    )
    history = goal("show", food["id"], "--history")
    assert [(r["revision"], r["duration_days"]) for r in history] == [
        (food["revision"], 7),
        (food["revision"] + 1, 14),
    ]
    tree = goal("show", parent_id, "--tree")
    assert {g["id"]: (g["parent_goal_id"], g["status"]) for g in tree["goals"]} == {
        parent_id: (None, "active"),
        tracker["id"]: (parent_id, "active"),
        gym["id"]: (parent_id, "completed"),
        food["id"]: (parent_id, "active"),
    }

    trace = live_directory / "ask.jsonl"
    reply = run("ask", "--trace-file", trace, QUESTION)
    assert_tool_result(trace, "get_goal_tree", parent_id, tree)
    assert_plan_answer(reply)


@pytest.mark.live
def test_message_draft_sets_distinct_date_target_and_window(run, goal):
    run(
        "goal",
        "create",
        "Log food on seven distinct dates within a 14-day window starting December 1, 2026. I will confirm each date.",
    )
    [draft] = goal("list")
    assert draft["status"] == "draft"
    progress = goal("progress", draft["id"])
    assert (
        progress["count"],
        progress["target"],
        progress["window_start"],
        progress["window_end"],
    ) == (0, 7, "2026-12-01", "2026-12-14")


@pytest.mark.live
def test_ask_explains_monday_progress_before_and_after_revision(
    live_directory, run, goal
):
    goal_id = goal("create", "--title", "Food log", "--target-distinct-dates", 7)["id"]
    monday = "2026-11-23"
    reports = [
        goal(
            "observe",
            goal_id,
            "--confirmation",
            statement,
            "--reported-date",
            monday,
            "--retry-key",
            key,
        )
        for statement, key in [
            ("I logged lunch", "lunch"),
            ("I logged dinner", "dinner"),
        ]
    ]
    ids = [r["evidence_id"] for r in reports]
    question = (
        "What progress have I made on my food log, and how do we know? "
        "Return JSON with count, target, status, and days. For each day include "
        "reported_date, evidence_ids, source, and submitted_by using the saved values."
    )
    for target in (7, 14):
        if target == 14:
            goal("revise", goal_id, "--target-distinct-dates", target)
        progress = goal("progress", goal_id)
        assert (progress["count"], progress["target"], progress["status"]) == (
            1,
            target,
            "active",
        )
        assert progress["evidence"] == reports
        trace = live_directory / f"revision-{progress['revision']}.jsonl"
        reply = run("ask", "--trace-file", trace, question)
        assert_tool_result(trace, "get_goal_progress", goal_id, progress)
        answer = json.loads(
            reply.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        assert (answer["count"], answer["target"], answer["status"]) == (
            1,
            target,
            "active",
        )
        [day] = answer["days"]
        assert day["reported_date"] == monday and sorted(day["evidence_ids"]) == ids
        assert (day["source"], day["submitted_by"]) == ("owner_confirmation", 1)


@pytest.mark.live
def test_delegated_operator_decides_when_membership_evidence_is_sufficient(
    live_directory, run, goal
):
    parent = goal("create", "--title", "Build an exercise routine")
    child = goal(
        "create",
        "--title",
        "Get a gym membership",
        "--parent",
        parent["id"],
        "--success-criteria",
        "The membership is active",
        "--measurement-plan",
        "An owner confirmation of active membership is sufficient",
    )
    goal_id = child["id"]
    operator = json.loads(run("register", "Reviewer"))
    grant = goal("grant-completion", goal_id, operator["id"])
    tour = goal(
        "observe", goal_id, "--confirmation", "I toured the gym", "--retry-key", "tour"
    )
    day_pass = goal(
        "observe", goal_id, "--reference", "receipt:day-pass", "--retry-key", "receipt"
    )
    review = (
        "Review this goal. If you judge the evidence sufficient, complete it. "
        "Otherwise tell me what’s missing."
    )
    first_trace = live_directory / "before.jsonl"
    reply = run(
        "ask", "--completion-grant", grant["id"], "--trace-file", first_trace, review
    )
    assert_tool_result(
        first_trace, "get_goal_progress", goal_id, goal("progress", goal_id)
    )
    assert all(
        json.loads(line).get("item", {}).get("tool") != "complete_goal"
        for line in first_trace.read_text(encoding="utf-8").splitlines()
    )
    assert goal("show", goal_id)["status"] == "active"
    assert goal("show", goal_id)["completion"] is None
    assert "membership" in reply.lower()
    assert any(word in reply.lower() for word in ("active", "confirm", "join"))

    confirmation = goal(
        "observe",
        goal_id,
        "--confirmation",
        "My gym membership is active.",
        "--retry-key",
        "membership",
    )
    final_trace = live_directory / "after.jsonl"
    reply = run(
        "ask", "--completion-grant", grant["id"], "--trace-file", final_trace, review
    )
    (revision,) = goal("show", goal_id, "--history")
    assert revision["evidence"] == [tour, day_pass, confirmation]
    assert confirmation["source"] == "owner_confirmation"
    assert confirmation["submitted_by"] == 1
    decision = revision["completion"]
    if decision is None:
        calls = [
            item
            for line in final_trace.read_text(encoding="utf-8").splitlines()
            if (event := json.loads(line))["type"] == "item.completed"
            and (item := event.get("item", {})).get("tool") == "complete_goal"
        ]
        pytest.fail(
            f"No delegated completion was saved. Reply {reply!r}. Completion calls {calls!r}."
        )
    assert decision["completion_grant_id"] == grant["id"]
    assert decision["recorded_by_operator_id"] == operator["id"]
    assert confirmation["evidence_id"] in decision["evidence_ids"]
    assert decision["rationale"].strip()
    assert_tool_result(final_trace, "complete_goal", goal_id, decision)
    assert goal("show", goal_id)["status"] == "completed"
    assert goal("show", parent["id"]) == parent
    assert "complet" in reply.lower() and "membership" in reply.lower()
