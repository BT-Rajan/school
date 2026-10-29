"""Sign-in, second factor, sessions, invitations and recovery (section 4).

Failed attempts commit their audit entry and counters before raising, so a
failure is never rolled back with the request.
"""

from dataclasses import dataclass
from datetime import timedelta

from argon2 import PasswordHasher
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import clock, context
from app.audit import service as audit
from app.config import get_settings
from app.district import get_district
from app.errors import AppError, invalid
from app.mail import queue as mail
from app.models import (
    AuthChallenge,
    ChallengePurpose,
    Invitation,
    MailPriority,
    MfaMethod,
    RecoveryCode,
    Role,
    User,
    UserSession,
    UserStatus,
)
from app.security import crypto, passwords, tokens, totp

from . import rate_limit

CODE_TTL = timedelta(minutes=10)
ENROLL_TTL = timedelta(minutes=30)
INVITATION_TTL = timedelta(hours=72)
LOCK_AFTER_FAILURES = 5
LOCK_DURATION = timedelta(minutes=15)
RECOVERY_CODE_COUNT = 10

CODE_TEMPLATES = {
    ChallengePurpose.LOGIN: "login_code",
    ChallengePurpose.PASSWORD_RESET: "password_reset_code",
}


@dataclass
class ChallengeIssued:
    token: str
    method: str
    expires_at: object


@dataclass
class TotpEnrollment:
    token: str
    secret: str
    uri: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def totp_required(db: Session, user: User) -> bool:
    return user.role in get_district(db).setting("totp_required_roles")


def _totp_context(user_id: int) -> str:
    return f"totp:{user_id}"


def _audit_user(db: Session, action: str, user: User | None, severity: str = "info", **after) -> None:
    audit.record(
        db,
        action,
        entity_type="user",
        entity_id=user.id if user else None,
        after=after or None,
        severity=severity,
        actor_id=user.id if user else None,
        actor_role=user.role if user else None,
    )


# Challenges -----------------------------------------------------------------


def _issue_challenge(
    db: Session,
    user: User,
    purpose: ChallengePurpose,
    method: str,
    pending_secret_enc: str | None = None,
) -> ChallengeIssued:
    token = tokens.new_token()
    challenge_id = tokens.sha256(token)
    ttl = ENROLL_TTL if purpose == ChallengePurpose.ENROLL_TOTP else CODE_TTL
    challenge = AuthChallenge(
        id=challenge_id,
        user_id=user.id,
        purpose=purpose,
        method=method,
        pending_secret_enc=pending_secret_enc,
        expires_at=clock.now() + ttl,
        created_at=clock.now(),
    )
    if method == MfaMethod.EMAIL:
        _send_code(db, user, challenge)
    db.add(challenge)
    db.flush()
    return ChallengeIssued(token, method, challenge.expires_at)


def _send_code(db: Session, user: User, challenge: AuthChallenge) -> None:
    ip = context.current().ip or "unknown"
    rate_limit.require(db, f"code:user:{user.id}", 3, timedelta(minutes=10))
    rate_limit.require(db, f"code:ip:{ip}", 30, timedelta(hours=1))
    code = tokens.new_numeric_code()
    challenge.code_hash = tokens.keyed_hash("code", challenge.id, code)
    mail.send_to_user(
        db, user, CODE_TEMPLATES[ChallengePurpose(challenge.purpose)], {"code": code}, MailPriority.SECURITY
    )
    _audit_user(db, "otp.issued", user, purpose=challenge.purpose)


def _load_challenge(db: Session, token: str, purpose: ChallengePurpose) -> tuple[AuthChallenge, User]:
    challenge = db.execute(
        select(AuthChallenge).where(AuthChallenge.id == tokens.sha256(token)).with_for_update()
    ).scalar_one_or_none()
    if (
        challenge is None
        or challenge.purpose != purpose
        or challenge.used_at is not None
        or challenge.expires_at <= clock.now()
    ):
        raise AppError(401, "challenge_invalid")
    user = db.execute(select(User).where(User.id == challenge.user_id).with_for_update()).scalar_one()
    if user.status == UserStatus.INACTIVE:
        raise AppError(401, "challenge_invalid")
    if user.is_locked():
        raise AppError(423, "account_locked", {"until": user.locked_until.isoformat()})
    return challenge, user


