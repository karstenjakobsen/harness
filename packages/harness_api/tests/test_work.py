from contextlib import closing

import pytest

from harness_api import GoalAPI, GoalConflictError, OperatorAPI

IMAGE = "localhost/worker@sha256:" + "a" * 64


class Scheduler:
    def __init__(self):
        self.registrations = []

    crash = False
    crash_before_request = False
    missing = False

    @staticmethod
    def handle(run_id):
        return "job-" + run_id

    def start(self, run_id, spec):
        if self.crash_before_request:
            raise KeyboardInterrupt()
        self.registrations.append((run_id, spec))
        if self.crash:
            raise KeyboardInterrupt()

    def lookup(self, run_id, spec):
        from harness_api import WorkloadStatus

        if self.missing:
            raise OSError("Job records unavailable")
        return WorkloadStatus("running", self.handle(run_id), "alloc-" + run_id)


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    api.work.configure_launcher(IMAGE, "local-test", "local-worker")
    goal = api.create_goal("Test pinned rooks")["id"]
    operator = OperatorAPI(path).register_operator("Reviewer")["id"]
    grant = api.grant_work(goal, operator)
    run = api.start_run(work_grant_id=grant["id"])["id"]
    return api, goal, run


def delegate(api, goal, run, skills=()):
    call = api.start_tool_call(
        run, "delegate_work", target_goal_id=goal, target_revision=1
    )
    return api.work.delegate_work(
        goal, 1, "Prepare two cases", list(skills), "brief", call=call
    )


def test_lost_delegation_reply_after_revision_edit(workspace, tmp_path):
    from harness_api import GoalValidationError

    api, goal, run = workspace
    original = delegate(api, goal, run)
    api.update_goal(goal, title="New requirements")
    api = GoalAPI(tmp_path / "goals.db")
    assert delegate(api, goal, run) == original
    calls = api.get_run(run)["calls"]
    assert len(calls) == 2
    assert calls[0]["sequence"] == original["sequence"]
    assert calls[1]["sequence"] != original["sequence"]
    assert [c["work"]["result"] for c in calls] == ["committed", "retrieved"]
    assert calls[1]["work"]["attempt_id"] == original["attempt_id"]
    for key, brief, reason in [
        ("brief", "Different", "different work"),
        ("new", "Prepare two cases", "revision 2"),
    ]:
        call = api.start_tool_call(
            run, "delegate_work", target_goal_id=goal, target_revision=1
        )
        with pytest.raises(GoalConflictError, match=reason):
            api.work.delegate_work(goal, 1, brief, [], key, call=call)
    scheduler = Scheduler()
    api.work.dispatch(original["attempt_id"], scheduler)
    assert scheduler.registrations == []
    (item,) = api.get_goal_activity(goal)["work_items"]
    (attempt,) = item["attempts"]
    assert attempt["state"] == "declined" and "revision 2" in attempt["reason"]
    api.withdraw_work(item["grant_id"])
    api.grant_work(goal, item["operator_id"])
    with pytest.raises(GoalValidationError):
        delegate(api, goal, run)


def test_revision_edit_before_dispatch_and_retry(workspace):
    api, goal, run = workspace
    work = delegate(api, goal, run)
    api.update_goal(goal, title="New requirements")
    scheduler = Scheduler()
    api.work.dispatch(work["attempt_id"], scheduler)
    assert scheduler.registrations == []
    (item,) = api.get_goal_activity(goal)["work_items"]
    (attempt,) = item["attempts"]
    assert attempt["state"] == "declined"
    assert "revision 1" in attempt["reason"] and "revision 2" in attempt["reason"]
    call = api.start_tool_call(run, "retry_work", target_work_item_id=item["id"])
    with pytest.raises(GoalConflictError, match="revision 2"):
        api.work.retry_work(item["id"], attempt["id"], "again", call=call)
    assert len(api.get_goal_activity(goal)["work_items"][0]["attempts"]) == 1


def retry(api, run, item, expected, key):
    call = api.start_tool_call(run, "retry_work", target_work_item_id=item)
    return api.work.retry_work(item, expected, key, call=call)


def history(api, goal):
    return api.get_goal_activity(goal)["work_items"][0]


def test_pending_dispatch_race_and_reopen(workspace, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    api, goal, run = workspace
    result = delegate(api, goal, run)
    scheduler = Scheduler()
    barrier = Barrier(2)

    def recover(_):
        barrier.wait()
        GoalAPI(tmp_path / "goals.db").work.dispatch(result["attempt_id"], scheduler)

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(recover, range(2)))
    assert len(scheduler.registrations) == 1
    (attempt,) = history(api, goal)["attempts"]
    assert attempt["state"] == "running"
    assert attempt["committing_call"] == {"run_id": run, "sequence": 1}


