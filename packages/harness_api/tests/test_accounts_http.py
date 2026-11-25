import httpx2
import pytest
from fastapi.testclient import TestClient

from harness_api import OperatorAPI, UserAPI
from harness_api.app import create_app


def test_account_endpoints_share_ownership_and_deletion_rules(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    with TestClient(create_app(path)) as client:
        users = UserAPI(path)
        operators = OperatorAPI(path)

        admin = users.get_user("admin")
        assert client.get("/users").json() == [admin]
        assert client.delete("/users/admin").status_code == 409
        response = client.post("/users", json={"id": "sam"})
        assert (
            response.status_code == 201 and response.headers["Location"] == "/users/sam"
        )
        assert (
            response.json() == users.get_user("sam") == client.get("/users/sam").json()
        )
        updated = client.patch("/users/sam", json={"display_name": "Sam Lee"})
        assert (
            updated.status_code == 200
            and users.get_user("sam")["display_name"] == "Sam Lee"
        )
        assert updated.json() == users.get_user("sam")

        default = client.post("/operators", json={"name": "Coach"})
        assert default.status_code == 201 and default.json()["owner_user_id"] == "admin"
        registration = client.post(
            "/operators", json={"name": "Planner", "owner_user_id": "sam"}
        )
        assert registration.status_code == 201
        route = registration.headers["Location"]
        operator = operators.get_operator(registration.json()["id"])
        assert client.get(route).json() == registration.json() == operator
        assert client.get("/operators", params={"owner_user_id": "sam"}).json() == [
            operator
        ]
        conflict = client.delete("/users/sam")
        assert (
            conflict.status_code == 409
            and "registered operator" in conflict.json()["detail"]
        )

        assert client.delete(route).status_code == 204
        assert client.get(route).status_code == 404
        assert client.get("/operators").json() == [default.json()]
        assert client.delete("/users/sam").status_code == 204
        assert client.get("/users/sam").status_code == 404
        assert client.get("/users").json() == [admin]
        assert client.post("/users", json={"id": "sam"}).status_code == 409
        assert (
            client.post(
                "/operators", json={"name": "Again", "owner_user_id": "sam"}
            ).status_code
            == 404
        )


@pytest.mark.parametrize("user_id", ["søren/a?b#c", "..", "team%2Fone"])
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.anyio
async def test_created_user_location_round_trips_text_ids(
    tmp_path, user_id, anyio_backend
):
    app = create_app(tmp_path / "accounts.sqlite3")
    # ASGITransport decodes the wire path once, as Uvicorn does.
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post("/users", json={"id": user_id})
        assert response.status_code == 201
        url = response.headers["Location"]
        assert (await client.get(url)).json()["id"] == user_id
        assert (await client.patch(url, json={"display_name": "Name"})).json()[
            "id"
        ] == user_id
        assert (await client.delete(url)).status_code == 204


def test_account_http_errors(tmp_path):
    path = tmp_path / "accounts.sqlite3"
    with TestClient(create_app(path)) as client:
        assert client.post("/users", json={"id": " "}).status_code == 422
        assert (
            client.patch("/users/admin", json={"display_name": None}).status_code == 422
        )
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