def _register_failure(db: Session, user: User, challenge: AuthChallenge | None, reason: str) -> None:
    if challenge is not None:
        challenge.attempts += 1
    user.failed_code_count += 1
    _audit_user(db, "otp.failed", user, severity="warning", reason=reason)
    if user.failed_code_count >= LOCK_AFTER_FAILURES:
        user.locked_until = clock.now() + LOCK_DURATION
        user.failed_code_count = 0
        _audit_user(db, "account.locked", user, severity="warning", until=user.locked_until)
    db.commit()
    raise AppError(401, "code_invalid")


def _check_totp(user: User, code: str, secret_enc: str | None = None, *, enrolling: bool = False) -> bool:
    secret_enc = secret_enc or user.totp_secret_enc
    if not secret_enc or not code:
        return False
    secret = crypto.decrypt(secret_enc, context=_totp_context(user.id))
    step = totp.matching_step(secret, code, None if enrolling else user.totp_last_step)
    if step is None:
        return False
    user.totp_last_step = step
    return True


def _use_recovery_code(db: Session, user: User, code: str) -> bool:
    code_hash = tokens.keyed_hash("recovery", str(user.id), tokens.normalize_recovery_code(code))
    row = db.execute(
        select(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.code_hash == code_hash, RecoveryCode.used_at.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        return False
    row.used_at = clock.now()
    _audit_user(db, "recovery_code.used", user, severity="warning")
    return True


def _verify_second_factor(
    db: Session,
    user: User,
    challenge: AuthChallenge | None,
    code: str | None,
    recovery_code: str | None,
) -> None:
    """Check the user's configured second factor, or a recovery code."""
    if recovery_code:
        if user.mfa_method == MfaMethod.TOTP and _use_recovery_code(db, user, recovery_code):
            return
        _register_failure(db, user, challenge, "recovery_code")
    if user.mfa_method == MfaMethod.TOTP:
        if _check_totp(user, code or ""):
            return
        _register_failure(db, user, challenge, "totp")
    # Email method: compare against the code sent for this challenge.
    expected = challenge.code_hash if challenge else None
    given = tokens.keyed_hash("code", challenge.id, (code or "").strip()) if challenge else ""
    if expected and tokens.constant_time_equal(expected, given):
        return
    _register_failure(db, user, challenge, "email_code")


def _succeed(db: Session, user: User, challenge: AuthChallenge) -> None:
    challenge.used_at = clock.now()
    user.failed_code_count = 0
    _audit_user(db, "otp.verified", user, purpose=challenge.purpose)


# Sessions -------------------------------------------------------------------


def create_session(db: Session, user: User) -> str:
    token = tokens.new_token()
    ctx = context.current()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=tokens.sha256(token),
            ip=ctx.ip,
            user_agent=(ctx.user_agent or "")[:400] or None,
            created_at=clock.now(),
            last_seen_at=clock.now(),
        )
    )
    db.flush()
    return token


def csrf_token_for(session_token: str) -> str:
    return tokens.keyed_hash("csrf", session_token)


def revoke_sessions(db: Session, user_id: int, reason: str, except_session_id: int | None = None) -> None:
    query = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id is not None:
        query = query.where(UserSession.id != except_session_id)
    db.execute(query.values(revoked_at=clock.now(), revoke_reason=reason))


def find_session(db: Session, token: str) -> tuple[UserSession, User] | None:
    session = db.execute(
        select(UserSession).where(UserSession.token_hash == tokens.sha256(token), UserSession.revoked_at.is_(None))
    ).scalar_one_or_none()
    if session is None:
        return None
    idle = timedelta(hours=int(get_district(db).setting("session_idle_hours")))
    if session.last_seen_at + idle < clock.now():
        session.revoked_at = clock.now()
        session.revoke_reason = "idle_timeout"
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    if clock.now() - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = clock.now()
        db.commit()
    return session, user


def session_still_valid(db: Session, session_id: int) -> bool:
    """For open live connections: still signed in, without counting as activity.

    A connected but untouched screen must not keep a session alive past its idle limit.
    """
    session = db.get(UserSession, session_id)
    if session is None or session.revoked_at is not None:
        return False
    idle = timedelta(hours=int(get_district(db).setting("session_idle_hours")))
    if session.last_seen_at + idle < clock.now():
        return False
    user = db.get(User, session.user_id)
    return user is not None and user.status == UserStatus.ACTIVE


# Login ----------------------------------------------------------------------


