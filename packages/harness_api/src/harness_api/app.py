from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .controllers.accounts import operators_router, users_router
from .controllers.goals import router as goals_router
from .controllers.runs import router as runs_router
from .controllers.skills import router as skills_router
from .database import DATABASE_PATH, WorkspaceStorageError
from .models.accounts import (
    AccountConflictError,
    AccountNotFoundError,
    AccountValidationError,
    OperatorAPI,
    UserAPI,
)
from .models.activity import RunNotFoundError
from .models.goals import (
    GoalAPI,
    GoalConflictError,
    GoalNotFoundError,
    GoalValidationError,
)
from .models.skills import SkillAPI, SkillNotFoundError, SkillValidationError


def create_app(database_path: Path | str = DATABASE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.goal_api = GoalAPI(database_path, local_owner=False)
        app.state.skill_api = SkillAPI(database_path)
        app.state.user_api = UserAPI(database_path)
        app.state.operator_api = OperatorAPI(database_path)
        yield

    api = FastAPI(title="Harness API", lifespan=lifespan)
    api.include_router(goals_router)
    api.include_router(users_router)
    api.include_router(operators_router)
    api.include_router(runs_router)
    api.include_router(skills_router)

    @api.exception_handler(SkillNotFoundError)
    @api.exception_handler(GoalNotFoundError)
    @api.exception_handler(AccountNotFoundError)
    @api.exception_handler(RunNotFoundError)
    def not_found(
        _request: Request,
        error: GoalNotFoundError
        | AccountNotFoundError
        | RunNotFoundError
        | SkillNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"detail": str(error)},
        )

    @api.exception_handler(SkillValidationError)
    @api.exception_handler(GoalValidationError)
    @api.exception_handler(AccountValidationError)
    def invalid_input(
        _request: Request,
        error: GoalValidationError | AccountValidationError | SkillValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            content={"detail": str(error)},
        )

    @api.exception_handler(GoalConflictError)
    @api.exception_handler(AccountConflictError)
    def conflict(
        _request: Request, error: GoalConflictError | AccountConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.CONFLICT, content={"detail": str(error)}
        )

    @api.exception_handler(WorkspaceStorageError)
    def storage_unavailable(
        _request: Request, error: WorkspaceStorageError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            content={"detail": str(error)},
        )

    return api


app = create_app()
