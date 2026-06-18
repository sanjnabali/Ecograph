"""
api/errors.py - Centralised exception handlers and error response shapes
"""

import logging
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    error: str
    message: str
    detail: Optional[Any] = None


def _error(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(error=code, message=message, detail=detail).model_dump(
            exclude_none=True
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Call once in api/main.py to attach all exception handlers."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"field": ".".join(str(loc) for loc in e["loc"]), "msg": e["msg"]}
            for e in exc.errors()
        ]
        logger.warning(f"validation error on {request.url}: {errors}")
        return _error(
            422,
            "validation_error",
            "One or more request fields are invalid",
            detail=errors,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        logger.warning(f"ValueError on {request.url}: {exc}")
        return _error(400, "bad_request", str(exc))

    @app.exception_handler(PermissionError)
    async def permission_error_handler(
        request: Request, exc: PermissionError
    ) -> JSONResponse:
        logger.error(f"PermissionError on {request.url}: {exc}")
        return _error(503, "database_unavailable", str(exc))

    @app.exception_handler(ConnectionError)
    async def connection_error_handler(
        request: Request, exc: ConnectionError
    ) -> JSONResponse:
        logger.error(f"ConnectionError on {request.url}: {exc}")
        return _error(503, "database_unavailable", str(exc))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Catch-all: never leak stack traces to the client in production."""
        logger.exception(f"Unhandled error on {request.url}: {exc}")
        return _error(
            500,
            "internal_server_error",
            "An unexpected error occurred. Check server logs.",
        )