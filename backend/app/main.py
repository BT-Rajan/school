import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import context
from app.api import auth, imports, reference, structure, system, users
from app.auth.deps import SESSION_COOKIE
from app.auth.rate_limit import api_limiter
from app.config import get_settings
from app.errors import AppError, app_error_handler, validation_error_handler
from app.logging_setup import configure_logging
from app.security import tokens

log = logging.getLogger(__name__)


def _client_ip(request: Request) -> str | None:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    dev = settings.environment == "development"
    app = FastAPI(
        title="School Cluster Evaluation System",
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        ip = _client_ip(request)
        context.set_context(
            context.RequestContext(request_id=request_id[:64], ip=ip, user_agent=request.headers.get("user-agent"))
        )
        session = request.cookies.get(SESSION_COOKIE)
        if not api_limiter.allow(f"ip:{ip}", settings.rate_limit_ip_per_minute) or (
            session and not api_limiter.allow(f"session:{tokens.sha256(session)}", settings.rate_limit_user_per_minute)
        ):
            return JSONResponse({"error": {"code": "rate_limited"}}, status_code=429, headers={"Retry-After": "60"})
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": request_id})
            response = JSONResponse({"error": {"code": "internal_error"}}, status_code=500)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers.setdefault("Cache-Control", "no-store")
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith("/api") and not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    for module in (system, auth, users, structure, reference, imports):
        app.include_router(module.router)
    return app


app = create_app()
