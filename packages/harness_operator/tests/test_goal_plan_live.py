import json
import re
import subprocess
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

QUESTION = (
    "For my Lose 20 lb goal, list each subgoal, tell me which is complete and how "
    "we know, give the current food-tracking duration, and tell me whether the "
    "parent goal is complete."
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
    subjects = {
        "gym": r"\bgym\b",
        "tracker": r"\btracker\b",
        "food": r"\bfood\b",
        "parent": r"\bparent\b|\blose 20\s*[- ]?(?:lb|pound)",
    }
    sections = {name: [] for name in subjects}
    current = None
    normalized = re.sub(r"[*_`]", "", answer.lower())
    for clause in re.split(r"\n+|(?<=[.!?;])\s+", normalized):
        matches = [
            name for name, pattern in subjects.items() if re.search(pattern, clause)
        ]
        if matches:
            # A summary mentioning two goals cannot prove either one's status.
            current = matches[0] if len(matches) == 1 else None
        if current:
            sections[current].append(clause)

    done = r"\b(?:complete[d]?|done|finished)\b"
    negated_done = r"\b(?:not|isn['’]t|hasn['’]t) (?:(?:yet|been|marked|as) )*" + done
    open_status = r"\b(?:open|active|in progress|pending|incomplete|unfinished)\b"
    gym = " ".join(sections["gym"])
    assert re.search(done, gym) and not re.search(negated_done, gym), gym
    attribution = r"(?:\b(?:owner|user|you|your)\b.{0,30}\bconfirm\w*|\bconfirm\w*.{0,30}\b(?:owner|user|you)\b)"
    unconfirmed = r"\b(?:not|never|no|without|didn['’]t) (?:(?:yet|been|any|an?|the|owner|user|your|explicit) )*confirm\w*"
    assert re.search(attribution, re.sub(unconfirmed, "", gym)), gym
    for name in ("tracker", "food", "parent"):
        section = " ".join(sections[name])
        assert re.search(open_status, section) or re.search(negated_done, section), (
            name,
            section,
        )
        assert not re.search(done, re.sub(negated_done, "", section)), (name, section)
    food = " ".join(sections["food"])
    previous_duration = r"\b(?:formerly|originally|previously|from|used to be|instead of) (?:14|fourteen)[\s-]+days?\b"
    assert re.search(
        r"\b(?:14|fourteen)[\s-]+days?\b", re.sub(previous_duration, "", food)
    ), food
    assert not re.search(
        r"\b(?:now|currently|current (?:duration|requirement))\s*(?:is|:)?\s*(?:7|seven)[\s-]+days?\b",
        food,
    ), food


@pytest.mark.parametrize(
    "gym,food",
    [
        ("Complete, never confirmed by the owner", "Open for 14 days"),
        ("Complete, you confirmed it", "Open, previously 14 days and now seven days"),
    ],
)
def test_answer_rejects_wrong_evidence_or_current_duration(gym, food):
    reply = f"Gym membership — {gym}.\nPersonal tracker — active.\nFood tracking — {food}.\nParent — still open."
    with pytest.raises(AssertionError):
        assert_plan_answer(reply)


def test_answer_accepts_historical_duration_and_open_status_wording():
    assert_plan_answer(
        "Parent — not yet marked complete.\nFood tracking — active, extended from seven days to fourteen days.\n"
        "Gym membership — completed by owner confirmation.\nPersonal tracker — still open."
    )


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
        return json.loads(run("api", "goals", *args))

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
