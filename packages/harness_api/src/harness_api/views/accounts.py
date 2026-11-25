from pydantic import BaseModel, ConfigDict


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str | None = None


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str


class UserView(BaseModel):
    id: str
    display_name: str
    created_at: str
    deleted_at: str | None


class OperatorRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    owner_user_id: str | None = None
    mission: str | None = None


class OperatorView(BaseModel):
    id: int
    owner_user_id: str
    name: str
    mission: str | None
    created_at: str
    deleted_at: str | None
