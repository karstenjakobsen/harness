import csv
import json
import re
import subprocess
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from harness_api import DATABASE_PATH
from harness_api.app import create_app

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


def assert_day_pass_answer(reply):
    text = " ".join(reply.casefold().replace("’", "'").replace("*", "").split())
    if re.search(
        r"\bif (?:your |the )?(?:gym )?membership is (?:currently )?active,? "
        r"(?:please )?confirm (?:it|that)(?: directly)?(?=[,.!?;]|$| and (?:i|we)\b)",
        text,
    ):
        return
    if re.search(
        r"\b(?:a )?(?:direct )?confirmation from you that (?:the |your )?"
        r"(?:gym )?membership is active would satisfy (?:the )?(?:saved )?criteria\b",
        text,
    ):
        return
    joining = r"join(?:ed|ing)?|sign(?:ed)? up|a (?:gym )?member"
    membership = rf"\b(?:membership|{joining})\b"
    missing = (
        r"\b(?:missing|need|awaiting|unclear|insufficient|not enough|not an active|"
        r"no (?:\w+ )?(?:evidence|proof|confirmation)|"
        r"next step is for (?:the owner|you) to confirm|"
        r"(?:open because|still) .*?requir\w*\b.*?\bconfirm\w*|"
        r"(?:not|neither(?: record)?|cannot|\w+n't) (?:yet )?"
        r"(?:confirm|show|establish|prove|verify|tell)\w*|please confirm)\b"
    )
    for clause in re.findall(r"[^,.!?;]+[!?]?", text):
        if re.search(rf"{missing}.*{membership}", clause):
            return
        if re.search(
            rf"{membership} (?:is |remains )?(?:still )?"
            r"(?:unconfirmed|unclear|unknown|unverified|"
            r"(?:not|hasn't been) (?:yet )?(?:confirmed|verified))\b",
            clause,
        ):
            return
        if clause.endswith("?") and re.search(
            r"\b(?:did you|have you|do you|are you|is (?:the|your)|can you|could you)\b.*"
            rf"\b(?:{joining}|active (?:gym )?membership|membership (?:is )?(?:currently )?active)\b",
            clause,
        ):
            return
    pytest.fail(
        f"Expected the reply to identify or ask about unconfirmed membership: {reply!r}"
    )


@pytest.mark.parametrize(
    "reply",
    [
        "The day pass doesn't establish that your membership is active.",
        "An active gym membership is still unconfirmed.",
        "A direct confirmation from you that the membership is active would satisfy the saved criteria.",
        "Your membership hasn’t been confirmed.",
        "The receipt shows a visit, not an active membership.",
        "What's missing is your confirmation of an active membership.",
        "I left it open because revision 1 requires the owner to confirm that the membership is active.",
        "Please confirm that your gym membership is active.",
        "Is your gym membership active?",
        "You toured the gym. Did you end up joining?",
        "I left it open. If your membership is active, confirm that directly.",
        "If your membership is active, confirm that and I can complete subgoal 2.",
        "The next step is for the owner to confirm that the gym membership is active.",
    ],
)
def test_day_pass_answer_accepts_a_missing_fact_or_a_question(reply):
    assert_day_pass_answer(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Your membership is active.",
        "The receipt confirms you have an active gym membership.",
        "Your membership is active. Please confirm the date of your visit.",
        "The receipt is missing, but your membership is active.",
        "Your membership is active. Do you have your membership card?",
        "The goal is still open. I need a copy of the day pass.",
        "If your membership is active, confirm that your day-pass receipt is valid.",
    ],
)
def test_day_pass_answer_rejects_replies_that_miss_the_gap(reply):
    with pytest.raises(pytest.fail.Exception):
        assert_day_pass_answer(reply)