def start_login(db: Session, email: str, password: str) -> ChallengeIssued:
    email = normalize_email(email)
    ip = context.current().ip or "unknown"
    rate_limit.require(db, f"login:ip:{ip}", 50, timedelta(hours=1))
    rate_limit.require(db, f"login:email:{email}", 10, timedelta(minutes=15))
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    password_ok = passwords.verify_password(user.password_hash if user else None, password)
    if user is None or not password_ok or user.status != UserStatus.ACTIVE:
        audit.record(
            db,
            "login.failed",
            entity_type="user",
            entity_id=user.id if user else None,
            after={"reason": "bad_credentials" if not password_ok else "not_active"},
            severity="warning",
        )
        db.commit()
        raise AppError(401, "invalid_credentials")
    if user.is_locked():
        _audit_user(db, "login.locked", user, severity="warning")
        db.commit()
        raise AppError(423, "account_locked", {"until": user.locked_until.isoformat()})
    if PasswordHasher().check_needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    issued = _issue_challenge(db, user, ChallengePurpose.LOGIN, user.mfa_method)
    _audit_user(db, "login.password_ok", user, method=user.mfa_method)
    db.commit()
    return issued


def resend_login_code(db: Session, token: str) -> None:
    challenge, user = _load_challenge(db, token, ChallengePurpose.LOGIN)
    if challenge.method != MfaMethod.EMAIL:
        raise invalid("not_email_method")
    _send_code(db, user, challenge)
    challenge.expires_at = clock.now() + CODE_TTL
    db.commit()


def complete_login(db: Session, token: str, code: str | None, recovery_code: str | None) -> tuple[str, User]:
    challenge, user = _load_challenge(db, token, ChallengePurpose.LOGIN)
    _verify_second_factor(db, user, challenge, code, recovery_code)
    _succeed(db, user, challenge)
    session_token = create_session(db, user)
    user.last_login_at = clock.now()
    _audit_user(db, "login.succeeded", user, method="recovery_code" if recovery_code else user.mfa_method)
    db.commit()
    return session_token, user


def logout(db: Session, session: UserSession, user: User) -> None:
    session.revoked_at = clock.now()
    session.revoke_reason = "logout"
    _audit_user(db, "logout", user)
    db.commit()


# Password reset -------------------------------------------------------------


def request_password_reset(db: Session, email: str) -> str:
    """Always returns a token, so the response does not reveal whether the account exists."""
    email = normalize_email(email)
    ip = context.current().ip or "unknown"
    rate_limit.require(db, f"reset:ip:{ip}", 20, timedelta(hours=1))
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE:
        db.commit()
        return tokens.new_token()
    issued = _issue_challenge(db, user, ChallengePurpose.PASSWORD_RESET, MfaMethod.EMAIL)
    _audit_user(db, "password_reset.requested", user)
    db.commit()
    return issued.token


def complete_password_reset(
    db: Session,
    token: str,
    code: str,
    new_password: str,
    second_code: str | None = None,
    recovery_code: str | None = None,
) -> None:
    challenge, user = _load_challenge(db, token, ChallengePurpose.PASSWORD_RESET)
    given = tokens.keyed_hash("code", challenge.id, code.strip())
    if not challenge.code_hash or not tokens.constant_time_equal(challenge.code_hash, given):
        _register_failure(db, user, challenge, "reset_code")
    if user.mfa_method == MfaMethod.TOTP:
        # FR-A5: an authenticator user also proves the second factor.
        _verify_second_factor(db, user, None, second_code, recovery_code)
    problem = passwords.policy_problem(new_password, email=user.email, name=user.name)
    if problem:
        raise invalid(problem)
    _succeed(db, user, challenge)
    user.password_hash = passwords.hash_password(new_password)
    revoke_sessions(db, user.id, "password_reset")
    _audit_user(db, "password_reset.completed", user)
    db.commit()


def change_password(db: Session, user: User, session: UserSession, current: str, new_password: str) -> None:
    if not passwords.verify_password(user.password_hash, current):
        _audit_user(db, "password_change.failed", user, severity="warning")
        db.commit()
        raise AppError(401, "invalid_credentials")
    problem = passwords.policy_problem(new_password, email=user.email, name=user.name)
    if problem:
        raise invalid(problem)
    user.password_hash = passwords.hash_password(new_password)
    revoke_sessions(db, user.id, "password_changed", except_session_id=session.id)
    _audit_user(db, "password.changed", user)
    db.commit()


# Invitations ----------------------------------------------------------------


