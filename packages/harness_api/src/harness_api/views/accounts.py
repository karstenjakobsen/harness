from pydantic import BaseModel, ConfigDict

from . import PositiveInteger


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    display_name: str | None = None


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str


class UserView(BaseModel):
    id: int
    username: str
    display_name: str
    created_at: str
    deleted_at: str | None


class OperatorRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    owner_user_id: PositiveInteger | None = None
    mission: str | None = None


class OperatorView(BaseModel):
    id: int
    owner_user_id: int
    name: str
    mission: str | None
    created_at: str
    deleted_at: str | None
