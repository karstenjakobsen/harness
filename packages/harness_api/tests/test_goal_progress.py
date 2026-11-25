import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier

import pytest

from harness_api import GoalAPI, GoalConflictError, GoalValidationError


def test_owner_context_requires_a_boolean(tmp_path):
    with pytest.raises(GoalValidationError, match="local_owner"):
        GoalAPI(tmp_path / "goals.db", local_owner="false")


def test_concurrent_retries_create_one_citable_report(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    goal_id = api.create_goal("Track", target_distinct_dates=1)["id"]
    ready = Barrier(2, timeout=5)

    def submit():
        caller = GoalAPI(path)
        ready.wait()
        return caller.record_observation(
            goal_id,
            confirmation="Logged",
            reported_date="2026-11-23",
            retry_key="monday",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, retry = [pool.submit(submit) for _ in range(2)]
        saved = first.result()
        assert retry.result() == saved
    assert api.get_goal_progress(goal_id)["evidence"] == [saved]


def test_monday_reports_support_both_revisions_and_keep_their_submission_history(
    tmp_path,
):
    api = GoalAPI(tmp_path / "workspace.sqlite3")
    goal = api.create_goal("Track food", status="active", target_distinct_dates=7)
    goal_id = goal["id"]
    monday = "2026-11-23"
    first = api.record_observation(
        goal_id, confirmation="Logged meals", reported_date=monday, retry_key="first"
    )
    second = api.record_observation(
        goal_id,
        confirmation="Reviewed Monday's log",
        reported_date=monday,
        retry_key="second",
    )
    ids = [first["evidence_id"], second["evidence_id"]]
    assert ids[0] != ids[1]
    for target, revision in [(7, 1), (14, 2)]:
        if revision == 2:
            api.update_goal(goal_id, target_distinct_dates=target)
        progress = api.get_goal_progress(goal_id)
        assert (progress["count"], progress["target"], progress["revision"]) == (
            1,
            target,
            revision,
        )
        assert progress["result"] == "unmet" and progress["status"] == "active"
        assert progress["days"] == [{"reported_date": monday, "evidence_ids": ids}]
        assert progress["evidence"] == [first, second]
    assert first["source"] == "owner_confirmation"
    assert first["submitted_by"] == first["observed_by"] == "admin"
    assert first["requested_by"] is None
    late = api.record_observation(
        goal_id,
        confirmation="Another Monday entry",
        reported_date=monday,
        retry_key="late",
    )
    old = api.get_goal_progress(goal_id, revision=1)
    assert (old["count"], old["target"], old["revision"]) == (1, 7, 1)
    assert old["evidence"] == [first, second, late]
    history = api.get_goal_history(goal_id)
    assert [r["evidence"] for r in history] == [[first, second], [late]]
    assert all(r["created_at"] for r in history)
    assert all(e["recorded_at"] for e in old["evidence"])


def test_retry_key_returns_original_observation_even_after_revision(tmp_path):
    api = GoalAPI(tmp_path / "goals.db")
    goal_id = api.create_goal("Track")["id"]
    report = {
        "reference": "app:log/1",
        "reported_date": "2026-11-23",
        "retry_key": "monday",
    }
    saved = api.record_observation(goal_id, **report)
    assert (
        saved["source"] == "owner_supplied_reference" and saved["observed_by"] is None
    )
    api.update_goal(goal_id, title="Track meals")
    assert api.record_observation(goal_id, **report) == saved
    with pytest.raises(GoalConflictError):
        api.record_observation(goal_id, **{**report, "reported_date": "2026-11-24"})
    progress = api.get_goal_progress(goal_id)
    assert progress["result"] == "unavailable" and progress["evidence"] == [saved]


def test_count_uses_report_dates_within_both_inclusive_bounds(tmp_path):
    api = GoalAPI(tmp_path / "goals.db")
    goal_id = api.create_goal(
        "Track", target_distinct_dates=2, duration_days=2, window_start="2026-11-22"
    )["id"]
    for day in (21, 22, 23, 24):
        api.record_observation(
            goal_id,
            confirmation="Logged",
            reported_date=f"2026-11-{day}",
            retry_key=str(day),
        )
    api.record_observation(
        goal_id, reference="app:entry", reported_date="2026-11-22", retry_key="ref"
    )
    api.record_observation(goal_id, confirmation="Undated", retry_key="undated")
    result = api.get_goal_progress(goal_id)
    assert result["result"] == "met" and result["status"] == "draft"
    assert (result["window_start"], result["window_end"]) == (
        "2026-11-22",
        "2026-11-23",
    )
    assert [r["reported_date"] for r in result["evidence"]] == [
        "2026-11-22",
        "2026-11-23",
    ]


def test_decision_freezes_cited_ids_and_keeps_its_own_statement(tmp_path):
    path = tmp_path / "goals.db"
    api = GoalAPI(path)
    goal_id = api.create_goal("Review", status="active")["id"]
    other = api.create_goal("Other")["id"]
    ids = [
        api.record_observation(goal_id, confirmation="A report", retry_key=key)[
            "evidence_id"
        ]
        for key in ("a", "b")
    ]
    foreign_id = api.record_observation(
        other, confirmation="Other report", retry_key="a"
    )["evidence_id"]
    before = api.get_goal_history(goal_id)
    for invalid in ([*ids, foreign_id], [999], [True]):
        with pytest.raises(GoalValidationError):
            api.complete_goal(goal_id, 1, confirmation="Reviewed", evidence_ids=invalid)
    assert api.get_goal_history(goal_id) == before
    saved = api.complete_goal(goal_id, 1, confirmation="Reviewed", evidence_ids=ids)
    assert saved["evidence_ids"] == ids and saved["statement_evidence_id"] not in ids
    assert (
        api.complete_goal(goal_id, 1, confirmation="Reviewed", evidence_ids=ids[::-1])
        == saved
    )
    with pytest.raises(GoalValidationError, match="different completion"):
        api.complete_goal(goal_id, 1, confirmation="Reviewed", evidence_ids=ids[:1])
    api.record_observation(goal_id, confirmation="Later", retry_key="later")
    api.update_goal(goal_id, title="Review again")
    with pytest.raises(GoalValidationError, match="Stale"):
        api.complete_goal(goal_id, 1, confirmation="Reviewed", evidence_ids=ids)
    first, second = GoalAPI(path).get_goal_history(goal_id)
    assert first["completion"] == saved and second["completion"] is None
    assert [r["evidence_id"] for r in first["evidence"][:3]] == [
        *ids,
        saved["statement_evidence_id"],
    ]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("version", [3, 4, 5])
def test_migrated_completion_remains_citable_after_reopen(legacy_database, version):
    path = legacy_database(version)
    owner = "admin" if version == 5 else "local"
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute(
            "INSERT INTO goals (id, owner_user_id, status) VALUES (7, ?, 'completed')",
            (owner,),
        )
        connection.executescript("""
            INSERT INTO goal_revisions (goal_id, revision, title, created_at)
            VALUES (7, 1, 'Track meals', '2020-02-01 00:00:00');
        """)
        connection.execute(
            """
            INSERT INTO goal_events (id, goal_id, revision, kind, actor, occurred_at, recorded_at, payload)
            VALUES (19, 7, 1, 'completion', ?, '2020-02-03 12:00:00', '2020-02-04 09:00:00',
            '{"evidence_kind":"owner_supplied_reference","evidence":"app:entry/1"}')
        """,
            (owner,),
        )
    first = GoalAPI(path).get_goal_history(7)
    reopened = GoalAPI(path)
    assert reopened.get_goal_history(7) == first
    [revision] = first
    [record] = revision["evidence"]
    assert record["reported_date"] is None and record["observed_by"] is None
    assert (
        record["source"],
        record["submitted_by"],
        record["occurred_at"],
        record["recorded_at"],
    ) == (
        "owner_supplied_reference",
        "admin",
        "2020-02-03 12:00:00",
        "2020-02-04 09:00:00",
    )
    assert revision["created_at"] == "2020-02-01 00:00:00"
    assert revision["completion"] == {
        "goal_id": 7,
        "revision": 1,
        "event_id": 19,
        "recorded_by": "admin",
        "recorded_at": record["recorded_at"],
        "evidence_kind": record["source"],
        "evidence": "app:entry/1",
        "statement_evidence_id": record["evidence_id"],
        "evidence_ids": [],
    }
    assert (
        reopened.complete_goal(7, 1, reference="app:entry/1") == revision["completion"]
    )
    reopened.update_goal(7, title="Track again")
    cited = reopened.complete_goal(
        7, 2, confirmation="Reviewed", evidence_ids=[record["evidence_id"]]
    )
    assert cited["evidence_ids"] == [record["evidence_id"]]
    assert reopened.get_goal_history(7)[0] == revision


def test_late_monday_report_counts_for_closed_window_on_original_revision(tmp_path):
    api = GoalAPI(tmp_path / "goals.db")
    goal_id = api.create_goal(
        "Track", duration_days=1, window_start="2020-02-03", target_distinct_dates=1
    )["id"]
    assert api.get_goal_progress(goal_id)["count"] == 0
    api.update_goal(goal_id, window_start="2020-02-04")
    report = api.record_observation(
        goal_id,
        confirmation="Logged Monday",
        reported_date="2020-02-03",
        retry_key="monday",
    )
    assert report["revision"] == 2 and report["recorded_at"][:10] > "2020-02-03"
    assert api.get_goal_progress(goal_id)["count"] == 0
    earlier = api.get_goal_progress(goal_id, revision=1)
    assert (earlier["count"], earlier["result"], earlier["evidence"]) == (
        1,
        "met",
        [report],
    )


def test_bounded_count_defaults_to_goal_creation_even_for_a_later_revision(
    legacy_database,
):
    path = legacy_database(5)
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.executescript("""
            INSERT INTO goals (id, owner_user_id, created_at) VALUES (3, 'admin', '2020-02-29T00:59:59+01:00');
            INSERT INTO goal_revisions (goal_id, revision, title) VALUES (3, 1, 'Track');
        """)
    api = GoalAPI(path)
    api.update_goal(3, target_distinct_dates=2, duration_days=3)
    first_day = api.record_observation(
        3, confirmation="Logged", reported_date="2020-02-28", retry_key="first"
    )
    progress = api.get_goal_progress(3)
    assert (progress["window_start"], progress["window_end"]) == (
        "2020-02-28",
        "2020-03-01",
    )
    assert progress["evidence"] == [first_day]
    for fields in (
        {"window_start": "2021-02-29"},
        {"target_distinct_dates": True},
        {"window_start": "9999-12-31"},
        {"duration_days": 2**63 - 1},
    ):
        with pytest.raises(GoalValidationError):
            api.update_goal(3, **fields)
    assert api.get_goal_progress(3) == progress