def test_dispatch_crashes_reconcile_without_registration(workspace, tmp_path):
    api, goal, run = workspace
    result = delegate(api, goal, run)
    scheduler = Scheduler()
    scheduler.crash = True
    with pytest.raises(KeyboardInterrupt):
        api.work.dispatch(result["attempt_id"], scheduler)
    scheduler.crash = False
    reopened = GoalAPI(tmp_path / "goals.db")
    reopened.work.dispatch(result["attempt_id"], scheduler)
    assert len(scheduler.registrations) == 1
    assert history(reopened, goal)["attempts"][0]["state"] == "running"
    scheduler.missing = True
    reopened.work.dispatch(result["attempt_id"], scheduler)
    assert history(reopened, goal)["attempts"][0]["state"] == "unknown"
    assert len(scheduler.registrations) == 1


def test_crash_between_claim_and_request_stays_unknown(workspace, tmp_path):
    api, goal, run = workspace
    result = delegate(api, goal, run)
    scheduler = Scheduler()
    scheduler.crash_before_request = True
    with pytest.raises(KeyboardInterrupt):
        api.work.dispatch(result["attempt_id"], scheduler)
    scheduler.missing = True
    GoalAPI(tmp_path / "goals.db").work.dispatch(result["attempt_id"], scheduler)
    assert scheduler.registrations == []
    assert history(api, goal)["attempts"][0]["state"] == "unknown"


def test_concurrent_retries_and_late_evidence(workspace):
    from concurrent.futures import ThreadPoolExecutor

    api, goal, run = workspace
    first = delegate(api, goal, run)
    scheduler = Scheduler()
    api.work.dispatch(first["attempt_id"], scheduler)

    def decide(key):
        try:
            return retry(api, run, first["work_item_id"], first["attempt_id"], key)
        except GoalConflictError:
            return None

    with ThreadPoolExecutor(2) as pool:
        decisions = list(pool.map(decide, ["again-a", "again-b"]))
    second = next(d for d in decisions if d)
    assert sum(d is None for d in decisions) == 1
    key = "again-a" if decisions[0] else "again-b"
    assert retry(api, run, first["work_item_id"], first["attempt_id"], key) == second
    with pytest.raises(GoalConflictError):
        retry(api, run, first["work_item_id"], second["attempt_id"], key)
    api.work.dispatch(second["attempt_id"], scheduler)
    attempts = history(api, goal)["attempts"]
    for attempt in reversed(attempts):
        submitted = api.work.worker_call(
            attempt["job_id"],
            attempt["allocation_id"],
            "submit_work_result",
            {"fixture": FIXTURE},
        )
        assert (
            api.work.worker_call(
                attempt["job_id"],
                attempt["allocation_id"],
                "submit_work_result",
                {"fixture": FIXTURE},
            )
            == submitted
        )
        with pytest.raises(GoalConflictError):
            api.work.worker_call(
                attempt["job_id"],
                attempt["allocation_id"],
                "submit_work_result",
                {"fixture": FIXTURE | {"executed": True}},
            )
    item = history(api, goal)
    assert item["latest_attempt_id"] == second["attempt_id"]
    assert all(a["result"] for a in item["attempts"])
    assert (
        item["attempts"][0]["result"]["evidence_id"]
        > item["attempts"][1]["result"]["evidence_id"]
    )
    assert api.get_goal(goal)["status"] == "draft"


FIXTURE = {
    "cases": [
        {
            "fen": "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
            "move": "e2f2",
            "expected_legal": False,
            "reason": "Exposes the white king.",
        }
    ],
    "executed": False,
}


