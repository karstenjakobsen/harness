import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from harness_api import (
    GoalAPI,
    GoalConflictError,
    GoalNotFoundError,
    GoalStorageError,
    GoalValidationError,
    OperatorAPI,
    UserAPI,
)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    operator_id = OperatorAPI(path).register_operator("Planner")["id"]
    return path, api, operator_id


def start_revision_call(api, run_id, goal_id, revision=1):
    return api.start_tool_call(
        run_id, "revise_goal", target_goal_id=goal_id, target_revision=revision
    )


def test_create_retries_retrieve_revision_one_and_each_call_can_commit_once(workspace):
    path, api, operator_id = workspace
    grant = api.grant_definition("create_goal", operator_id)
    run_id = api.start_run(definition_grant_id=grant["id"])["id"]

    def attempt():
        return api.start_tool_call(run_id, "create_goal")

    first_call = attempt()
    first = api.create_delegated_goal(" Library ", call=first_call, retry_key="library")
    assert first == {"goal_id": 1, "revision": 1, "status": "draft"}
    assert api.get_goal(1)["parent_goal_id"] is None
    with pytest.raises(GoalConflictError, match="already saved"):
        api.create_delegated_goal("Another goal", call=first_call, retry_key="new")
    assert len(api.list_goals()) == 1
    api.update_goal(1, success_criteria="Membership and checkout")
    api.complete_goal(1, 2, confirmation="Owner verified both")

    retry = attempt()
    assert (
        api.create_delegated_goal("Library", call=retry, retry_key="library") == first
    )
    assert api.get_goal(1)["status"] == "completed"
    with pytest.raises(GoalConflictError, match="different goal definition"):
        api.create_delegated_goal("Different", call=attempt(), retry_key="library")
    another = api.create_delegated_goal(
        "Second goal", call=attempt(), retry_key="new", status="active"
    )
    assert another == {"goal_id": 2, "revision": 1, "status": "active"}

    reopened = GoalAPI(path)
    saved = reopened.get_run(run_id)
    assert saved["definition_grant"] == grant and saved["operator_id"] == operator_id
    original, retrieved, conflict, second = saved["calls"]
    reference = {"goal_id": 1, "revision": 1}
    assert (
        original["committed_revision"] == retrieved["retrieved_revision"] == reference
    )
    assert original["outcome"] == "unfinished" and original["returned_goals"] is None
    assert original["retrieved_revision"] is retrieved["committed_revision"] is None
    assert conflict["committed_revision"] is None
    assert second["committed_revision"] == {"goal_id": 2, "revision": 1}
    timeline = reopened.get_goal_activity(1)["timeline"]
    assert [
        entry["committing_call"] for entry in timeline if entry["kind"] == "revision"
    ] == [first_call, None]
    assert [entry["relationship"] for entry in timeline if entry["kind"] == "call"] == [
        "creation_result",
        "creation_result",
    ]

    api.delete_goal(1)
    with pytest.raises(GoalNotFoundError):
        api.create_delegated_goal("Library", call=attempt(), retry_key="library")
    assert [goal["id"] for goal in api.list_goals()] == [2]


def test_revise_checks_revision_in_transaction_and_preserves_evidence(workspace):
    path, api, operator_id = workspace
    goal_id = api.create_goal(
        "Library", desired_outcome="Join library", measurement_plan="Ask owner"
    )["id"]
    report = api.record_observation(
        goal_id, confirmation="Started application", retry_key="report"
    )
    grant = api.grant_definition("revise_goal", operator_id, goal_id=goal_id)
    run_id = api.start_run(definition_grant_id=grant["id"])["id"]
    calls = [start_revision_call(api, run_id, goal_id) for _ in range(2)]

    def revise(call):
        return GoalAPI(path, local_owner=False).revise_delegated_goal(
            goal_id,
            1,
            call=call,
            success_criteria="Membership and checkout",
            measurement_plan=None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(revise, call) for call in calls]
    failures = [future.exception() for future in futures]
    assert sum(failure is None for failure in failures) == 1
    (failure,) = [failure for failure in failures if failure is not None]
    assert isinstance(failure, GoalConflictError) and "Stale revision" in str(failure)
    winner = calls[failures.index(None)]
    assert futures[failures.index(None)].result() == {
        "goal_id": goal_id,
        "revision": 2,
        "status": "draft",
    }
    original, current = api.get_goal_history(goal_id)
    assert (
        original["evidence"] == [report] and original["measurement_plan"] == "Ask owner"
    )
    assert (
        current["desired_outcome"] == "Join library"
        and current["measurement_plan"] is None
    )
    assert current["success_criteria"] == "Membership and checkout"
    assert current["completion"] is None

    no_op = start_revision_call(api, run_id, goal_id, revision=2)
    assert api.revise_delegated_goal(goal_id, 2, call=no_op)["revision"] == 2
    call_records = api.get_run(run_id)["calls"]
    assert [
        call["sequence"] for call in call_records if call["committed_revision"]
    ] == [winner["sequence"]]
    assert [
        entry["committing_call"]
        for entry in api.get_goal_activity(goal_id)["timeline"]
        if entry["kind"] == "revision"
    ] == [None, winner]
    assert api.get_goal_history(goal_id) == [original, current]


