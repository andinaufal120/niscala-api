"""Declares the errors of every operation in the generated OpenAPI document."""

from http import HTTPStatus

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.error_catalog import ERROR_STATUS, ROUTE_ERRORS
from app.errors import ErrorBody

ERROR_BODY_REF = "#/components/schemas/ErrorBody"
DEFAULT_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")
HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


def _error_response(status: int, codes: list[str]) -> dict:
    phrase = HTTPStatus(status).phrase
    return {
        "description": f"{phrase}: {', '.join(codes)}",
        "content": {"application/json": {"schema": {"$ref": ERROR_BODY_REF}}},
    }


def _declare_errors(document: dict) -> None:
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            codes = sorted(
                ROUTE_ERRORS[(method.upper(), path)],
                key=lambda code: (ERROR_STATUS[code], code),
            )
            operation["x-error-codes"] = codes
            responses = operation["responses"]
            # The framework's own validation error is replaced by the uniform body.
            responses.pop("422", None)
            for status in sorted({ERROR_STATUS[code] for code in codes}):
                at_status = [c for c in codes if ERROR_STATUS[c] == status]
                responses[str(status)] = _error_response(status, at_status)


def _fix_schemas(document: dict) -> None:
    schemas = document["components"]["schemas"]
    for name in DEFAULT_VALIDATION_SCHEMAS:
        schemas.pop(name, None)
    if "ErrorBody" not in schemas:
        schemas["ErrorBody"] = ErrorBody.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )


def install_openapi(app: FastAPI) -> None:
    """Make `app.openapi()` return the document with the error declarations."""

    def build() -> dict:
        if app.openapi_schema is None:
            document = get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                summary=app.summary,
                description=app.description,
                routes=app.routes,
                webhooks=app.webhooks.routes,
                tags=app.openapi_tags,
                servers=app.servers,
            )
            _declare_errors(document)
            _fix_schemas(document)
            app.openapi_schema = document
        return app.openapi_schema

    app.openapi = build