def test_scoped_authority_and_withdrawal(workspace):
    from harness_api import GoalValidationError

    api, goal, run = workspace
    first = delegate(api, goal, run)
    scheduler = Scheduler()
    api.work.dispatch(first["attempt_id"], scheduler)
    attempt = history(api, goal)["attempts"][0]
    binding = attempt["job_id"], attempt["allocation_id"]
    with pytest.raises(GoalValidationError):
        api.work.worker_call(
            binding[0], "replacement", "submit_work_result", {"fixture": FIXTURE}
        )
    with pytest.raises(GoalValidationError):
        api.work.worker_call(
            *binding, "read_skill", {"id": "unassigned", "revision": 1}
        )
    with pytest.raises(GoalValidationError):
        api.work.worker_call(*binding, "get_work_brief", {"work_item_id": 2})
    other = api.create_goal("Other")["id"]
    with pytest.raises(GoalValidationError):
        delegate(api, other, run)
    assert api.work.can_read(*binding)
    grant = api.get_run(run)["work_grant_id"]
    operator = api.get_run(run)["operator_id"]
    api.withdraw_work(grant)
    api.grant_work(goal, operator)
    assert not api.work.can_read(*binding)
    for tool, args in [
        ("get_work_brief", {}),
        ("submit_work_result", {"fixture": FIXTURE}),
    ]:
        with pytest.raises(GoalValidationError):
            api.work.worker_call(*binding, tool, args)
    with pytest.raises(GoalValidationError):
        retry(api, run, first["work_item_id"], first["attempt_id"], "new")
    with pytest.raises(GoalValidationError):
        delegate(api, goal, run)
    assert len(history(api, goal)["attempts"]) == 1
    assert history(api, goal)["attempts"][0]["result"] is None
    assert all(
        c["outcome"] == "denied"
        for c in history(api, goal)["attempts"][0]["worker_calls"]
    )


def test_pinned_skills_and_goal_edit_during_execution(workspace):
    from harness_api import SkillCatalog, SkillSource

    api, goal, run = workspace

    def catalog(revision):
        return SkillCatalog(
            str(revision) * 40,
            (
                SkillSource(
                    "skills/chess-rules",
                    f"kind: skill\nid: chess-rules\nname: Chess\ndescription: King safety\nauthor: Harness\nrevision: {revision}\n",
                    f"Instructions {revision}",
                ),
            ),
        )

    api.skills.import_catalog(catalog(1))
    first = delegate(api, goal, run, [{"id": "chess-rules", "revision": 1}])
    scheduler = Scheduler()
    api.work.dispatch(first["attempt_id"], scheduler)
    api.update_goal(goal, title="Updated goal")
    api.skills.import_catalog(catalog(2))
    attempt = history(api, goal)["attempts"][0]
    binding = attempt["job_id"], attempt["allocation_id"]
    assert api.work.worker_call(*binding, "get_work_brief", {})["goal"]["revision"] == 1
    assert (
        api.work.worker_call(*binding, "list_skills", {})["skills"][0]["revision"] == 1
    )
    assert (
        api.work.worker_call(
            *binding, "read_skill", {"id": "chess-rules", "revision": 1}
        )["instructions"]
        == "Instructions 1"
    )
    result = api.work.worker_call(*binding, "submit_work_result", {"fixture": FIXTURE})
    (report,) = api.get_goal_history(goal)[0]["evidence"]
    assert result["revision"] == report["revision"] == 1
    assert report["worker_attempt_id"] == first["attempt_id"]
    assert report["requesting_operator_id"] == api.get_run(run)["operator_id"]


def test_duplicate_delegation_and_atomic_rollback(workspace, tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor

    from harness_api import WorkspaceStorageError

    api, goal, run = workspace
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: delegate(api, goal, run), range(2)))
    assert results[0] == results[1]
    assert len(history(api, goal)["attempts"]) == 1
    with closing(sqlite3.connect(tmp_path / "goals.db", autocommit=True)) as db:
        db.execute(
            "CREATE TRIGGER fail_link BEFORE INSERT ON work_call_results BEGIN SELECT RAISE(ABORT,'failed link'); END"
        )
    with pytest.raises(WorkspaceStorageError):
        retry(api, run, results[0]["work_item_id"], results[0]["attempt_id"], "again")
    assert len(history(api, goal)["attempts"]) == 1
    with closing(sqlite3.connect(tmp_path / "goals.db", autocommit=True)) as db:
        db.execute("DROP TRIGGER fail_link")
    assert (
        retry(api, run, results[0]["work_item_id"], results[0]["attempt_id"], "again")[
            "attempt_id"
        ]
        != results[0]["attempt_id"]
    )


@pytest.mark.parametrize(
    "fixture",
    [
        {"cases": [], "executed": False},
        {"cases": FIXTURE["cases"] * 17, "executed": False},
        {"cases": [FIXTURE["cases"][0] | {"reason": "x" * 601}], "executed": False},
        FIXTURE | {"executed": "false"},
        FIXTURE | {"operator_id": 1},
    ],
)
def test_bounded_fixture_denial_leaves_evidence_unchanged(workspace, fixture):
    api, goal, run = workspace
    first = delegate(api, goal, run)
    api.work.dispatch(first["attempt_id"], Scheduler())
    attempt = history(api, goal)["attempts"][0]
    with pytest.raises(ValueError):
        api.work.worker_call(
            attempt["job_id"],
            attempt["allocation_id"],
            "submit_work_result",
            {"fixture": fixture},
        )
    assert not api.get_goal_progress(goal)["evidence"]


