"""API errors carry a stable code. The client translates codes into messages."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status: int, code: str, detail: Any = None, headers: dict[str, str] | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers


def not_found() -> AppError:
    # Out-of-scope objects also get 404, so existence is not disclosed.
    return AppError(404, "not_found")


def conflict(current: Any) -> AppError:
    """Optimistic-lock failure (FR-AS7). The client shows the current state."""
    return AppError(409, "version_conflict", {"current": current})


def invalid(code: str, detail: Any = None) -> AppError:
    return AppError(422, code, detail)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    body: dict[str, Any] = {"code": exc.code}
    if exc.detail is not None:
        body["detail"] = exc.detail
    return JSONResponse({"error": body}, status_code=exc.status, headers=exc.headers)


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        {"field": ".".join(str(p) for p in err["loc"][1:]), "code": err["type"], "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse({"error": {"code": "validation_failed", "detail": fields}}, status_code=422)