@pytest.mark.parametrize("action", ["create_goal", "revise_goal"])
def test_withdrawal_regrant_and_unregister_leave_old_runs_denied(workspace, action):
    path, api, operator_id = workspace
    goal_id = api.create_goal("Library")["id"]
    scope = {"goal_id": goal_id} if action == "revise_goal" else {}
    grant = api.grant_definition(action, operator_id, **scope)
    run_id = api.start_run(definition_grant_id=grant["id"])["id"]

    def write(run, first=False):
        if action == "create_goal":
            return api.create_delegated_goal(
                "New goal", retry_key="first", call=api.start_tool_call(run, action)
            )
        return api.revise_delegated_goal(
            goal_id,
            1,
            call=start_revision_call(api, run, goal_id),
            **({} if first else {"title": "Library membership"}),
        )

    write(run_id, first=True)
    snapshot = api.list_goals()
    api.withdraw_definition_grant(grant["id"])
    with pytest.raises(GoalValidationError, match="inactive"):
        write(run_id)
    replacement = api.grant_definition(action, operator_id, **scope)
    assert replacement["id"] != grant["id"]
    with pytest.raises(GoalValidationError, match="inactive"):
        write(run_id)
    assert api.list_goals() == snapshot
    fresh = api.start_run(definition_grant_id=replacement["id"])["id"]
    write(fresh)
    OperatorAPI(path).unregister_operator(operator_id)
    with pytest.raises(GoalValidationError, match="inactive"):
        write(fresh)
    assert api.get_run(run_id)["definition_grant"] == grant
    assert api.get_run(fresh)["definition_grant"] == replacement


def test_definition_grants_and_calls_require_the_owner_action_and_target(workspace):
    path, api, operator_id = workspace
    goal_id = api.create_goal("Library")["id"]
    other_goal = api.create_goal("Another goal")["id"]
    user_id = UserAPI(path).create_user("another")["id"]
    foreign_operator = OperatorAPI(path).register_operator(
        "Other", owner_user_id=user_id
    )["id"]
    with pytest.raises(GoalValidationError, match="owned by"):
        api.grant_definition("create_goal", foreign_operator)
    with pytest.raises(GoalValidationError, match="workspace owner"):
        GoalAPI(path, local_owner=False).grant_definition(
            "revise_goal", operator_id, goal_id=goal_id
        )
    with pytest.raises(GoalValidationError):
        api.grant_definition("create_goal", operator_id, goal_id=goal_id)
    grant = api.grant_definition("revise_goal", operator_id, goal_id=goal_id)
    run_id = api.start_run(definition_grant_id=grant["id"])["id"]
    with pytest.raises(GoalValidationError, match="does not cover"):
        api.revise_delegated_goal(
            other_goal, 1, call=start_revision_call(api, run_id, other_goal)
        )
    with pytest.raises(GoalValidationError, match="does not cover"):
        api.create_delegated_goal(
            "Another",
            retry_key="another",
            call=api.start_tool_call(run_id, "create_goal"),
        )
    with pytest.raises(GoalValidationError, match="does not match"):
        api.revise_delegated_goal(
            goal_id, 2, call=start_revision_call(api, run_id, goal_id)
        )
    with pytest.raises(GoalValidationError, match="unavailable"):
        api.revise_delegated_goal(goal_id, 1, call={"run_id": run_id, "sequence": 99})
    advisory = api.start_run()["id"]
    with pytest.raises(GoalValidationError, match="does not match"):
        api.revise_delegated_goal(
            goal_id, 1, call=start_revision_call(api, advisory, goal_id)
        )
    api.complete_goal(goal_id, 1, confirmation="Already verified")
    before = api.get_goal_history(goal_id)
    with pytest.raises(GoalConflictError, match="completed goal"):
        api.revise_delegated_goal(
            goal_id, 1, call=start_revision_call(api, run_id, goal_id), title="Changed"
        )
    assert api.get_goal_history(goal_id) == before
    api.delete_goal(goal_id)
    with pytest.raises(GoalValidationError, match="inactive"):
        api.revise_delegated_goal(
            goal_id, 1, call=start_revision_call(api, run_id, goal_id)
        )


