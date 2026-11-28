"""Slice 16 acceptance through public model operations and real SQLite."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from harness_api import (
    GoalAPI,
    GoalValidationError,
    OperatorAPI,
    UserAPI,
    WorkAPI,
    WorkAuthorizationError,
    WorkConflictError,
    WorkNotFoundError,
    WorkspaceInput,
    WorkStorageError,
    WorkValidationError,
)

EMPTY = WorkspaceInput(source_path=None, base_sha=None)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    goals, work = GoalAPI(path), WorkAPI(path)
    parent = goals.create_goal("Parent", status="active")
    goal = goals.create_goal(
        "Library deliverable", parent_goal_id=parent["id"], status="active"
    )
    operator = OperatorAPI(path).register_operator("Builder")
    grant = work.grant_delegation(goal["id"], operator["id"])
    run = goals.start_run(delegation_grant_id=grant["id"])
    return path, goals, work, goal, grant, run


def start_call(goals, run, goal, revision=1, tool="delegate_work"):
    return goals.start_tool_call(
        run["id"], tool, target_goal_id=goal["id"], target_revision=revision
    )


def delegate(
    work,
    goal,
    call,
    key="deliverable",
    brief="Write a report.",
    workspace_input=EMPTY,
    revision=1,
):
    return work.delegate_work(
        goal["id"], revision, brief, workspace_input, key, call=call
    )


@pytest.mark.parametrize(
    "source",
    [EMPTY, WorkspaceInput(source_path="/unavailable/repository", base_sha="a" * 40)],
)
def test_delegate_reopen_and_finish_preserves_attribution_and_zero_attempts(
    workspace, source
):
    path, goals, work, goal, grant, run = workspace
    before = goals.get_goal(goal["id"])
    parent = goals.get_goal(goal["parent_goal_id"])
    call = start_call(goals, run, goal)
    item = delegate(work, goal, call, workspace_input=source)
    assert item["delegation_grant_id"] == grant["id"]
    assert item["operator_id"] == grant["operator_id"]
    assert item["goal_id"] == goal["id"] and item["goal_revision"] == 1
    assert item["committing_call"] == call and item["brief"] == "Write a report."
    assert (
        item["source_path"] == source["source_path"]
        and item["base_sha"] == source["base_sha"]
    )
    reopened = WorkAPI(path)
    assert reopened.get_work_item(item["id"]) == item
    assert reopened.list_work_items(goal["id"]) == [item]
    assert reopened.list_attempts(item["id"]) == []
    assert reopened.get_delegation_grant(grant["id"]) == grant
    history = GoalAPI(path).get_run(run["id"])
    assert history["delegation_grant_id"] == grant["id"]
    assert (
        history["operator_id"] == grant["operator_id"]
        and history["mode"] == "delegated"
    )
    assert history["calls"][0]["committed_work_item_id"] == item["id"]
    assert history["calls"][0]["outcome"] == "unfinished"
    assert history["calls"][0]["returned_goals"] is None
    assert goals.get_goal(goal["id"]) == before
    assert goals.get_goal(parent["id"]) == parent
    goals.finish_tool_call(call, "returned", returned_work_item_id=item["id"])
    goals.finish_run(run["id"], "succeeded")
    assert goals.get_run(run["id"])["calls"][0]["outcome"] == "returned"
    assert all(
        "brief" not in c and "workspace_input" not in c for c in history["calls"]
    )


def test_one_commit_per_call_and_lost_reply_retrieval(workspace):
    path, goals, work, goal, _grant, run = workspace
    first_call = start_call(goals, run, goal)
    item = delegate(work, goal, first_call)
    with pytest.raises(WorkConflictError, match="already saved"):
        delegate(work, goal, first_call, key="different-key")
    assert WorkAPI(path).list_work_items(goal["id"]) == [item]
    # The reply was never recorded. Recovery gets a new call, not a second write.
    goals, work = GoalAPI(path), WorkAPI(path)
    retry_call = start_call(goals, run, goal)
    assert delegate(work, goal, retry_call) == item
    calls = goals.get_run(run["id"])["calls"]
    assert (
        calls[0]["committed_work_item_id"]
        == calls[1]["retrieved_work_item_id"]
        == item["id"]
    )
    assert (
        calls[0]["retrieved_work_item_id"] is calls[1]["committed_work_item_id"] is None
    )
    assert calls[0]["outcome"] == "unfinished"
    goals.finish_tool_call(retry_call, "returned", returned_work_item_id=item["id"])
    # Rejected reuse did not reserve its key.
    other = delegate(work, goal, start_call(goals, run, goal), key="different-key")
    assert other["id"] != item["id"]
    assert item["committing_call"] == first_call


@pytest.mark.parametrize("changed", ["brief", "input", "revision"])
def test_retry_key_conflicts_leave_original_item(workspace, changed):
    path, goals, work, goal, _grant, run = workspace
    item = delegate(work, goal, start_call(goals, run, goal))
    kwargs = {}
    if changed == "brief":
        kwargs["brief"] = "Changed brief"
    elif changed == "input":
        kwargs["workspace_input"] = WorkspaceInput(
            source_path="/other", base_sha="b" * 40
        )
    else:
        goals.update_goal(goal["id"], title="Changed revision")
        kwargs["revision"] = 2
    with pytest.raises(WorkConflictError, match="different work inputs"):
        delegate(
            work,
            goal,
            start_call(goals, run, goal, revision=kwargs.get("revision", 1)),
            **kwargs,
        )
    assert WorkAPI(path).list_work_items(goal["id"]) == [item]
    second = delegate(
        work,
        goal,
        start_call(goals, run, goal, revision=kwargs.get("revision", 1)),
        key="new",
        **kwargs,
    )
    assert second["id"] != item["id"]


@pytest.mark.parametrize(
    "case",
    [
        "advisory",
        "assignment",
        "definition",
        "completion",
        "other_goal",
        "parent_grant",
        "missing_call",
        "wrong_tool",
        "wrong_target",
        "wrong_revision",
        "finished_call",
        "finished_run",
        "foreign_run",
    ],
)
def test_authority_denials_preserve_history(workspace, case):
    path, goals, work, goal, grant, run = workspace
    if case in ("advisory", "assignment"):
        if case == "assignment":
            # Assignment-only setup has no public creation operation.
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "INSERT INTO goal_assignments(goal_id,operator_id) VALUES (?,?)",
                    (goal["id"], grant["operator_id"]),
                )
        run = goals.start_run()
    elif case == "definition":
        definition = goals.grant_definition(
            "revise_goal", grant["operator_id"], goal_id=goal["id"]
        )
        run = goals.start_run(definition_grant_id=definition["id"])
    elif case == "completion":
        completion = goals.grant_completion(goal["id"], grant["operator_id"])
        run = goals.start_run(completion["id"])
    elif case in ("other_goal", "parent_grant"):
        target = (
            goals.create_goal("Other")
            if case == "other_goal"
            else goals.get_goal(goal["parent_goal_id"])
        )
        another = work.grant_delegation(target["id"], grant["operator_id"])
        run = goals.start_run(delegation_grant_id=another["id"])
    call = start_call(
        goals,
        run,
        goal,
        revision=2 if case == "wrong_revision" else 1,
        tool="get_goal_progress" if case == "wrong_tool" else "delegate_work",
    )
    if case == "missing_call":
        call = {"run_id": run["id"], "sequence": 999}
    elif case == "wrong_target":
        call = start_call(goals, run, goals.get_goal(goal["parent_goal_id"]))
    elif case == "finished_call":
        goals.finish_tool_call(call, "denied")
    elif case == "finished_run":
        goals.finish_run(run["id"], "succeeded")
    elif case == "foreign_run":
        # There is no public API for starting a foreign owner's run. Change only
        # the fixture's ownership to exercise the public write's scope check.
        user = UserAPI(path).create_user("foreign")
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "UPDATE operator_runs SET owner_user_id = ? WHERE id = ?",
                (user["id"], run["id"]),
            )
    prior = goals.get_goal_history(goal["id"])
    with pytest.raises(WorkAuthorizationError):
        delegate(work, goal, call)
    assert work.list_work_items(goal["id"]) == []
    assert goals.get_goal_history(goal["id"]) == prior
    if case not in ("foreign_run", "missing_call", "finished_call"):
        goals.finish_tool_call(call, "denied")
        saved = goals.get_run(run["id"])["calls"][-1]
        assert (
            saved["outcome"] == "denied" and saved.get("committed_work_item_id") is None
        )


def test_withdraw_regrant_denies_old_session_and_scopes_retry_keys(workspace):
    _path, goals, work, goal, grant, run = workspace
    item = delegate(work, goal, start_call(goals, run, goal))
    withdrawn = work.withdraw_delegation(grant["id"])
    assert withdrawn["withdrawn_at"] is not None
    with pytest.raises(GoalValidationError):
        goals.start_run(delegation_grant_id=grant["id"])
    replacement = work.grant_delegation(goal["id"], grant["operator_id"])
    for key in ("deliverable", "new"):
        with pytest.raises(WorkAuthorizationError):
            delegate(work, goal, start_call(goals, run, goal), key=key)
    fresh_run = goals.start_run(delegation_grant_id=replacement["id"])
    fresh = delegate(work, goal, start_call(goals, fresh_run, goal))
    assert (
        fresh["id"] != item["id"] and fresh["delegation_grant_id"] == replacement["id"]
    )
    assert work.get_work_item(item["id"]) == item


@pytest.mark.parametrize(
    "change", [None, "withdrawn", "regranted", "unregistered", "finished"]
)
def test_run_write_action_reports_live_delegation_authority(workspace, change):
    path, goals, work, goal, grant, run = workspace
    if change in ("withdrawn", "regranted"):
        work.withdraw_delegation(grant["id"])
        if change == "regranted":
            work.grant_delegation(goal["id"], grant["operator_id"])
    elif change == "unregistered":
        OperatorAPI(path).unregister_operator(grant["operator_id"])
    elif change == "finished":
        goals.finish_run(run["id"], "succeeded")
    assert goals.get_run_write_action(run["id"]) == (
        "delegate_work" if change is None else None
    )


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("revision", WorkConflictError),
        ("completed", WorkConflictError),
        ("revoked", WorkConflictError),
        ("deleted", WorkAuthorizationError),
        ("unregistered", WorkAuthorizationError),
    ],
)
def test_current_revision_and_lifecycle_checked_even_on_replay(
    workspace, change, error
):
    path, goals, work, goal, grant, run = workspace
    item = delegate(work, goal, start_call(goals, run, goal))
    if change == "revision":
        goals.update_goal(goal["id"], title="New revision")
    elif change == "completed":
        goals.complete_goal(goal["id"], 1, confirmation="Verified")
    elif change == "revoked":
        # No owner operation currently exposes revocation. Seed only this
        # lifecycle state, then exercise delegation through its public model.
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "UPDATE goals SET status = 'revoked' WHERE id = ?", (goal["id"],)
            )
    elif change == "deleted":
        goals.delete_goal(goal["id"])
    else:
        OperatorAPI(path).unregister_operator(grant["operator_id"])
    before = goals.get_run(run["id"])["calls"][0]
    for key in ("deliverable", "fresh-key"):
        with pytest.raises(error):
            delegate(work, goal, start_call(goals, run, goal), key=key)
    assert WorkAPI(path).get_work_item(item["id"]) == item
    assert goals.get_run(run["id"])["calls"][0] == before
    assert work.list_attempts(item["id"]) == []


def test_rollback_after_item_insert_preserves_history_and_retry_key(workspace):
    path, goals, work, goal, _grant, run = workspace
    call = start_call(goals, run, goal)
    before = goals.get_run(run["id"])
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TRIGGER fail_link BEFORE INSERT ON run_call_work_items BEGIN SELECT RAISE(ABORT, 'failed link'); END"
        )
    with pytest.raises(WorkStorageError):
        delegate(work, goal, call)
    work = WorkAPI(path)
    assert work.list_work_items(goal["id"]) == []
    assert goals.get_run(run["id"]) == before
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TRIGGER fail_link")
    item = delegate(work, goal, call)
    assert item["committing_call"] == call
    assert work.list_work_items(goal["id"]) == [item]


def test_concurrent_identical_requests_commit_one_item(workspace):
    path, goals, work, goal, _grant, run = workspace
    calls = [start_call(goals, run, goal) for _ in range(2)]
    barrier = Barrier(2)

    def submit(call):
        api = WorkAPI(path)
        barrier.wait(timeout=10)
        return delegate(api, goal, call)

    with ThreadPoolExecutor(max_workers=2) as pool:
        items = list(pool.map(submit, calls))
    assert items[0] == items[1]
    assert work.list_work_items(goal["id"]) == items[:1]
    saved = goals.get_run(run["id"])["calls"]
    assert sum(c["committed_work_item_id"] is not None for c in saved) == 1
    assert sum(c["retrieved_work_item_id"] is not None for c in saved) == 1
    assert work.list_attempts(items[0]["id"]) == []


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"source_path": "relative", "base_sha": "a" * 40},
        {"source_path": "/requested", "base_sha": None},
        {"source_path": None, "base_sha": "a" * 40},
        {"source_path": "/requested", "base_sha": "abc"},
        {"source_path": "/bad\x00path", "base_sha": "a" * 40},
    ],
)
def test_workspace_input_validation(workspace, value):
    _path, goals, work, goal, _grant, run = workspace
    with pytest.raises(WorkValidationError):
        delegate(work, goal, start_call(goals, run, goal), workspace_input=value)
    assert work.list_work_items(goal["id"]) == []


@pytest.mark.parametrize("key", ["", " ", "bad\x00key", None])
def test_retry_key_validation(workspace, key):
    _path, goals, work, goal, _grant, run = workspace
    with pytest.raises(WorkValidationError):
        delegate(work, goal, start_call(goals, run, goal), key=key)
    assert work.list_work_items(goal["id"]) == []


def test_foreign_grants_and_single_binding(workspace):
    path, goals, work, goal, grant, run = workspace
    user = UserAPI(path).create_user("other")
    operator = OperatorAPI(path).register_operator("Foreign", owner_user_id=user["id"])
    with pytest.raises(WorkValidationError):
        work.grant_delegation(goal["id"], operator["id"])
    definition = goals.grant_definition(
        "revise_goal", grant["operator_id"], goal_id=goal["id"]
    )
    with pytest.raises(GoalValidationError):
        goals.start_run(
            definition_grant_id=definition["id"], delegation_grant_id=grant["id"]
        )
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "UPDATE goals SET owner_user_id = ? WHERE id = ?", (user["id"], goal["id"])
        )
    with pytest.raises(WorkNotFoundError):
        work.grant_delegation(goal["id"], grant["operator_id"])
    with pytest.raises(WorkAuthorizationError):
        delegate(work, goal, start_call(goals, run, goal))


def test_history_snapshot_retains_work_result_after_reply_finishes(workspace):
    _path, goals, work, goal, _grant, run = workspace
    original = start_call(goals, run, goal)
    item = delegate(work, goal, original)
    reader = goals.start_run()
    call = goals.start_tool_call(reader["id"], "get_run", target_run_id=run["id"])
    history = goals.get_run(run["id"], call=call)
    goals.finish_tool_call(call, "returned", history_result=history)
    goals.finish_tool_call(original, "returned", returned_work_item_id=item["id"])
    snapshot = goals.get_run(reader["id"])["calls"][0]["returned_history"]
    assert snapshot["calls"][0]["committed_work_item_id"] == item["id"]
    assert snapshot["calls"][0]["outcome"] == "unfinished"
    with pytest.raises(GoalValidationError):
        goals.finish_tool_call(
            start_call(goals, run, goal), "returned", returned_work_item_id=item["id"]
        )
