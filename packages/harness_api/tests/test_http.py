import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from harness_api import GoalAPI, OperatorAPI
from harness_api.app import create_app


def test_http_reads_delegated_decision_and_rejects_grant_arguments(tmp_path):
    path = tmp_path / "goals.sqlite3"
    api = GoalAPI(path)
    parent = api.create_goal("Parent")
    child = api.create_goal("Child", parent_goal_id=parent["id"])
    goal_id = child["id"]
    operator_id = OperatorAPI(path).register_operator("Reviewer")["id"]
    grant = api.grant_completion(goal_id, operator_id)
    report = api.record_observation(
        goal_id, confirmation="Verified", retry_key="report"
    )
    with TestClient(create_app(path)) as client:
        response = client.post(
            f"/goals/{goal_id}/completion",
            json={
                "revision": 1,
                "confirmation": "Verified",
                "completion_grant_id": grant["id"],
            },
        )
        assert response.status_code == 422
        assert api.get_goal(goal_id)["completion"] is None
        decision = api.complete_goal(
            goal_id,
            1,
            completion_grant_id=grant["id"],
            rationale="Verified",
            evidence_ids=[report["evidence_id"]],
        )
        assert client.get(f"/goals/{goal_id}").json()["completion"] == decision
        assert client.get(f"/goals/{goal_id}/history").json() == api.get_goal_history(
            goal_id
        )


@pytest.mark.parametrize(
    ("intent", "expected"),
    [({}, "draft"), ({"status": "draft"}, "draft"), ({"status": "active"}, "active")],
)
def test_http_goal_creation_intent(tmp_path, intent, expected):
    with TestClient(create_app(tmp_path / "goals.sqlite3")) as client:
        definition = {"title": "Log meals", "duration_days": 7}
        response = client.post("/goals", json={**definition, **intent})
        assert response.status_code == 201
        goal = response.json()
        assert (goal["status"], goal["revision"], goal["duration_days"]) == (
            expected,
            1,
            7,
        )
        assert client.get(response.headers["Location"]).json() == goal
        assert (
            client.post(
                "/goals", json={**definition, "status": "completed"}
            ).status_code
            == 422
        )
        assert [row["id"] for row in client.get("/goals").json()] == [goal["id"]]


def test_delete_conflict_preserves_visible_tree_and_assignment(tmp_path):
    path = tmp_path / "goals.sqlite3"
    with TestClient(create_app(path)) as client:
        parent = client.post("/goals", json={"title": "Parent"}).json()["id"]
        child = client.post(
            "/goals", json={"title": "Child", "parent_goal_id": parent}
        ).json()["id"]
        with closing(sqlite3.connect(path, autocommit=True)) as connection:
            connection.execute(
                "INSERT INTO operators (id, owner_user_id, name) VALUES (1, 1, 'Alice')"
            )
            connection.execute(
                "INSERT INTO goal_assignments (goal_id, operator_id) VALUES (?, 1)",
                (parent,),
            )
            conflict = client.delete(f"/goals/{parent}")
            assert conflict.status_code == 409
            assert "children" in conflict.json()["detail"]
            assert client.get(f"/goals/{parent}").json()["operator"] == "Alice"
            assert client.get(f"/goals/{child}").json()["parent_goal_id"] == parent
            assert [goal["id"] for goal in client.get("/goals").json()] == [
                parent,
                child,
            ]
            assert client.delete(f"/goals/{child}").status_code == 204
            assert client.delete(f"/goals/{parent}").status_code == 204
            assert connection.execute(
                "SELECT released_at FROM goal_assignments WHERE goal_id = ?", (parent,)
            ).fetchone()[0]
            assert client.get("/goals").json() == []


