"""Request authentication, CSRF protection and role checks."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app import context
from app.audit import service as audit
from app.db import get_db
from app.errors import AppError
from app.models import Role, User, UserSession
from app.security import tokens

from . import service

SESSION_COOKIE = "sces_session"
CSRF_COOKIE = "sces_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    user: User
    session: UserSession

    @property
    def role(self) -> Role:
        return Role(self.user.role)


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    found = service.find_session(db, token) if token else None
    if found is None:
        raise AppError(401, "not_authenticated")
    session, user = found
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not tokens.constant_time_equal(sent, service.csrf_token_for(token)):
            raise AppError(403, "csrf_failed")
    ctx = context.current()
    ctx.actor_id = user.id
    ctx.actor_role = user.role
    return Principal(user, session)


def require_roles(*roles: Role) -> Callable[..., Principal]:
    allowed = {Role(r) for r in roles}

    def dependency(request: Request, principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed:
            audit.record_denial(f"{request.method} {request.url.path}", reason="role")
            raise AppError(403, "forbidden")
        return principal

    return dependency


admin_only = require_roles(Role.DISTRICT_ADMIN)
structure_managers = require_roles(Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD)
