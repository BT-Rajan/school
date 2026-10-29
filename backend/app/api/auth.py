from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.audit import service as audit
from app.auth import service
from app.auth.deps import CSRF_COOKIE, SESSION_COOKIE, Principal, current_principal
from app.config import get_settings
from app.db import get_db
from app.errors import invalid, not_found
from app.models import User, UserSession
from app.security.passwords import MIN_LENGTH

router = APIRouter(prefix="/api/auth", tags=["auth"])


class MeOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    locale: str
    mfa_method: str
    totp_required: bool


def me_out(db: Session, user: User) -> MeOut:
    return MeOut(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        locale=user.locale,
        mfa_method=user.mfa_method,
        totp_required=service.totp_required(db, user),
    )


def set_session_cookies(response: Response, session_token: str) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(SESSION_COOKIE, session_token, httponly=True, secure=secure, samesite="strict", path="/api")
    # Readable by the client, which echoes it in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE, service.csrf_token_for(session_token), httponly=False, secure=secure, samesite="strict", path="/"
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/api")
    response.delete_cookie(CSRF_COOKIE, path="/")


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class ChallengeOut(BaseModel):
    challenge: str
    method: str
    expires_at: datetime


@router.post("/login", response_model=ChallengeOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    issued = service.start_login(db, body.email, body.password)
    return ChallengeOut(challenge=issued.token, method=issued.method, expires_at=issued.expires_at)


class VerifyIn(BaseModel):
    challenge: str = Field(max_length=100)
    code: str | None = Field(default=None, max_length=20)
    recovery_code: str | None = Field(default=None, max_length=20)


@router.post("/login/verify", response_model=MeOut)
def login_verify(body: VerifyIn, response: Response, db: Session = Depends(get_db)):
    if not body.code and not body.recovery_code:
        raise invalid("code_required")
    session_token, user = service.complete_login(db, body.challenge, body.code, body.recovery_code)
    set_session_cookies(response, session_token)
    return me_out(db, user)


class ChallengeIn(BaseModel):
    challenge: str = Field(max_length=100)


@router.post("/login/resend", status_code=204)
def login_resend(body: ChallengeIn, db: Session = Depends(get_db)):
    service.resend_login_code(db, body.challenge)


@router.post("/logout", status_code=204)
def logout(response: Response, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    session = db.get(UserSession, principal.session.id)
    service.logout(db, session, db.get(User, principal.user.id))
    clear_session_cookies(response)


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return me_out(db, principal.user)


class MeUpdateIn(BaseModel):
    locale: str = Field(pattern="^(en|ar)$")


@router.patch("/me", response_model=MeOut)
def update_me(body: MeUpdateIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = db.get(User, principal.user.id)
    user.locale = body.locale
    db.commit()
    return me_out(db, user)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChangeIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    service.change_password(
        db, db.get(User, principal.user.id), principal.session, body.current_password, body.new_password
    )


class SessionOut(BaseModel):
    id: int
    created_at: datetime
    last_seen_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.execute(
        select(UserSession)
        .where(UserSession.user_id == principal.user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    ).scalars()
    return [
        SessionOut(
            id=s.id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            ip=s.ip,
            user_agent=s.user_agent,
            current=s.id == principal.session.id,
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != principal.user.id or session.revoked_at is not None:
        raise not_found()
    session.revoked_at = clock.now()
    session.revoke_reason = "revoked_by_user"
    audit.record(db, "session.revoked", entity_type="session", entity_id=session.id)
    db.commit()


class ResetRequestIn(BaseModel):
    email: EmailStr


@router.post("/password-reset/request", response_model=ChallengeIn)
def password_reset_request(body: ResetRequestIn, db: Session = Depends(get_db)):
    return ChallengeIn(challenge=service.request_password_reset(db, body.email))


class ResetCompleteIn(BaseModel):
    challenge: str = Field(max_length=100)
    code: str = Field(max_length=20)
    new_password: str = Field(max_length=200)
    second_code: str | None = Field(default=None, max_length=20)
    recovery_code: str | None = Field(default=None, max_length=20)


@router.post("/password-reset/complete", status_code=204)
def password_reset_complete(body: ResetCompleteIn, db: Session = Depends(get_db)):
    service.complete_password_reset(
        db, body.challenge, body.code, body.new_password, body.second_code, body.recovery_code
    )


class InvitationOut(BaseModel):
    name: str
    email: str
    role: str
    totp_required: bool


@router.get("/invitations/{token}", response_model=InvitationOut)
def invitation(token: str, db: Session = Depends(get_db)):
    return InvitationOut(**service.describe_invitation(db, token))


class AcceptIn(BaseModel):
    password: str = Field(max_length=200)
    method: str = Field(pattern="^(email|totp)$")


class EnrollmentOut(BaseModel):
    challenge: str
    secret: str
    otpauth_uri: str


class AcceptOut(BaseModel):
    me: MeOut | None = None
    enrollment: EnrollmentOut | None = None


@router.post("/invitations/{token}/accept", response_model=AcceptOut)
def accept_invitation(token: str, body: AcceptIn, response: Response, db: Session = Depends(get_db)):
    result = service.accept_invitation(db, token, body.password, body.method)
    if "session" in result:
        set_session_cookies(response, result["session"])
        return AcceptOut(me=me_out(db, result["user"]))
    enrollment = result["enrollment"]
    return AcceptOut(
        enrollment=EnrollmentOut(challenge=enrollment.token, secret=enrollment.secret, otpauth_uri=enrollment.uri)
    )


class PasswordIn(BaseModel):
    password: str = Field(max_length=200)


@router.post("/mfa/totp/start", response_model=EnrollmentOut)
def totp_start(body: PasswordIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    enrollment = service.start_totp_enrollment(db, db.get(User, principal.user.id), body.password)
    return EnrollmentOut(challenge=enrollment.token, secret=enrollment.secret, otpauth_uri=enrollment.uri)


class ConfirmIn(BaseModel):
    challenge: str = Field(max_length=100)
    code: str = Field(max_length=20)


class ConfirmOut(BaseModel):
    me: MeOut
    recovery_codes: list[str]


@router.post("/mfa/totp/confirm", response_model=ConfirmOut)
def totp_confirm(body: ConfirmIn, response: Response, db: Session = Depends(get_db)):
    """Confirms enrollment, both from an invitation and when switching methods."""
    result = service.confirm_totp_enrollment(db, body.challenge, body.code)
    if "session" in result:
        set_session_cookies(response, result["session"])
    return ConfirmOut(me=me_out(db, result["user"]), recovery_codes=result["recovery_codes"])


class ReauthIn(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field(default="", max_length=20)


@router.post("/mfa/recovery-codes", response_model=list[str])
def recovery_codes(body: ReauthIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return service.regenerate_recovery_codes(db, db.get(User, principal.user.id), body.password, body.code)


@router.post("/mfa/email", response_model=MeOut)
def switch_to_email(body: ReauthIn, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = db.get(User, principal.user.id)
    service.switch_to_email(db, user, body.password, body.code)
    return me_out(db, user)


@router.get("/password-policy")
def password_policy():
    return {"min_length": MIN_LENGTH}
