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
SUPPORT_HEADER = "X-Support-Session"


@dataclass
class Principal:
    user: User
    session: UserSession
    # Set during an admin's read-only support view (FR-AD3): user is the person being viewed.
    support_admin: User | None = None

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
    support_id = request.headers.get(SUPPORT_HEADER)
    if support_id is not None:
        from app.admin import support  # imports scope helpers that use Principal

        # The admin stays the actor in the audit log; the answers are the viewed user's.
        viewed = support.resolve(db, user, support_id, request.method, request.url.path)
        return Principal(viewed, session, support_admin=user)
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
