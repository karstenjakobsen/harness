from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .controllers.goals import router
from .models.goals import (
    DATABASE_PATH,
    GoalAPI,
    GoalConflictError,
    GoalNotFoundError,
    GoalStorageError,
    GoalValidationError,
)


def create_app(database_path: Path | str = DATABASE_PATH) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.goal_api = GoalAPI(database_path)
        yield

    api = FastAPI(title="Harness API", lifespan=lifespan)
    api.include_router(router)

    @api.exception_handler(GoalNotFoundError)
    def goal_not_found(_request: Request, error: GoalNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND,
            content={"detail": str(error)},
        )

    @api.exception_handler(GoalValidationError)
    def invalid_goal(_request: Request, error: GoalValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            content={"detail": str(error)},
        )

    @api.exception_handler(GoalConflictError)
    def goal_conflict(_request: Request, error: GoalConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.CONFLICT, content={"detail": str(error)}
        )

    @api.exception_handler(GoalStorageError)
    def goal_storage_unavailable(
        _request: Request, error: GoalStorageError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            content={"detail": str(error)},
        )

    return api


app = create_app()