@pytest.mark.parametrize("action", ["create_goal", "create_subgoal", "revise_goal"])
def test_failed_revision_link_rolls_back_definition_and_retry_record(workspace, action):
    path, api, operator_id = workspace
    goal_id = api.create_goal("Library")["id"]
    scope = {"goal_id": goal_id} if action != "create_goal" else {}
    grant = api.grant_definition(action, operator_id, **scope)
    run_id = api.start_run(definition_grant_id=grant["id"])["id"]
    call = api.start_tool_call(
        run_id,
        action,
        target_goal_id=scope.get("goal_id"),
        target_revision=1 if scope else None,
    )

    def write():
        if action == "create_goal":
            return api.create_delegated_goal("Other", retry_key="new", call=call)
        if action == "create_subgoal":
            return api.create_delegated_subgoal(
                goal_id,
                1,
                "Child",
                success_criteria="Owner confirms membership",
                retry_key="new",
                call=call,
            )
        return api.revise_delegated_goal(goal_id, 1, call=call, title="Revised")

    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("""
            CREATE TRIGGER fail_link BEFORE INSERT ON run_call_revisions
            BEGIN SELECT RAISE(ABORT, 'forced link failure'); END;
        """)
        with pytest.raises(GoalStorageError):
            write()
        reopened = GoalAPI(path)
        assert len(reopened.list_goals()) == 1
        assert reopened.get_goal(goal_id)["revision"] == 1
        (attempt,) = reopened.get_run(run_id)["calls"]
        assert (
            attempt["outcome"] == "unfinished" and attempt["committed_revision"] is None
        )
        db.execute("DROP TRIGGER fail_link")
    result = write()
    assert reopened.get_run(run_id)["calls"][0]["committed_revision"] == {
        "goal_id": result["goal_id"],
        "revision": result["revision"],
    }


@pytest.fixture
def planning(workspace):
    path, api, operator_id = workspace
    parent = api.create_goal("Join the library")
    grant = api.grant_definition("create_subgoal", operator_id, goal_id=parent["id"])
    run_id = api.start_run(definition_grant_id=grant["id"])["id"]
    return path, api, parent["id"], grant, run_id


def subgoal_call(api, run_id, parent_id, revision=1):
    return api.start_tool_call(
        run_id, "create_subgoal", target_goal_id=parent_id, target_revision=revision
    )


def save_child(api, parent_id, call, key="card", revision=1, **changes):
    fields = {"success_criteria": "The library issues a card."} | changes
    return api.create_delegated_subgoal(
        parent_id, revision, "Get a card", retry_key=key, call=call, **fields
    )


@pytest.mark.parametrize("open_status", ["draft", "active", "paused"])
@pytest.mark.parametrize("closed_status", ["completed", "revoked"])
def test_subgoal_parent_lifecycle_and_retrieval(planning, open_status, closed_status):
    path, api, parent, _, run = planning
    with closing(sqlite3.connect(path, autocommit=True)) as db:
        db.execute("UPDATE goals SET status=? WHERE id=?", (open_status, parent))
    initial = api.get_goal(parent)
    original_call = subgoal_call(api, run, parent)
    child = save_child(api, parent, original_call)
    sibling = save_child(
        api,
        parent,
        subgoal_call(api, run, parent),
        "checkout",
        success_criteria="The loan appears in the account.",
    )
    assert child != sibling and child["status"] == sibling["status"] == "draft"
    assert api.get_goal(parent) == initial
    if closed_status == "completed":
        api.complete_goal(parent, 1, confirmation="Membership verified")
    else:
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute("UPDATE goals SET status='revoked' WHERE id=?", (parent,))
    with pytest.raises(GoalConflictError, match=closed_status):
        save_child(api, parent, subgoal_call(api, run, parent), "third")
    assert save_child(api, parent, subgoal_call(api, run, parent)) == child
    assert api.get_goal(parent)["revision"] == 1
    assert len(api.get_goal_tree(parent)["goals"]) == 3
    calls = api.get_run(run)["calls"]
    assert calls[2]["committed_revision"] is None
    assert calls[0]["committed_revision"] == calls[3]["retrieved_revision"]
    rev = next(
        e
        for e in api.get_goal_activity(child["goal_id"])["timeline"]
        if e["kind"] == "revision"
    )
    assert rev["committing_call"] == original_call