def test_submission_race_and_failure_rollback(workspace, tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor

    from harness_api import WorkspaceStorageError

    api, goal, run = workspace
    first = delegate(api, goal, run)
    api.work.dispatch(first["attempt_id"], Scheduler())
    attempt = history(api, goal)["attempts"][0]
    binding = attempt["job_id"], attempt["allocation_id"]
    with closing(sqlite3.connect(tmp_path / "goals.db", autocommit=True)) as db:
        db.execute(
            "CREATE TRIGGER fail_result BEFORE INSERT ON work_results BEGIN SELECT RAISE(ABORT,'failed result'); END"
        )
    with pytest.raises(WorkspaceStorageError):
        api.work.worker_call(*binding, "submit_work_result", {"fixture": FIXTURE})
    assert api.get_goal_progress(goal)["evidence"] == []
    assert history(api, goal)["attempts"][0]["worker_calls"] == []
    with closing(sqlite3.connect(tmp_path / "goals.db", autocommit=True)) as db:
        db.execute("DROP TRIGGER fail_result")
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(
                lambda _: api.work.worker_call(
                    *binding, "submit_work_result", {"fixture": FIXTURE}
                ),
                range(2),
            )
        )
    assert results[0] == results[1]
    assert len(api.get_goal_progress(goal)["evidence"]) == 1


def test_assignment_without_work_grant_cannot_delegate(workspace):
    from harness_api import GoalValidationError

    api, _goal, run = workspace
    operator = api.get_run(run)["operator_id"]
    parent = api.create_goal("Parent")["id"]
    child = api.create_goal("Child", parent_goal_id=parent)["id"]
    completion = api.grant_completion(child, operator)
    assigned_run = api.start_run(completion["id"])["id"]
    with pytest.raises(GoalValidationError):
        delegate(api, child, assigned_run)
    assert api.get_goal_activity(child)["work_items"] == []


def test_byte_limit_is_checked_before_observation_write(workspace):
    api, goal, run = workspace
    first = delegate(api, goal, run)
    api.work.dispatch(first["attempt_id"], Scheduler())
    attempt = history(api, goal)["attempts"][0]
    fixture = {
        "cases": [FIXTURE["cases"][0] | {"reason": "♜" * 600}] * 16,
        "executed": False,
    }
    with pytest.raises(ValueError, match="16384"):
        api.work.worker_call(
            attempt["job_id"],
            attempt["allocation_id"],
            "submit_work_result",
            {"fixture": fixture},
        )
    assert api.get_goal_progress(goal)["evidence"] == []


def test_failed_exit_without_result_and_conflicting_placement(workspace):
    from harness_api import GoalValidationError, WorkloadStatus

    api, goal, run = workspace
    work = delegate(api, goal, run)
    scheduler = Scheduler()
    api.work.dispatch(work["attempt_id"], scheduler)
    original = history(api, goal)["attempts"][0]
    scheduler.lookup = lambda run_id, spec: WorkloadStatus(
        "running", scheduler.handle(run_id), "replacement"
    )
    api.work.dispatch(work["attempt_id"], scheduler)
    changed = history(api, goal)["attempts"][0]
    assert changed["state"] == "unknown"
    assert changed["allocation_id"] == original["allocation_id"]
    assert changed["replacement_allocation_ids"] == ["replacement"]
    with pytest.raises(GoalValidationError):
        api.work.worker_call(changed["job_id"], "replacement", "get_work_brief", {})
    scheduler.lookup = lambda run_id, spec: WorkloadStatus(
        "failed", scheduler.handle(run_id), original["allocation_id"], 7
    )
    api.work.dispatch(work["attempt_id"], scheduler)
    failed = history(api, goal)["attempts"][0]
    assert failed["state"] == "failed" and failed["exit_code"] == 7
    assert failed["result"] is None


