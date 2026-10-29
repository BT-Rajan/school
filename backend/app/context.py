"""Per-request values that audit entries and logs need."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestContext:
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    actor_id: int | None = None
    actor_role: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def current() -> RequestContext:
    ctx = _current.get()
    if ctx is None:
        ctx = RequestContext()
        _current.set(ctx)
    return ctx


def set_context(ctx: RequestContext) -> None:
    _current.set(ctx)