def create_invitation(db: Session, user: User, created_by: int | None, send_at=None) -> str:
    """Issue a single-use 72-hour invitation and queue its email (FR-T4)."""
    db.execute(
        update(Invitation)
        .where(Invitation.user_id == user.id, Invitation.used_at.is_(None), Invitation.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )
    token = tokens.new_token()
    start = send_at or clock.now()
    db.add(
        Invitation(
            user_id=user.id,
            token_hash=tokens.sha256(token),
            expires_at=start + INVITATION_TTL,
            created_by=created_by,
            created_at=clock.now(),
        )
    )
    district = get_district(db)
    mail.send_to_user(
        db,
        user,
        "invitation",
        {
            "name": user.name,
            "district": district.name_ar if user.locale == "ar" else district.name_en,
            "link": f"{get_settings().public_base_url}/invite/{token}",
        },
        MailPriority.INVITATION,
        scheduled_for=start,
    )
    audit.record(db, "invitation.created", entity_type="user", entity_id=user.id, after={"send_at": start})
    db.flush()
    return token


def _open_invitation(db: Session, token: str) -> tuple[Invitation, User]:
    invitation = db.execute(
        select(Invitation).where(Invitation.token_hash == tokens.sha256(token)).with_for_update()
    ).scalar_one_or_none()
    if (
        invitation is None
        or invitation.used_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= clock.now()
    ):
        raise AppError(404, "invitation_invalid")
    user = db.get(User, invitation.user_id)
    if user is None or user.status != UserStatus.INVITED:
        raise AppError(404, "invitation_invalid")
    return invitation, user


def describe_invitation(db: Session, token: str) -> dict:
    _, user = _open_invitation(db, token)
    return {"name": user.name, "email": user.email, "role": user.role, "totp_required": totp_required(db, user)}


def accept_invitation(db: Session, token: str, password: str, method: str) -> dict:
    invitation, user = _open_invitation(db, token)
    if method not in (MfaMethod.EMAIL, MfaMethod.TOTP):
        raise invalid("mfa_method_invalid")
    if method == MfaMethod.EMAIL and totp_required(db, user):
        raise invalid("totp_required")
    problem = passwords.policy_problem(password, email=user.email, name=user.name)
    if problem:
        raise invalid(problem)
    user.password_hash = passwords.hash_password(password)
    # Opening the emailed link proves the address (FR-A10).
    user.email_verified_at = clock.now()
    if method == MfaMethod.EMAIL:
        user.mfa_method = MfaMethod.EMAIL
        user.status = UserStatus.ACTIVE
        invitation.used_at = clock.now()
        session_token = create_session(db, user)
        _audit_user(db, "invitation.accepted", user, method=method)
        db.commit()
        return {"session": session_token, "user": user}
    # The invitation stays open until the authenticator is confirmed,
    # so a user who abandons enrollment can start again from the link.
    enrollment = _start_totp(db, user)
    _audit_user(db, "invitation.password_set", user)
    db.commit()
    return {"enrollment": enrollment}


# Authenticator enrollment ---------------------------------------------------


def _start_totp(db: Session, user: User) -> TotpEnrollment:
    secret = totp.new_secret()
    issued = _issue_challenge(
        db,
        user,
        ChallengePurpose.ENROLL_TOTP,
        MfaMethod.TOTP,
        pending_secret_enc=crypto.encrypt(secret, context=_totp_context(user.id)),
    )
    issuer = get_district(db).name_en
    return TotpEnrollment(issued.token, secret, totp.provisioning_uri(secret, account=user.email, issuer=issuer))


def start_totp_enrollment(db: Session, user: User, password: str) -> TotpEnrollment:
    if not passwords.verify_password(user.password_hash, password):
        _audit_user(db, "mfa.enroll_failed", user, severity="warning")
        db.commit()
        raise AppError(401, "invalid_credentials")
    enrollment = _start_totp(db, user)
    db.commit()
    return enrollment


def confirm_totp_enrollment(db: Session, token: str, code: str) -> dict:
    challenge, user = _load_challenge(db, token, ChallengePurpose.ENROLL_TOTP)
    if not _check_totp(user, code, challenge.pending_secret_enc, enrolling=True):
        _register_failure(db, user, challenge, "totp_enroll")
    _succeed(db, user, challenge)
    user.totp_secret_enc = challenge.pending_secret_enc
    user.mfa_method = MfaMethod.TOTP
    result: dict = {"user": user}
    if user.status == UserStatus.INVITED:
        user.status = UserStatus.ACTIVE
        db.execute(
            update(Invitation)
            .where(Invitation.user_id == user.id, Invitation.used_at.is_(None), Invitation.revoked_at.is_(None))
            .values(used_at=clock.now())
        )
        result["session"] = create_session(db, user)
        _audit_user(db, "invitation.accepted", user, method=MfaMethod.TOTP)
    else:
        _audit_user(db, "mfa.changed", user, method=MfaMethod.TOTP)
    result["recovery_codes"] = _new_recovery_codes(db, user)
    db.commit()
    return result


def _new_recovery_codes(db: Session, user: User) -> list[str]:
    db.execute(
        update(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        .values(used_at=clock.now())
    )
    codes = [tokens.new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        db.add(
            RecoveryCode(
                user_id=user.id,
                code_hash=tokens.keyed_hash("recovery", str(user.id), tokens.normalize_recovery_code(code)),
                created_at=clock.now(),
            )
        )
    _audit_user(db, "recovery_codes.generated", user)
    db.flush()
    return codes


def _reauthenticate(db: Session, user: User, password: str, code: str) -> None:
    if not passwords.verify_password(user.password_hash, password):
        _audit_user(db, "reauth.failed", user, severity="warning")
        db.commit()
        raise AppError(401, "invalid_credentials")
    if user.mfa_method == MfaMethod.TOTP and not _check_totp(user, code):
        _register_failure(db, user, None, "reauth_totp")


def regenerate_recovery_codes(db: Session, user: User, password: str, code: str) -> list[str]:
    if user.mfa_method != MfaMethod.TOTP:
        raise invalid("not_totp_method")
    _reauthenticate(db, user, password, code)
    codes = _new_recovery_codes(db, user)
    db.commit()
    return codes


def switch_to_email(db: Session, user: User, password: str, code: str) -> None:
    if totp_required(db, user):
        raise invalid("totp_required")
    if user.mfa_method == MfaMethod.EMAIL:
        return
    _reauthenticate(db, user, password, code)
    _clear_totp(db, user)
    _audit_user(db, "mfa.changed", user, method=MfaMethod.EMAIL)
    db.commit()


def _clear_totp(db: Session, user: User) -> None:
    user.mfa_method = MfaMethod.EMAIL
    user.totp_secret_enc = None
    user.totp_last_step = None
    db.execute(
        update(RecoveryCode)
        .where(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        .values(used_at=clock.now())
    )


# Administration -------------------------------------------------------------


def admin_unlock(db: Session, target: User) -> None:
    target.locked_until = None
    target.failed_code_count = 0
    audit.record(db, "account.unlocked", entity_type="user", entity_id=target.id)
    db.commit()


def admin_reset_mfa(db: Session, target: User) -> None:
    """Reset a user to emailed codes after a lost phone (FR-A15)."""
    _clear_totp(db, target)
    target.locked_until = None
    target.failed_code_count = 0
    revoke_sessions(db, target.id, "mfa_reset")
    audit.record(db, "mfa.reset_by_admin", entity_type="user", entity_id=target.id, severity="warning")
    mail.send_to_user(db, target, "mfa_reset_notice", {}, MailPriority.SECURITY)
    db.commit()


def break_glass_reset(db: Session, email: str) -> int:
    """Server-side emergency reset of a user's second factor (FR-A9)."""
    target = db.execute(select(User).where(User.email == normalize_email(email))).scalar_one_or_none()
    if target is None:
        raise AppError(404, "not_found")
    _clear_totp(db, target)
    target.locked_until = None
    target.failed_code_count = 0
    revoke_sessions(db, target.id, "break_glass")
    entry = audit.record(
        db,
        "break_glass.mfa_reset",
        entity_type="user",
        entity_id=target.id,
        severity="critical",
        actor_id=None,
        actor_role="server_cli",
    )
    others = db.execute(
        select(User).where(User.role == Role.DISTRICT_ADMIN, User.status == UserStatus.ACTIVE, User.id != target.id)
    ).scalars()
    for admin in others:
        mail.send_to_user(
            db, admin, "break_glass_notice", {"target": target.email, "seq": entry.seq}, MailPriority.SECURITY
        )
    mail.send_to_user(db, target, "mfa_reset_notice", {}, MailPriority.SECURITY)
    db.commit()
    return entry.seq