def test_late_inspection_preserves_finished_attempt(workspace):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from harness_api import WorkloadStatus

    api, goal, run = workspace
    saved = delegate(api, goal, run)
    scheduler = Scheduler()
    api.work.dispatch(saved["attempt_id"], scheduler)
    original = history(api, goal)["attempts"][0]
    inspecting, release = Event(), Event()

    class DelayedScheduler(Scheduler):
        def lookup(self, run_id, spec):
            inspecting.set()
            assert release.wait(10)
            return WorkloadStatus("running", self.handle(run_id), "replacement")

    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(
            api.work.dispatch, saved["attempt_id"], DelayedScheduler()
        )
        try:
            assert inspecting.wait(10)
            scheduler.lookup = lambda run_id, spec: WorkloadStatus(
                "succeeded", scheduler.handle(run_id), original["allocation_id"], 0
            )
            api.work.dispatch(saved["attempt_id"], scheduler)
        finally:
            release.set()
        pending.result()
    final = history(api, goal)["attempts"][0]
    assert final["state"] == "succeeded" and final["exit_code"] == 0
    assert final["allocation_id"] == original["allocation_id"]
    assert final["replacement_allocation_ids"] == []


def test_submission_conflict_keeps_domain_error_and_audit(workspace):
    api, goal, run = workspace
    saved = delegate(api, goal, run)
    api.work.dispatch(saved["attempt_id"], Scheduler())
    attempt = history(api, goal)["attempts"][0]
    binding = attempt["job_id"], attempt["allocation_id"]
    submitted = api.work.worker_call(
        *binding, "submit_work_result", {"fixture": FIXTURE}
    )
    with pytest.raises(GoalConflictError):
        api.work.worker_call(
            *binding, "submit_work_result", {"fixture": FIXTURE | {"executed": True}}
        )
    current = history(api, goal)["attempts"][0]
    assert current["result"]["evidence_id"] == submitted["evidence_id"]
    assert current["worker_calls"][-1]["outcome"] == "denied"
    assert len(api.get_goal_progress(goal)["evidence"]) == 1


def test_text_file_contract_reopen_and_replay(workspace, tmp_path):
    from fastapi.testclient import TestClient

    from harness_api import GoalValidationError
    from harness_api.app import create_app

    api, goal, run = workspace

    def assign(kind):
        call = api.start_tool_call(
            run, "delegate_work", target_goal_id=goal, target_revision=1
        )
        return api.work.delegate_work(
            goal, 1, "Deliver a file", [], "key", call=call, result_type=kind
        )

    work = assign("text_file")
    with pytest.raises(GoalConflictError, match="different work"):
        assign("fixture")
    api.work.dispatch(work["attempt_id"], Scheduler())
    api.update_goal(goal, title="Updated")
    attempt = history(api, goal)["attempts"][0]
    binding = attempt["job_id"], attempt["allocation_id"]
    assert (
        api.work.worker_call(*binding, "get_work_brief", {})["result_type"]
        == "text_file"
    )

    def submit(**payload):
        return api.work.worker_call(*binding, "submit_work_result", payload)

    file = {"filename": "roundtrip.txt", "content": "\ufeffø\r\n" + "ø" * 8188 + "x"}
    assert len(file["content"].encode("utf-8")) == 16384
    for bad in [
        {"fixture": FIXTURE},
        {"text_file": file | {"filename": "../file"}},
        {"text_file": file | {"content": file["content"] + "x"}},
        {"text_file": file | {"content": "\ud800"}},
    ]:
        with pytest.raises(GoalValidationError):
            submit(**bad)
    assert history(api, goal)["attempts"][0]["result"] is None
    result = submit(text_file=file)
    assert result["evidence_id"] == submit(text_file=file)["evidence_id"]
    for changed in [{"filename": "again.txt"}, {"content": "different"}]:
        with pytest.raises(GoalConflictError):
            submit(text_file=file | changed)
    with TestClient(create_app(tmp_path / "goals.db")) as client:
        assert client.get(f"/goals/{goal}").status_code == 401
        client.headers["Authorization"] = "Bearer wrong"
        assert client.get(f"/goals/{goal}").status_code == 401
        client.headers["Authorization"] = (
            "Bearer " + api.work.owner_http_token_file.read_text()
        )
        (item,) = (
            client.get(f"/goals/{goal}/history?view=activity")
            .raise_for_status()
            .json()["work_items"]
        )
    (attempt,) = item["attempts"]
    assert item["revision"] == 1 and item["result_type"] == "text_file"
    assert attempt["result"]["text_file"] == file
    assert attempt["result"]["evidence_id"] == result["evidence_id"]
    first = next(
        call
        for call in attempt["worker_calls"]
        if call["tool"] == "submit_work_result" and call["outcome"] == "returned"
    )
    assert attempt["result"]["worker_call_id"] == first["id"]
