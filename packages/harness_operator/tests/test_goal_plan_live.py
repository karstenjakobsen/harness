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


def assert_tree_call(trace, expected_tree):
    parent_id = expected_tree["root_id"]
    for line in trace.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        item = event.get("item", {})
        if (
            event["type"] == "item.completed"
            and item.get("type") == "mcp_tool_call"
            and item.get("server") == "harness_mcp"
            and item.get("tool") == "get_goal_tree"
            and item.get("arguments") == {"goal_id": parent_id}
            and item.get("status") == "completed"
            and not item.get("error")
        ):
            result = item.get("result")
            if result and not (result.get("isError") or result.get("is_error")):
                tree = result.get("structuredContent") or result.get(
                    "structured_content"
                )
                if tree is None:
                    tree = json.loads(result["content"][0]["text"])
                assert tree == expected_tree
                return
    pytest.fail(f"No successful get_goal_tree call for parent {parent_id} in {trace}")


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
def workspace(tmp_path):
    with TemporaryDirectory(dir=tmp_path, prefix="workspace-") as directory:
        yield Path(directory)


@pytest.mark.live
def test_ask_explains_saved_plan_through_mcp(tmp_path, workspace):
    operator = Path(sysconfig.get_path("scripts")) / "operator"

    def run(*args):
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

    def goal(*args):
        return json.loads(run("goal", *args))

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

    trace = tmp_path / "ask.jsonl"
    reply = run("ask", "--trace-file", trace, QUESTION)
    assert_tree_call(trace, tree)
    assert_plan_answer(reply)
