"""Uniform JSON error responses: {"code": str, "field": str | None, "message": str}."""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

SOURCE_SEGMENTS = {"body", "query", "path", "header", "cookie"}


class ApiError(Exception):
    """An error with an HTTP status and a stable, machine-readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
        field: str | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message or code.replace("_", " ").capitalize()
        self.field = field
        super().__init__(self.message)


def _response(
    status_code: int,
    code: str,
    message: str,
    field: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"code": code, "field": field, "message": message},
        status_code=status_code,
        headers=headers,
    )


def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _response(exc.status_code, exc.code, exc.message, exc.field)


def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    error = exc.errors()[0]
    loc = list(error["loc"])
    if error["type"] == "json_invalid":
        loc = []
    elif loc and loc[0] in SOURCE_SEGMENTS:
        loc = loc[1:]
    field = ".".join(str(part) for part in loc) or None
    return _response(422, "VALIDATION_FAILED", error["msg"], field)


def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    phrase = HTTPStatus(exc.status_code).phrase
    code = phrase.upper().replace("'", "").replace(" ", "_").replace("-", "_")
    message = exc.detail if isinstance(exc.detail, str) and exc.detail else phrase
    return _response(exc.status_code, code, message, headers=exc.headers)


def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", exc_info=exc)
    return _response(500, "INTERNAL_ERROR", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    """Make every error response use the uniform JSON shape."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