def test_http_crud_shares_goal_model(tmp_path):
    database = tmp_path / "goals.sqlite3"
    with TestClient(create_app(database)) as client:
        response = client.post(
            "/goals",
            json={
                "title": "Check file permissions",
                "desired_outcome": "The config stays private",
                "duration": "standing",
                "assessment_type": "objective",
                "success_criteria": "The mode is 0600",
            },
        )
        assert response.status_code == 201
        created = response.json()
        goal_id = created["id"]
        path = f"/goals/{goal_id}"
        assert response.headers["Location"] == path
        assert created["status"] == "draft"
        assert created["revision"] == 1
        assert GoalAPI(database).get_goal(goal_id) == created
        assert client.get(path).json() == created

        model_created = GoalAPI(database).create_goal("Review the handover")
        drafts = client.get("/goals", params={"status": "draft"}).json()
        assert [draft["id"] for draft in drafts] == [goal_id, model_created["id"]]
        assert client.get("/goals", params={"status": "active"}).json() == []

        revised = client.patch(path, json={"title": "Keep config private"}).json()
        assert revised["revision"] == 2
        assert revised["desired_outcome"] == created["desired_outcome"]
        assert revised["duration"] == "standing"
        assert (
            client.patch(path, json={"desired_outcome": None}).json()["desired_outcome"]
            is None
        )

        deleted = client.delete(path)
        assert deleted.status_code == 204
        assert not deleted.content
        assert client.get(path).status_code == 404
        assert [goal["id"] for goal in client.get("/goals").json()] == [
            model_created["id"]
        ]


def test_http_rejects_invalid_input_and_reports_missing_goals(tmp_path):
    with TestClient(create_app(tmp_path / "goals.sqlite3")) as client:
        assert client.post("/goals", json={"title": " "}).status_code == 422
        assert (
            client.post(
                "/goals", json={"title": "Draft", "duration": "unknown"}
            ).status_code
            == 422
        )
        assert client.get("/goals", params={"status": "unknown"}).status_code == 422
        assert (
            client.post(
                "/goals", json={"title": "Draft", "desired_outcome": 123}
            ).status_code
            == 422
        )
        missing = client.get("/goals/999")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Goal 999 was not found."}
        assert client.get(f"/goals/{2**63}").status_code == 422
        assert (
            client.patch("/goals/999", json={"title": "New title"}).status_code == 404
        )
        assert client.delete("/goals/999").status_code == 404
        assert client.get("/goals").json() == []


def test_http_revises_child_requirements_and_preserves_parent(tmp_path):
    with TestClient(create_app(tmp_path / "goals.sqlite3")) as client:
        root = client.post("/goals", json={"title": "Root"}).json()
        assert (
            client.post(
                "/goals", json={"title": "Child", "parent_goal_id": True}
            ).status_code
            == 422
        )
        child = client.post(
            "/goals",
            json={
                "parent_goal_id": root["id"],
                "title": "Track food",
                "duration_days": 7,
                "measurement_plan": "Review log",
            },
        ).json()
        path = f"/goals/{child['id']}"
        revised = client.patch(
            path, json={"duration_days": 14, "success_criteria": "Log daily"}
        ).json()
        assert revised == {
            **child,
            "revision": 2,
            "duration_days": 14,
            "success_criteria": "Log daily",
        }
        assert revised["parent_goal_id"] == root["id"]
        assert client.patch(path, json={"duration_days": 0}).status_code == 422
        assert (
            client.patch(path, json={"duration_days": None}).json()["duration_days"]
            is None
        )
        assert client.get(f"/goals/{root['id']}").json() == root


def test_http_reports_storage_unavailable(tmp_path):
    database = tmp_path / "goals.sqlite3"
    with TestClient(create_app(database)) as client:
        database.rename(tmp_path / "moved.sqlite3")
        response = client.get("/goals")
        assert response.status_code == 503
        assert response.json() == {"detail": "The goals database is unavailable."}


