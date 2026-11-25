from http import HTTPStatus
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response

from ..models.accounts import Operator, OperatorAPI, User, UserAPI
from ..views.accounts import (
    OperatorRegisterRequest,
    OperatorView,
    UserCreateRequest,
    UserUpdateRequest,
    UserView,
)

users_router = APIRouter(prefix="/users", tags=["users"])
operators_router = APIRouter(prefix="/operators", tags=["operators"])


def get_user_api(request: Request) -> UserAPI:
    return request.app.state.user_api


def get_operator_api(request: Request) -> OperatorAPI:
    return request.app.state.operator_api


UserService = Annotated[UserAPI, Depends(get_user_api)]
OperatorService = Annotated[OperatorAPI, Depends(get_operator_api)]


@users_router.post("", response_model=UserView, status_code=HTTPStatus.CREATED)
def create_user(
    body: UserCreateRequest, response: Response, users: UserService
) -> User:
    user = users.create_user(body.id, body.display_name)
    # IDs are arbitrary text. Encode path separators and relative dot segments.
    user_id = quote(user["id"], safe="").replace(".", "%2E")
    response.headers["Location"] = f"/users/{user_id}"
    return user


@users_router.get("", response_model=list[UserView])
def list_users(users: UserService) -> list[User]:
    return users.list_users()


@users_router.get("/{user_id:path}", response_model=UserView)
def get_user(user_id: str, users: UserService) -> User:
    return users.get_user(user_id)


@users_router.patch("/{user_id:path}", response_model=UserView)
def update_user(user_id: str, body: UserUpdateRequest, users: UserService) -> User:
    return users.update_user(user_id, body.display_name)


@users_router.delete("/{user_id:path}", status_code=HTTPStatus.NO_CONTENT)
def delete_user(user_id: str, users: UserService) -> Response:
    users.delete_user(user_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@operators_router.post("", response_model=OperatorView, status_code=HTTPStatus.CREATED)
def register_operator(
    body: OperatorRegisterRequest, response: Response, operators: OperatorService
) -> Operator:
    operator = operators.register_operator(
        body.name, body.owner_user_id, mission=body.mission
    )
    response.headers["Location"] = f"/operators/{operator['id']}"
    return operator


@operators_router.get("", response_model=list[OperatorView])
def list_operators(
    operators: OperatorService, owner_user_id: str | None = None
) -> list[Operator]:
    return operators.list_operators(owner_user_id)


@operators_router.get("/{operator_id}", response_model=OperatorView)
def get_operator(operator_id: int, operators: OperatorService) -> Operator:
    return operators.get_operator(operator_id)


@operators_router.delete("/{operator_id}", status_code=HTTPStatus.NO_CONTENT)
def unregister_operator(operator_id: int, operators: OperatorService) -> Response:
    operators.unregister_operator(operator_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)
