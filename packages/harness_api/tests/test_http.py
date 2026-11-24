from fastapi.testclient import TestClient

from harness_api import GoalAPI
from harness_api.app import create_app


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
