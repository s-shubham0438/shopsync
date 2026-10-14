"""Domain exceptions and the handlers that render them as the error envelope.

Services raise ``AppError`` subclasses; they never import FastAPI's
HTTPException. Handlers here translate everything (including framework
validation and routing errors) into ``ErrorResponse``.
"""

from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx
from app.schemas.common import ErrorBody, ErrorDetail, ErrorResponse


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: list[ErrorDetail] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Resource already exists."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication required."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please try again later."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Service temporarily unavailable."


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, details=details, request_id=request_id_ctx.get()
        )
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True), status_code=status_code, headers=headers
    )


def _status_code_slug(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    except ValueError:
        return "error"


async def _handle_app_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppError, exc)
    return error_response(
        exc.status_code, exc.code, exc.message, details=exc.details, headers=exc.headers
    )


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(RequestValidationError, exc)
    # Deliberately omit the rejected `input`: it may contain passwords or tokens.
    errors: list[dict[str, Any]] = list(exc.errors())
    details = [
        ErrorDetail(loc=list(err.get("loc", ())), message=err["msg"], type=err.get("type"))
        for err in errors
    ]
    return error_response(422, "validation_error", "Request validation failed.", details=details)


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(
        exc.status_code,
        _status_code_slug(exc.status_code),
        message,
        headers=dict(exc.headers) if exc.headers else None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    # Unhandled exceptions are caught in RequestContextMiddleware so the 500
    # response still carries the request id and CORS headers.