def test_http_observations_keep_unknown_caller_and_completion_citations(tmp_path):
    db = tmp_path / "goals.db"
    with TestClient(create_app(db)) as client:
        goal = client.post(
            "/goals",
            json={
                "title": "Track",
                "target_distinct_dates": 7,
                "window_start": "2026-11-23",
                "duration_days": 7,
            },
        ).json()
        path = f"/goals/{goal['id']}"
        report = {
            "confirmation": "Daily log",
            "reported_date": "2026-11-23",
            "retry_key": "entry-1",
        }
        obs = path + "/observations"
        for forged in (
            {"submitted_by": 1},
            {"source": "machine"},
            {"observed_by": "app"},
        ):
            assert client.post(obs, json=report | forged).status_code == 422
        saved = client.post(obs, json=report)
        assert saved.status_code == 200
        evidence = saved.json()
        assert evidence["source"] == "unattributed_confirmation"
        assert (
            evidence["submitted_by"]
            is evidence["observed_by"]
            is evidence["requested_by"]
            is None
        )
        assert client.post(obs, json=report).json() == evidence
        assert (
            client.post(obs, json=report | {"reported_date": "2026-11-24"}).status_code
            == 409
        )
        assert (
            client.post(obs, json=report | {"reported_date": "2026-02-29"}).status_code
            == 422
        )
        future = report | {"retry_key": "advance", "reported_date": "9999-01-01"}
        assert client.post(obs, json=future).status_code == 422
        api = GoalAPI(db)
        local = api.record_observation(
            goal["id"],
            confirmation="Daily log",
            reported_date="2026-11-23",
            retry_key="entry-1",
        )
        client.patch(path, json={"target_distinct_dates": 14}).raise_for_status()
        progress = client.get(path + "/progress", params={"revision": 1}).json()
        assert progress == api.get_goal_progress(goal["id"], revision=1)
        assert (progress["count"], progress["target"], progress["evidence"]) == (
            1,
            7,
            [evidence, local],
        )
        assert progress["days"] == [
            {
                "reported_date": local["reported_date"],
                "evidence_ids": [local["evidence_id"]],
            }
        ]
        assert client.get(path + "/progress?revision=999").status_code == 422
        citations = [evidence["evidence_id"], local["evidence_id"]]
        body = {"revision": 2, "reference": "app:report/1", "evidence_ids": citations}
        assert (
            client.post(path + "/completion", json=body | {"revision": 1}).status_code
            == 422
        )
        assert (
            client.post(
                path + "/completion", json=body | {"evidence_ids": [True]}
            ).status_code
            == 422
        )
        decision = client.post(path + "/completion", json=body).json()
        assert (
            decision["recorded_by"] is None
            and decision["evidence_kind"] == "unattributed_reference"
        )
        assert decision["evidence_ids"] == citations
        assert client.post(path + "/completion", json=body).json() == decision
        history = client.get(path + "/history").json()
        assert history == api.get_goal_history(goal["id"])
        assert history[-1]["completion"] == decision


def test_configuring_a_worker_protects_the_running_owner_api(tmp_path):
    db = tmp_path / "workspace.db"
    api = GoalAPI(db)
    image = "example/worker@sha256:" + "a" * 64
    with TestClient(create_app(db)) as client:
        assert client.get("/goals").status_code == 200
        api.work.configure_launcher(image, "local", "http://worker/mcp")
        token_file = api.work.owner_http_token_file
        assert token_file.stat().st_mode & 0o777 == 0o600
        token = token_file.read_text()
        api.work.configure_launcher(image, "local", "http://worker/mcp")
        assert token_file.read_text() == token
        for path in ["/goals", "/users", "/operators", "/skills", "/runs/1"]:
            assert client.get(path).status_code == 401
        assert client.post("/goals", json={"title": "Unauthorized"}).status_code == 401
        client.headers["Authorization"] = "Bearer " + token
        assert client.get("/goals").json() == []
        token_file.unlink()
        assert client.get("/goals").status_code == 401
