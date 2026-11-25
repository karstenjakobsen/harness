import pytest
from fastapi.testclient import TestClient

from harness_api import OperatorAPI, UserAPI
from harness_api.app import create_app


def test_account_endpoints_share_ownership_and_deletion_rules(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    with TestClient(create_app(path)) as client:
        users = UserAPI(path)
        operators = OperatorAPI(path)

        admin = users.get_user(1)
        assert client.get("/users").json() == [admin]
        assert client.delete("/users/1").status_code == 409
        response = client.post("/users", json={"username": "sam"})
        assert response.status_code == 201
        owner_id = response.json()["id"]
        user_url = response.headers["Location"]
        assert user_url == f"/users/{owner_id}"
        assert (
            response.json() == users.get_user(owner_id) == client.get(user_url).json()
        )
        updated = client.patch(user_url, json={"display_name": "Sam Lee"})
        assert (
            updated.status_code == 200
            and users.get_user(owner_id)["display_name"] == "Sam Lee"
        )
        assert updated.json() == users.get_user(owner_id)

        default = client.post("/operators", json={"name": "Coach"})
        assert default.status_code == 201 and default.json()["owner_user_id"] == 1
        registration = client.post(
            "/operators", json={"name": "Planner", "owner_user_id": owner_id}
        )
        assert registration.status_code == 201
        route = registration.headers["Location"]
        operator = operators.get_operator(registration.json()["id"])
        assert client.get(route).json() == registration.json() == operator
        assert client.get("/operators", params={"owner_user_id": owner_id}).json() == [
            operator
        ]
        conflict = client.delete(user_url)
        assert (
            conflict.status_code == 409
            and "registered operator" in conflict.json()["detail"]
        )

        assert client.delete(route).status_code == 204
        assert client.get(route).status_code == 404
        assert client.get("/operators").json() == [default.json()]
        assert client.delete(user_url).status_code == 204
        assert client.get(user_url).status_code == 404
        assert client.get("/users").json() == [admin]
        assert client.post("/users", json={"username": "sam"}).status_code == 409
        assert (
            client.post(
                "/operators", json={"name": "Again", "owner_user_id": owner_id}
            ).status_code
            == 404
        )


@pytest.mark.parametrize("username", ["søren/a?b#c", "..", "team%2Fone"])
def test_username_is_independent_of_generated_user_location(tmp_path, username):
    with TestClient(create_app(tmp_path / "accounts.sqlite3")) as client:
        response = client.post("/users", json={"username": username})
        assert response.status_code == 201
        url = response.headers["Location"]
        user = client.get(url).json()
        assert user["username"] == username
        assert url == f"/users/{user['id']}"


def test_account_http_errors(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    with TestClient(create_app(path)) as client:
        assert client.post("/users", json={"username": " "}).status_code == 422
        assert (
            client.post("/users", json={"username": "sam", "id": 50}).status_code == 422
        )
        assert (
            client.post("/operators", json={"name": "Coach", "id": 50}).status_code
            == 422
        )
        for invalid_id in ("1", True, 1.5, 0, 2**63):
            assert (
                client.post(
                    "/operators", json={"name": "Coach", "owner_user_id": invalid_id}
                ).status_code
                == 422
            )
        assert client.patch("/users/1", json={"display_name": None}).status_code == 422
        assert (
            client.post(
                "/operators", json={"name": "Coach", "deleted_at": "now"}
            ).status_code
            == 422
        )
        assert client.get(f"/operators/{2**63}").status_code == 422
        assert client.get("/operators/999").status_code == 404
        path.rename(tmp_path / "moved.sqlite3")
        failure = client.get("/users")
        assert failure.status_code == 503
        assert failure.json() == {"detail": "The workspace database is unavailable."}