@pytest.mark.live
def test_delegated_operator_decides_when_membership_evidence_is_sufficient(
    workspace, run, goal
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
    reply = run("ask", "--completion-grant", grant["id"], review)
    (first_id,) = _related_run_ids(goal("history", goal_id))
    first = json.loads(run("run", "show", first_id))
    original = [tour["evidence_id"], day_pass["evidence_id"]]
    assert _returned_progress(first, goal_id, child["revision"], original)
    assert all(call["tool"] != "complete_goal" for call in first["calls"])
    assert goal("show", goal_id)["status"] == "active"
    assert goal("show", goal_id)["completion"] is None
    assert_day_pass_answer(reply)

    confirmation = goal(
        "observe",
        goal_id,
        "--confirmation",
        "My gym membership is active.",
        "--retry-key",
        "membership",
    )
    reply = run("ask", "--completion-grant", grant["id"], review)
    history = goal("history", goal_id)
    (second_id,) = _related_run_ids(history) - {first_id}
    second = json.loads(run("run", "show", second_id))
    all_observations = [*original, confirmation["evidence_id"]]
    _assert_audited_completion(
        second,
        history,
        goal_id,
        child["revision"],
        all_observations,
        confirmation,
        operator["id"],
        grant["id"],
    )
    (revision,) = goal("show", goal_id, "--history")
    assert revision["evidence"] == [tour, day_pass, confirmation]
    assert confirmation["source"] == "owner_confirmation"
    assert confirmation["submitted_by"] == 1
    decision = revision["completion"]
    assert [
        item["decision"] for item in history["timeline"] if item["kind"] == "decision"
    ] == [decision]
    assert json.loads(run("run", "show", first_id)) == first
    assert goal("show", goal_id)["status"] == "completed"
    assert goal("show", parent["id"]) == parent
    assert "complet" in reply.lower() and "membership" in reply.lower()

    with TestClient(create_app(workspace / DATABASE_PATH)) as client:
        response = client.get(f"/goals/{goal_id}/history", params={"view": "activity"})
        response.raise_for_status()
        activity = response.json()
        discovered = []
        for run_id in _related_run_ids(activity):
            response = client.get(f"/runs/{run_id}")
            response.raise_for_status()
            discovered.append(response.json())
        first_http, second_http = sorted(
            discovered, key=lambda record: record["started_at"]
        )
        assert _returned_progress(first_http, goal_id, child["revision"], original)
        assert all(call["tool"] != "complete_goal" for call in first_http["calls"])
        _assert_audited_completion(
            second_http,
            activity,
            goal_id,
            child["revision"],
            all_observations,
            confirmation,
            operator["id"],
            grant["id"],
        )
        again = client.get(f"/runs/{first_http['id']}")
        again.raise_for_status()
        assert again.json() == first_http == first


@pytest.mark.live
def test_operator_creates_and_revises_draft_with_http_attribution(workspace, run, goal):
    operator = json.loads(run("register", "Library planner"))
    creation_grant = goal("grant-create", operator["id"])
    created_reply = run(
        "ask",
        "--definition-grant",
        creation_grant["id"],
        "Save a draft goal to join my library. Success means the library confirms my membership is active.",
    )
    with TestClient(create_app(workspace / DATABASE_PATH)) as client:

        def get(url):
            response = client.get(url)
            response.raise_for_status()
            return response.json()

        (draft,) = get("/goals")
        goal_id = draft["id"]
        assert draft["status"] == "draft" and draft["revision"] == 1
        revision_grant = goal("grant-revision", goal_id, operator["id"])
        revised_reply = run(
            "ask",
            "--definition-grant",
            revision_grant["id"],
            f"Revise goal ID {goal_id} so success requires both active membership and a successful first checkout. Save the revised criteria.",
        )

        timeline = get(f"/goals/{goal_id}/history?view=activity")["timeline"]
        original, revised = [item for item in timeline if item["kind"] == "revision"]
        assert "active" in original["definition"]["success_criteria"].lower()
        assert "membership" in original["definition"]["success_criteria"].lower()
        criteria = revised["definition"]["success_criteria"].lower()
        assert "active" in criteria and "membership" in criteria
        assert re.search(r"check(?:ed)?[ -]?out|borrow", criteria)
        assert not any(item["kind"] == "decision" for item in timeline)

        runs = set()
        for revision, entry, grant, reply in (
            (1, original, creation_grant, created_reply),
            (2, revised, revision_grant, revised_reply),
        ):
            assert entry["definition"]["revision"] == revision
            reference = entry["committing_call"]
            run_record = get(f"/runs/{reference['run_id']}")
            runs.add(run_record["id"])
            assert run_record["outcome"] == "succeeded"
            assert run_record["operator_id"] == operator["id"]
            assert run_record["definition_grant"] == grant
            (call,) = [
                call
                for call in run_record["calls"]
                if call["sequence"] == reference["sequence"]
            ]
            assert call["tool"] == grant["action"] and call["outcome"] == "returned"
            expected = {"goal_id": goal_id, "revision": revision}
            assert call["committed_revision"] == expected
            assert call["returned_goals"] == [
                expected | {"status": "draft", "observation_ids": [], "decision": None}
            ]
            assert call["target_goal_id"] == grant["goal_id"]
            assert call["target_revision"] == (1 if revision == 2 else None)
            answer = re.sub(r"[`*_]", "", reply.lower())
            assert re.search(rf"\b(?:goal(?:\s+id)?|id)[ :#]+{goal_id}\b", answer)
            assert re.search(rf"\b(?:revision|version|rev)[ .:#]+{revision}\b", answer)
            if revision == 2:
                assert "membership" in answer and re.search(
                    r"check(?:ed)?[ -]?out|borrow", answer
                )

        assert len(runs) == 2
        saved = get(f"/goals/{goal_id}")
        assert saved["status"] == "draft" and saved["revision"] == 2
        assert saved["completion"] is None


@pytest.mark.live
def test_operator_reconstructs_another_operators_revision(workspace, run, goal):
    author = json.loads(run("register", "Library planner"))
    reviewer = json.loads(run("register", "Library reviewer"))
    library = goal(
        "create",
        "--title",
        "Join the library",
        "--success-criteria",
        "Membership is active",
    )
    goal_id = library["id"]
    parent = goal("create", "--title", "Organize bills")
    other = goal("create", "--title", "File receipts", "--parent", parent["id"])
    revision_grant = goal("grant-revision", goal_id, author["id"])
    completion_grant = goal("grant-completion", other["id"], reviewer["id"])
    run(
        "ask",
        "--definition-grant",
        revision_grant["id"],
        f"Revise goal ID {goal_id} so success requires both active membership and a "
        "successful first checkout. Save the revised criteria.",
    )

    with TestClient(create_app(workspace / DATABASE_PATH)) as client:

        def get(url):
            return client.get(url).raise_for_status().json()

        goals_before = get("/goals")
        question = (
            f"Goal ID {goal_id}.\n"
            "Who changed the success criteria for this goal, what changed, and which "
            "run and call saved it?"
        )
        reply = run(
            "ask",
            "--completion-grant",
            completion_grant["id"],
            question,
        )

        history_path = f"/goals/{goal_id}/history?view=activity"
        timeline = get(history_path)["timeline"]
        original, revised = [item for item in timeline if item["kind"] == "revision"]
        assert original["definition"]["success_criteria"] == "Membership is active"
        assert revised["definition"]["revision"] == 2
        criteria = revised["definition"]["success_criteria"].lower()
        assert "active" in criteria and "membership" in criteria
        assert re.search(r"check(?:ed)?[ -]?out|borrow", criteria)

        commit = revised["committing_call"]
        author_run = get(f"/runs/{commit['run_id']}")
        assert author_run["operator_id"] == author["id"]
        assert author_run["definition_grant"] == revision_grant
        (author_call,) = [
            call
            for call in author_run["calls"]
            if call["sequence"] == commit["sequence"]
        ]
        committed = {"goal_id": goal_id, "revision": 2}
        assert author_call["tool"] == "revise_goal"
        assert author_call["committed_revision"] == committed

        reader_ids = {
            item["run_id"]
            for item in timeline
            if item.get("tool") == "get_goal_activity"
        }
        (reader_run,) = [
            record
            for run_id in reader_ids
            if (record := get(f"/runs/{run_id}"))["operator_id"] == reviewer["id"]
        ]
        assert reader_run["completion_grant_id"] == completion_grant["id"]
        assert reader_run["granted_goal_id"] == other["id"]
        activity_sequences = {
            item["sequence"]
            for item in timeline
            if item.get("tool") == "get_goal_activity"
            and item["run_id"] == reader_run["id"]
        }
        activity_read = next(
            (
                call
                for call in reader_run["calls"]
                if call["sequence"] in activity_sequences
                and call["outcome"] == "returned"
                and call["target_goal_id"] == goal_id
                and call["returned_history"]["goal_id"] == goal_id
                and any(
                    item["kind"] == "revision" and item["committing_call"] == commit
                    for item in call["returned_history"]["timeline"]
                )
            ),
            None,
        )
        assert activity_read is not None, reader_run
        run_read = next(
            (
                call
                for call in reader_run["calls"]
                if call["tool"] == "get_run"
                and call["outcome"] == "returned"
                and call["target_run_id"] == author_run["id"]
                and call["returned_history"]["run_id"] == author_run["id"]
                and any(
                    item["sequence"] == commit["sequence"]
                    and item["committed_revision"] == committed
                    for item in call["returned_history"]["calls"]
                )
            ),
            None,
        )
        assert run_read is not None, reader_run
        assert get("/goals") == goals_before
        assert all(
            not call["committed_revision"] and not call["committed_event_id"]
            for call in reader_run["calls"]
        )

    answer = re.sub(r"[`*_]", "", reply.lower())
    assert "membership" in answer and "active" in answer
    assert re.search(r"check(?:ed)?[ -]?out|borrow", answer)
    assert re.search(rf"\boperator(?:\s+id)?[ :#]+{author['id']}\b", answer)
    assert re.search(rf"\brun(?:\s+id)?[ :#]+{commit['run_id']}\b", answer)
    assert re.search(
        rf"\b(?:call(?:\s+sequence)?|sequence)[ :#]+{commit['sequence']}\b", answer
    )
    print(f"\nOwner's question\n{question}")
    print(f"\nSigned-in operator B's reply\n{reply.strip()}")
    print("\nVerified HTTP response excerpts")
    print(
        json.dumps(
            {
                history_path: {
                    "revision_1_criteria": original["definition"]["success_criteria"],
                    "revision_2_criteria": revised["definition"]["success_criteria"],
                    "committing_call": commit,
                    "activity_read": {
                        "run_id": activity_read["run_id"],
                        "sequence": activity_read["sequence"],
                    },
                },
                f"/runs/{author_run['id']}": {
                    "operator_id": author_run["operator_id"],
                    "definition_grant": author_run["definition_grant"],
                    "call": {
                        key: author_call[key]
                        for key in ("sequence", "tool", "outcome", "committed_revision")
                    },
                },
                f"/runs/{reader_run['id']}": {
                    "operator_id": reader_run["operator_id"],
                    "granted_goal_id": reader_run["granted_goal_id"],
                    "calls": [
                        {
                            key: call[key]
                            for key in (
                                "sequence",
                                "tool",
                                "outcome",
                                "returned_history",
                            )
                        }
                        for call in (activity_read, run_read)
                    ],
                },
            },
            indent=2,
        )
    )
    print("B's run made no goal changes.")


def _related_run_ids(history):
    return {item["run_id"] for item in history["timeline"] if item["kind"] == "call"}


def _returned_progress(run, goal_id, revision, observation_ids):
    return [
        call["sequence"]
        for call in run["calls"]
        if call["tool"] == "get_goal_progress"
        and call["outcome"] == "returned"
        and call["target_goal_id"] == goal_id
        and any(
            result["goal_id"] == goal_id
            and result["revision"] == revision
            and result["status"] == "active"
            and result["observation_ids"] == observation_ids
            for result in call["returned_goals"]
        )
    ]


def _assert_audited_completion(
    run,
    activity,
    goal_id,
    revision,
    observation_ids,
    confirmation,
    operator_id,
    grant_id,
):
    assert run["outcome"] == "succeeded" and run["mode"] == "delegated"
    assert run["operator_id"] == operator_id and run["completion_grant_id"] == grant_id
    (commit,) = [
        call for call in run["calls"] if call["committed_event_id"] is not None
    ]
    assert commit["tool"] == "complete_goal" and commit["outcome"] == "returned"
    assert commit["target_goal_id"] == goal_id and commit["target_revision"] == revision
    assert any(
        seq < commit["sequence"]
        for seq in _returned_progress(run, goal_id, revision, observation_ids)
    )
    (entry,) = [item for item in activity["timeline"] if item["kind"] == "decision"]
    decision = entry["decision"]
    assert (
        decision["event_id"] == commit["committed_event_id"]
        and decision["revision"] == revision
    )
    assert entry["committing_call"] == {
        "run_id": run["id"],
        "sequence": commit["sequence"],
    }
    assert (
        decision["recorded_by_operator_id"] == operator_id
        and decision["completion_grant_id"] == grant_id
    )
    assert decision["rationale"].strip()
    (returned,) = commit["returned_goals"]
    assert returned["decision"]["event_id"] == decision["event_id"]
    assert returned["decision"]["evidence_ids"] == decision["evidence_ids"]
    assert confirmation["evidence_id"] in decision["evidence_ids"]
    observations = {
        item["observation"]["evidence_id"]: item["observation"]
        for item in activity["timeline"]
        if item["kind"] == "observation"
    }
    saved = observations[confirmation["evidence_id"]]
    assert saved["submitted_by"] == confirmation["submitted_by"] == 1
    assert saved["recorded_at"] == confirmation["recorded_at"] and saved["recorded_at"]


@pytest.mark.live
def test_advisory_chess_plan_reads_versioned_skills(
    live_directory, workspace, run, goal
):
    original = goal("create", "--title", "Build a chess game in Go")
    trace = live_directory / "chess.jsonl"
    question = (
        "For my ‘Build a chess game in Go’ goal, what subgoals would you propose, "
        "and how would you verify that a move cannot leave your own king in check?"
    )
    reply = run("ask", "--trace-file", trace, question)
    with TestClient(create_app(workspace / DATABASE_PATH)) as client:

        def get(path):
            return client.get(path).raise_for_status().json()

        saved = get("/runs/1")
        assert saved["mode"] == "advisory" and saved["outcome"] == "succeeded"
        catalog = get("/skills")
        assert_tool_result(trace, "list_skills", None, {"skills": catalog})
        listed = [{"id": s["id"], "revision": s["revision"]} for s in catalog]
        assert any(
            c["tool"] == "list_skills" and c["returned_skills"] == listed
            for c in saved["calls"]
        )
        excerpts = {
            f"/runs/{saved['id']}": {
                "mode": saved["mode"],
                "outcome": saved["outcome"],
                "calls": [
                    {
                        key: call[key]
                        for key in ("sequence", "tool", "outcome", "returned_skills")
                    }
                    for call in saved["calls"]
                    if call["tool"] in ("list_skills", "read_skill")
                ],
            }
        }
        read = set()
        for call in saved["calls"]:
            if call["tool"] == "read_skill" and call["outcome"] == "returned":
                (ref,) = call["returned_skills"]
                url = f"/skills/{ref['id']}/revisions/{ref['revision']}"
                snapshot = get(url)
                assert (
                    snapshot["instructions"]
                    and snapshot["manifest"]
                    and snapshot["commit_sha"]
                )
                assert (snapshot["id"], snapshot["revision"]) == (
                    call["target_skill_id"],
                    call["target_revision"],
                )
                assert_tool_result(trace, "read_skill", None, snapshot)
                readers = get(url + "/reads")
                assert {"run_id": saved["id"], "sequence": call["sequence"]} in readers
                excerpts[url] = {
                    key: snapshot[key]
                    for key in ("source_path", "commit_sha", "content_hash")
                }
                excerpts[url]["instructions_excerpt"] = "\n\n".join(
                    snapshot["instructions"].split("\n\n", 2)[:2]
                )
                excerpts[url + "/reads"] = readers
                read.add((ref["id"], ref["revision"]))
        current = {item["id"]: item["revision"] for item in catalog}
        assert {
            (skill_id, current[skill_id]) for skill_id in ("chess-rules", "go-testing")
        } <= read
        tree = goal("show", original["id"], "--tree")
        (root,) = tree["goals"]
        assert (root["id"], root["revision"]) == (original["id"], original["revision"])

    assert_chess_plan_answer(reply)
    print(f"\nOwner's question\n{question}")
    print(f"\nSigned-in operator's reply\n{reply.strip()}")
    print("\nVerified HTTP response excerpts")
    print(json.dumps(excerpts, indent=2, ensure_ascii=False))
    print(
        f"Goal {root['id']} after the run: revision {root['revision']}, {len(tree['goals']) - 1} descendants."
    )


def assert_chess_plan_answer(reply):
    answer = reply.lower()
    assert re.search(r"subgoal|milestone|\bplan\b|^\s*1[.)]", answer, re.MULTILINE), (
        reply
    )
    assert "king" in answer and "check" in answer, reply
    fen = re.search(r"\b(?:[prnbqk1-8]+/){7}[prnbqk1-8]+ [wb]\b", answer)
    assert fen or len(set(re.findall(r"[a-h][1-8]", answer))) >= 3, reply
    assert re.search(r"testing\.t|t\.run\(|go test|table.driven", answer), reply
    # Read each candidate with its own expectation. A verdict from the next
    # row of a Go table or Markdown table belongs to a different move.
    coordinates = answer.translate(str.maketrans("", "", '"`'))
    moves = list(
        re.finditer(
            r"([a-h][1-8])[ \t]*(?:[-–—→>,]+|to)?[ \t]*([a-h][1-8])", coordinates
        )
    )
    seed_position = "k3r3/8/8/8/8/8/4r3/4k3 w" in answer or (
        "rook" in answer
        and all(square in answer for square in ("e1", "e2", "e8", "a8"))
    )
    for index, move in enumerate(moves):
        start, end = move.groups()
        if (
            seed_position
            and start == "e2"
            and end in {"e3", "e4", "e5", "e6", "e7", "e8"}
        ):
            continue  # The rook keeps blocking the e-file or captures the attacker.
        stop = moves[index + 1].start() if index + 1 < len(moves) else len(coordinates)
        after = coordinates[move.end() : stop][:150]
        previous = moves[index - 1].end() if index else 0
        before = coordinates[previous : move.start()].rsplit("\n", 1)[-1]
        if re.search(
            r"\b(false|illegal|reject(?:ed)?|absent)\b|must not|should not|wanterr:\s*true",
            after,
        ):
            return
        if re.search(r"\b(illegal|reject)[:\s`*]*$", before):
            return
    raise AssertionError(
        f"Expected the Go test to reject a move exposing the moving king: {reply}"
    )


@pytest.mark.parametrize(
    ("off_file", "still_blocking"), [("legal", "illegal"), ("true", "false")]
)
def test_chess_answer_rejects_reversed_expected_results(off_file, still_blocking):
    reply = (
        "Proposed subgoals: represent positions, then generate legal moves.\n"
        "Test king safety in check with a table-driven Go test.\n"
        "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1\n"
        f"| e2f2 | {off_file} |\n| e2e3 | {still_blocking} |"
    )
    with pytest.raises(AssertionError):
        assert_chess_plan_answer(reply)


@pytest.mark.parametrize("case", ['{"e2", "f2", false}', "e2 → f2 must be rejected"])
def test_chess_answer_accepts_a_full_position_and_one_illegal_move(case):
    assert_chess_plan_answer(
        "Proposed subgoals: represent the board and generate legal moves.\n"
        "For king safety, use a table-driven Go test for check.\n"
        f"k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1\n{case}"
    )


@pytest.mark.live
def test_delegated_operator_saves_subgoals(workspace, run, goal):
    parent = goal("create", "--title", "Build a chess game in Go")
    parent_id = parent["id"]
    operator = json.loads(run("register", "Chess planner"))
    question = (
        "Break my “Build a chess game in Go” goal into subgoals and save them for review. "
        "For each subgoal, say how we could tell it was done."
    )
    before = {g["id"] for g in goal("list")}
    proposal = run("ask", question)
    assert re.search(
        r"subgoal|milestone|plan|^\s*1[.)]", proposal, re.IGNORECASE | re.MULTILINE
    ), proposal
    assert re.search(r"board|piece|move|position|checkmate", proposal, re.IGNORECASE), (
        proposal
    )
    assert re.search(
        r"test|verif|done|pass|acceptance|demonstrat", proposal, re.IGNORECASE
    ), proposal
    assert {g["id"] for g in goal("list")} == before == {parent_id}
    assert goal("show", parent_id, "--tree")["goals"] == [parent]
    grant = goal("grant-subgoals", parent_id, operator["id"])
    reply = run("ask", "--definition-grant", grant["id"], question)
    tree = goal("show", parent_id, "--tree")["goals"]
    children = {g["id"]: g for g in tree if g["parent_goal_id"] == parent_id}
    assert len(children) >= 2 and len(tree) == 1 + len(children)
    criteria = " ".join(
        child["success_criteria"] for child in children.values()
    ).casefold()
    assert re.search(
        r"\b(?:saved|created|added|recorded|stored|drafts?)\b", reply, re.IGNORECASE
    ), reply
    assert any(
        term in criteria and term in reply.casefold()
        for term in ("board", "piece", "move", "position", "checkmate", "turn")
    )
    assert {g["id"] for g in goal("list")} - before == children.keys()

    with TestClient(create_app(workspace / DATABASE_PATH)) as client:

        def get(path):
            return client.get(path).raise_for_status().json()

        parent_url = f"/goals/{parent_id}/history?view=activity"
        timeline = get(parent_url)["timeline"]
        planning = [
            entry
            for entry in timeline
            if entry.get("tool") == "create_subgoal" and entry["outcome"] == "returned"
        ]
        (run_id,) = {entry["run_id"] for entry in planning}
        record = get(f"/runs/{run_id}")
        assert (
            record["definition_grant"] == grant
            and record["operator_id"] == operator["id"]
        )
        assert record["outcome"] == "succeeded" and record["mode"] == "delegated"
        commits = [c for c in record["calls"] if c["committed_revision"]]
        assert len(commits) == len(children)
        assert {c["committed_revision"]["goal_id"] for c in commits} == children.keys()
        assert get(f"/goals/{parent_id}") == parent
        print(
            f"\nOwner request\n{question}\n\nAdvisory reply (zero children saved)\n{proposal.strip()}"
        )
        print(f"\nDelegated reply\n{reply.strip()}\n\n{parent_url} → /runs/{run_id}")
        print(
            f"Operator {record['operator_id']}, grant {grant['id']}, parent {parent_id} at revision {parent['revision']} ({parent['status']})"
        )
        for call in commits:
            child_id = call["committed_revision"]["goal_id"]
            child = children[child_id]
            assert call["tool"] == "create_subgoal" and call["outcome"] == "returned"
            assert (call["target_goal_id"], call["target_revision"]) == (
                parent_id,
                parent["revision"],
            )
            assert any(
                entry["sequence"] == call["sequence"]
                and entry["relationship"] == "requested"
                for entry in planning
            )
            assert call["committed_revision"] == {"goal_id": child_id, "revision": 1}
            assert call["returned_goals"] == [
                call["committed_revision"]
                | {"status": "draft", "observation_ids": [], "decision": None}
            ]
            assert (child["status"], child["revision"]) == ("draft", 1)
            assert child["success_criteria"].strip()
            assert get(f"/goals/{child_id}") == child
            child_url = f"/goals/{child_id}/history?view=activity"
            (revision,) = [
                e for e in get(child_url)["timeline"] if e["kind"] == "revision"
            ]
            assert revision["definition"]["revision"] == 1
            assert revision["committing_call"] == {
                "run_id": run_id,
                "sequence": call["sequence"],
            }
            print(
                f"Call {call['sequence']} → {child_url} → revision 1, draft: {child['title']}\n  {child['success_criteria']}"
            )
        for call in record["calls"]:
            if (
                call["tool"] in ("list_skills", "read_skill")
                and call["outcome"] == "returned"
            ):
                print(
                    f"Call {call['sequence']} {call['tool']} → {call['returned_skills']}"
                )