def test_subgoal_checks_criteria_revision_and_grant_on_every_request(planning):
    _, api, parent, grant, run = planning
    for fields in (
        {},
        {"success_criteria": ""},
        {"success_criteria": "  "},
        {"success_criteria": None},
    ):
        with pytest.raises(GoalValidationError, match="criteria"):
            api.create_delegated_subgoal(
                parent,
                1,
                "Card",
                retry_key="card",
                call=subgoal_call(api, run, parent),
                **fields,
            )
    child = save_child(api, parent, subgoal_call(api, run, parent))
    baseline = api.get_goal_tree(parent)
    with pytest.raises(GoalConflictError, match="different"):
        save_child(
            api, parent, subgoal_call(api, run, parent), success_criteria="Changed"
        )
    assert api.get_goal_tree(parent) == baseline
    api.update_goal(parent, title="Renew library membership")
    revised = api.get_goal_tree(parent)
    with pytest.raises(GoalConflictError, match="Stale"):
        save_child(api, parent, subgoal_call(api, run, parent))
    with pytest.raises(GoalConflictError, match="different"):
        save_child(api, parent, subgoal_call(api, run, parent, 2), revision=2)
    api.withdraw_definition_grant(grant["id"])
    fresh = api.grant_definition("create_subgoal", grant["operator_id"], goal_id=parent)
    assert fresh["id"] != grant["id"]
    for key in ("card", "new"):
        with pytest.raises(GoalValidationError, match="inactive"):
            save_child(api, parent, subgoal_call(api, run, parent, 2), key, revision=2)
    assert api.get_goal_tree(parent) == revised
    calls = api.get_run(run)["calls"]
    assert [c["committed_revision"] for c in calls if c["committed_revision"]] == [
        {"goal_id": child["goal_id"], "revision": 1}
    ]
    assert all(c["retrieved_revision"] is None for c in calls)


def test_subgoal_concurrent_retry_and_recovery_after_commit(planning):
    path, api, parent, grant, run = planning
    attempts = [subgoal_call(api, run, parent) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda call: save_child(GoalAPI(path), parent, call), attempts)
        )
    assert results[0] == results[1]
    (winner,) = [c for c in api.get_run(run)["calls"] if c["committed_revision"]]
    original = {"run_id": run, "sequence": winner["sequence"]}
    with pytest.raises(GoalConflictError, match="already saved"):
        save_child(api, parent, original, "different")
    api.finish_run(run, "failed")
    reopened = GoalAPI(path)
    root, child = reopened.get_goal_tree(parent)["goals"]
    assert (
        child["id"] == results[0]["goal_id"] and child["parent_goal_id"] == root["id"]
    )
    (first,) = [
        e
        for e in reopened.get_goal_activity(child["id"])["timeline"]
        if e["kind"] == "revision"
    ]
    assert first["committing_call"] == original
    fresh = reopened.start_run(definition_grant_id=grant["id"])["id"]
    assert (
        save_child(reopened, parent, subgoal_call(reopened, fresh, parent))
        == results[0]
    )
    assert winner["outcome"] == "unfinished" and winner["returned_goals"] is None
    for c in [*reopened.get_run(run)["calls"], *reopened.get_run(fresh)["calls"]]:
        if c["run_id"] != run or c["sequence"] != original["sequence"]:
            assert c["retrieved_revision"] == winner["committed_revision"]
            assert c["committed_revision"] is None
    assert len(reopened.list_goals()) == 2


def test_subgoal_authority_is_checked_by_model(planning):
    _, api, parent, grant, run = planning
    other = api.create_goal("Another parent")["id"]
    with pytest.raises(GoalValidationError, match="does not cover"):
        save_child(api, other, subgoal_call(api, run, other))
    with pytest.raises(GoalValidationError, match="does not match"):
        save_child(api, parent, subgoal_call(api, run, other))
    advisory = api.start_run()["id"]
    top = api.grant_definition("create_goal", grant["operator_id"])
    creation_run = api.start_run(definition_grant_id=top["id"])["id"]
    for wrong_run in (advisory, creation_run):
        with pytest.raises(GoalValidationError):
            save_child(api, parent, subgoal_call(api, wrong_run, parent))
    call = subgoal_call(api, run, parent)
    api.finish_run(run, "failed")
    with pytest.raises(GoalValidationError, match="does not match"):
        save_child(api, parent, call)
    assert [g["id"] for g in api.list_goals()] == [parent, other]
    assert all(
        c["committed_revision"] is None
        for r in [advisory, creation_run, run]
        for c in api.get_run(r)["calls"]
    )


@pytest.mark.parametrize("retry", [False, True], ids=["commit", "retrieval"])
def test_subgoal_audit_cannot_deny_an_applied_call(planning, retry):
    _, api, parent, _, run = planning
    if retry:
        save_child(api, parent, subgoal_call(api, run, parent))
    call = subgoal_call(api, run, parent)
    result = save_child(api, parent, call)
    with pytest.raises(GoalValidationError, match="denied"):
        api.finish_tool_call(call, "denied")
    saved = api.get_run(run)["calls"][-1]
    assert saved["outcome"] == "unfinished"
    assert saved["retrieved_revision" if retry else "committed_revision"] == {
        "goal_id": result["goal_id"],
        "revision": result["revision"],
    }
    api.finish_tool_call(
        call,
        "returned",
        returned_goals=[result | {"observation_ids": [], "decision": None}],
    )
    assert api.get_run(run)["calls"][-1]["outcome"] == "returned"
