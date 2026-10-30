from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.admin import audit_viewer, person_export, support
from app.admin.audit_viewer import AuditFilters
from app.admin.support import StartIn
from app.auth.deps import Principal, admin_only
from app.db import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

FAILED_SIGN_INS = ("login.failed", "login.locked", "otp.failed", "account.locked", "password_change.failed")


@router.get("/audit")
def audit_log(
    filters: AuditFilters = Depends(),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: Principal = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """FR-L5: search and filter the audit log."""
    return audit_viewer.search(db, filters, page, page_size)


@router.get("/audit/export")
def audit_export(
    filters: AuditFilters = Depends(),
    format: Literal["csv", "xlsx"] = "xlsx",
    locale: Literal["en", "ar"] = "en",
    principal: Principal = Depends(admin_only),
    db: Session = Depends(get_db),
):
    body, media = audit_viewer.export(db, filters, format, locale, principal.user)
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="audit-log.{format}"'}
    )


@router.get("/failed-sign-ins")
def failed_sign_ins(
    days: int = Query(default=7, ge=1, le=90), _: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    """FR-AD2: recent failed sign-ins and lockouts, newest first."""
    rows = list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.action.in_(FAILED_SIGN_INS), AuditLog.created_at >= clock.now() - timedelta(days=days))
            .order_by(AuditLog.seq.desc())
            .limit(200)
        ).scalars()
    )
    ids = {int(e.entity_id) for e in rows if e.entity_type == "user" and e.entity_id and e.entity_id.isdigit()}
    users = {u.id: u for u in db.execute(select(User).where(User.id.in_(ids))).scalars()} if ids else {}
    out = []
    for e in rows:
        user = users.get(int(e.entity_id)) if e.entity_id and e.entity_id.isdigit() else None
        out.append(
            {
                "at": e.created_at,
                "action": e.action,
                "user": {"id": user.id, "name": user.name, "email": user.email} if user else None,
                "reason": (e.after or {}).get("reason"),
                "ip": e.ip,
            }
        )
    return out


@router.get("/support-users")
def support_users(
    q: str = Query(min_length=1, max_length=100), _: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    return support.find_users(db, q)


@router.get("/support-sessions")
def my_support_sessions(principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return support.mine(db, principal.user)


@router.post("/support-sessions", status_code=201)
def start_support(body: StartIn, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return support.session_out(db, support.start(db, principal.user, body))


@router.post("/support-sessions/{session_id}/end")
def end_support(session_id: int, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return support.session_out(db, support.end(db, principal.user, session_id))


@router.get("/users/{user_id}/export")
def person_data(user_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    """FR-AD4: everything held about one person."""
    body = person_export.export_and_audit(db, user_id)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="person-{user_id}.json"'},
    )
