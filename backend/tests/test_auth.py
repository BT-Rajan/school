from datetime import timedelta

import pyotp
from sqlalchemy import select

from app import clock
from app.auth import service as auth
from app.db import session_factory
from app.models import AuditLog, AuthChallenge, MailMessage, MfaMethod, Role, User, UserSession, UserStatus
from app.security import tokens, totp
from app.security.passwords import policy_problem

from .helpers import PASSWORD, csrf, deliver_mail, last_code, login, make_user, signed_in, user_by_email


def _start(client, email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_email_code_login(client, outbox):
    make_user(Role.CLUSTER_HEAD, "head@example.org")
    me = login(client, outbox, "head@example.org")
    assert me["role"] == "cluster_head"
    assert client.get("/api/auth/me").json()["email"] == "head@example.org"
    actions = [a for (a,) in _audit_actions()]
    assert {"login.password_ok", "otp.issued", "otp.verified", "login.succeeded"} <= set(actions)


def test_wrong_password_and_unknown_email_look_the_same(client, outbox):
    make_user(Role.TEACHER, "t@example.org")
    a = _start(client, "t@example.org", "wrong password!!")
    b = _start(client, "nobody@example.org", "wrong password!!")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"error": {"code": "invalid_credentials"}}


def test_lockout_after_five_bad_codes(client, outbox):
    """A locked account cannot sign in, even with the correct password and code."""
    make_user(Role.TEACHER, "t@example.org")
    challenge = _start(client, "t@example.org").json()["challenge"]
    for _ in range(4):
        r = client.post("/api/auth/login/verify", json={"challenge": challenge, "code": "000000"})
        assert r.json()["error"]["code"] == "code_invalid"
    r = client.post("/api/auth/login/verify", json={"challenge": challenge, "code": "000000"})
    assert r.status_code == 401
    r = _start(client, "t@example.org")
    assert r.status_code == 423 and r.json()["error"]["code"] == "account_locked"
    # After 15 minutes the lock lifts.
    clock.freeze(clock.now() + timedelta(minutes=16))
    assert _start(client, "t@example.org").status_code == 200


def test_admin_unlocks_a_locked_account(client, new_client, outbox):
    """Section 18: locked until unlocked; an admin's unlock is audited and works at once."""
    admin, _ = signed_in(new_client, outbox, Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    user, _ = make_user(Role.TEACHER, "t@example.org")
    challenge = _start(client, "t@example.org").json()["challenge"]
    for _ in range(5):
        client.post("/api/auth/login/verify", json={"challenge": challenge, "code": "000000"})
    assert _start(client, "t@example.org").status_code == 423
    locked = admin.get("/api/admin/locked-accounts").json()
    assert [u["email"] for u in locked] == ["t@example.org"]
    assert admin.post(f"/api/users/{user.id}/unlock").status_code == 204
    assert _start(client, "t@example.org").status_code == 200
    with session_factory()() as db:
        assert db.execute(select(AuditLog).where(AuditLog.action.like("%unlock%"))).first()


def test_code_requests_are_rate_limited(client, outbox):
    make_user(Role.TEACHER, "t@example.org")
    for _ in range(3):
        assert _start(client, "t@example.org").status_code == 200
    r = _start(client, "t@example.org")
    assert r.status_code == 429


def test_code_is_single_use_and_expires(client, outbox):
    make_user(Role.TEACHER, "t@example.org")
    challenge = _start(client, "t@example.org").json()["challenge"]
    code = last_code(outbox, "t@example.org")
    clock.freeze(clock.now() + timedelta(minutes=11))
    r = client.post("/api/auth/login/verify", json={"challenge": challenge, "code": code})
    assert r.json()["error"]["code"] == "challenge_invalid"
    clock.freeze(None)
    challenge = _start(client, "t@example.org").json()["challenge"]
    code = last_code(outbox, "t@example.org")
    assert client.post("/api/auth/login/verify", json={"challenge": challenge, "code": code}).status_code == 200
    r = client.post("/api/auth/login/verify", json={"challenge": challenge, "code": code})
    assert r.json()["error"]["code"] == "challenge_invalid"


def test_codes_are_stored_hashed(client, outbox, db):
    make_user(Role.TEACHER, "t@example.org")
    _start(client, "t@example.org")
    code = last_code(outbox, "t@example.org")
    challenge = db.execute(select(AuthChallenge)).scalar_one()
    assert code not in (challenge.code_hash or "")
    # The queued mail no longer holds the code once sent.
    assert all(m.context is None for m in db.execute(select(MailMessage)).scalars())


def test_authenticator_login_and_replay_rejected(client, outbox, new_client):
    _, secret = make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    challenge = _start(client, "admin@example.org").json()
    assert challenge["method"] == "totp"
    code = pyotp.TOTP(secret).now()
    assert (
        client.post("/api/auth/login/verify", json={"challenge": challenge["challenge"], "code": code}).status_code
        == 200
    )
    # Reusing the same code within its window fails.
    other = new_client()
    second = _start(other, "admin@example.org").json()["challenge"]
    r = other.post("/api/auth/login/verify", json={"challenge": second, "code": code})
    assert r.json()["error"]["code"] == "code_invalid"
    # No login email was sent to an authenticator user.
    deliver_mail()
    assert not [m for m in outbox if m.to == "admin@example.org"]


def test_invitation_with_email_method(client, outbox, new_client):
    admin, secret = make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP, staff_id="A1")
    login(client, outbox, "admin@example.org", secret=secret)
    r = client.post("/api/cluster-heads", json={"staff_id": "CH1", "name": "Head One", "email": "head@example.org"})
    assert r.status_code == 201, r.text
    deliver_mail()
    invite = next(m for m in outbox if m.to == "head@example.org")
    token = invite.text.split("/invite/")[1].split()[0]

    browser = new_client()
    info = browser.get(f"/api/auth/invitations/{token}").json()
    assert info == {"name": "Head One", "email": "head@example.org", "role": "cluster_head", "totp_required": False}
    weak = browser.post(f"/api/auth/invitations/{token}/accept", json={"password": "short", "method": "email"})
    assert weak.json()["error"]["code"] == "password_too_short"
    r = browser.post(f"/api/auth/invitations/{token}/accept", json={"password": PASSWORD, "method": "email"})
    assert r.status_code == 200 and r.json()["me"]["role"] == "cluster_head"
    assert user_by_email("head@example.org").email_verified_at is not None
    # Single use.
    again = new_client().get(f"/api/auth/invitations/{token}")
    assert again.status_code == 404


def test_invitation_expires_after_72_hours(client, outbox, new_client):
    _, secret = make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    login(client, outbox, "admin@example.org", secret=secret)
    client.post("/api/cluster-heads", json={"staff_id": "CH1", "name": "Head", "email": "head@example.org"})
    deliver_mail()
    token = next(m for m in outbox if m.to == "head@example.org").text.split("/invite/")[1].split()[0]
    clock.freeze(clock.now() + timedelta(hours=73))
    assert new_client().get(f"/api/auth/invitations/{token}").status_code == 404


def test_admin_invitation_requires_authenticator_and_issues_recovery_codes(client, outbox, new_client):
    _, secret = make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    login(client, outbox, "admin@example.org", secret=secret)
    client.post("/api/admins", json={"staff_id": "A2", "name": "Second Admin", "email": "admin2@example.org"})
    deliver_mail()
    token = next(m for m in outbox if m.to == "admin2@example.org").text.split("/invite/")[1].split()[0]
    browser = new_client()
    r = browser.post(f"/api/auth/invitations/{token}/accept", json={"password": PASSWORD, "method": "email"})
    assert r.json()["error"]["code"] == "totp_required"
    r = browser.post(f"/api/auth/invitations/{token}/accept", json={"password": PASSWORD, "method": "totp"})
    enrollment = r.json()["enrollment"]
    assert enrollment["otpauth_uri"].startswith("otpauth://totp/")
    # Abandoning and restarting from the same link works until enrollment is confirmed.
    r = browser.post(f"/api/auth/invitations/{token}/accept", json={"password": PASSWORD, "method": "totp"})
    enrollment = r.json()["enrollment"]
    bad = browser.post("/api/auth/mfa/totp/confirm", json={"challenge": enrollment["challenge"], "code": "123456"})
    assert bad.status_code == 401
    code = pyotp.TOTP(enrollment["secret"]).now()
    r = browser.post("/api/auth/mfa/totp/confirm", json={"challenge": enrollment["challenge"], "code": code})
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10
    assert user_by_email("admin2@example.org").status == UserStatus.ACTIVE

    # A recovery code works once.
    fresh = new_client()
    challenge = _start(fresh, "admin2@example.org").json()["challenge"]
    assert (
        fresh.post("/api/auth/login/verify", json={"challenge": challenge, "recovery_code": codes[0]}).status_code
        == 200
    )
    again = new_client()
    challenge = _start(again, "admin2@example.org").json()["challenge"]
    r = again.post("/api/auth/login/verify", json={"challenge": challenge, "recovery_code": codes[0]})
    assert r.json()["error"]["code"] == "code_invalid"


def test_admin_resets_lost_authenticator(client, outbox, new_client):
    _, secret = make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    target, target_secret = make_user(Role.SUPERVISOR, "sup@example.org", mfa=MfaMethod.TOTP)
    sup_browser = new_client()
    login(sup_browser, outbox, "sup@example.org", secret=target_secret)
    login(client, outbox, "admin@example.org", secret=secret)
    assert client.post(f"/api/users/{target.id}/mfa-reset").status_code == 204
    # The supervisor's sessions are revoked and they are told by email.
    assert sup_browser.get("/api/auth/me").status_code == 401
    deliver_mail()
    assert any(m.to == "sup@example.org" and "reset" in m.subject for m in outbox)
    assert user_by_email("sup@example.org").mfa_method == MfaMethod.EMAIL
    entry = _audit("mfa.reset_by_admin")
    assert entry.actor_role == "district_admin"


def test_password_reset_with_authenticator_needs_second_factor(client, outbox):
    _, secret = make_user(Role.SUPERVISOR, "sup@example.org", mfa=MfaMethod.TOTP)
    challenge = client.post("/api/auth/password-reset/request", json={"email": "sup@example.org"}).json()["challenge"]
    code = last_code(outbox, "sup@example.org")
    new = "a brand new long password"
    r = client.post(
        "/api/auth/password-reset/complete", json={"challenge": challenge, "code": code, "new_password": new}
    )
    assert r.json()["error"]["code"] == "code_invalid"
    challenge = client.post("/api/auth/password-reset/request", json={"email": "sup@example.org"}).json()["challenge"]
    code = last_code(outbox, "sup@example.org")
    r = client.post(
        "/api/auth/password-reset/complete",
        json={
            "challenge": challenge,
            "code": code,
            "new_password": new,
            "second_code": pyotp.TOTP(secret).now(),
        },
    )
    assert r.status_code == 204, r.text
    assert _start(client, "sup@example.org", new).status_code == 200


def test_password_reset_for_unknown_email_reveals_nothing(client, outbox):
    r = client.post("/api/auth/password-reset/request", json={"email": "ghost@example.org"})
    assert r.status_code == 200 and r.json()["challenge"]
    deliver_mail()
    assert not outbox


def test_breached_password_rejected():
    assert policy_problem("pass12345") == "password_too_short"
    assert policy_problem("password123") == "password_breached"
    assert policy_problem("qwertyuiop") == "password_breached"
    assert policy_problem("1234567890") == "password_breached"
    assert policy_problem("jo.smith-is-great", email="jo.smith@example.org") == "password_contains_identity"
    assert policy_problem("a perfectly fine passphrase") is None


def test_csrf_required_for_changes(client, outbox):
    make_user(Role.CLUSTER_HEAD, "head@example.org")
    login(client, outbox, "head@example.org")
    token = client.headers.pop("X-CSRF-Token")
    r = client.patch("/api/auth/me", json={"locale": "ar"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = client.patch("/api/auth/me", json={"locale": "ar"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.json()["locale"] == "ar"


def test_sessions_list_revoke_and_idle_timeout(client, outbox, new_client):
    make_user(Role.CLUSTER_HEAD, "head@example.org")
    login(client, outbox, "head@example.org")
    other = new_client()
    login(other, outbox, "head@example.org")
    sessions = client.get("/api/auth/sessions").json()
    assert len(sessions) == 2
    other_id = next(s["id"] for s in sessions if not s["current"])
    assert client.delete(f"/api/auth/sessions/{other_id}").status_code == 204
    assert other.get("/api/auth/me").status_code == 401
    clock.freeze(clock.now() + timedelta(hours=13))
    assert client.get("/api/auth/me").status_code == 401


def test_logout_revokes_session(client, outbox):
    make_user(Role.CLUSTER_HEAD, "head@example.org")
    login(client, outbox, "head@example.org")
    session_cookie = client.cookies.get("sces_session")
    assert client.post("/api/auth/logout").status_code == 204
    with session_factory()() as db:
        session = db.execute(
            select(UserSession).where(UserSession.token_hash == tokens.sha256(session_cookie))
        ).scalar_one()
        assert session.revoked_at is not None


def test_switch_to_authenticator_and_back(client, outbox):
    make_user(Role.SUPERVISOR, "sup@example.org")
    login(client, outbox, "sup@example.org")
    enrollment = client.post("/api/auth/mfa/totp/start", json={"password": PASSWORD}).json()
    secret = enrollment["secret"]
    r = client.post(
        "/api/auth/mfa/totp/confirm",
        json={"challenge": enrollment["challenge"], "code": totp.code_at_step(secret, totp.current_step())},
    )
    assert r.status_code == 200 and r.json()["me"]["mfa_method"] == "totp"
    # The next time step, since the confirming code cannot be reused.
    clock.freeze(clock.now() + timedelta(seconds=31))
    r = client.post(
        "/api/auth/mfa/email", json={"password": PASSWORD, "code": totp.code_at_step(secret, totp.current_step())}
    )
    assert r.status_code == 200, r.text
    assert r.json()["mfa_method"] == "email"


def test_admin_cannot_switch_to_email(client, outbox):
    _, secret = make_user(Role.DISTRICT_ADMIN, "admin@example.org", mfa=MfaMethod.TOTP)
    login(client, outbox, "admin@example.org", secret=secret)
    r = client.post("/api/auth/mfa/email", json={"password": PASSWORD, "code": "000000"})
    assert r.json()["error"]["code"] == "totp_required"


def test_break_glass_reset(client, outbox, db):
    """Requires server access, writes a critical audit entry, and notifies all other admins."""
    target, _ = make_user(Role.DISTRICT_ADMIN, "admin1@example.org", mfa=MfaMethod.TOTP)
    make_user(Role.DISTRICT_ADMIN, "admin2@example.org", mfa=MfaMethod.TOTP)
    make_user(Role.DISTRICT_ADMIN, "admin3@example.org", mfa=MfaMethod.TOTP)
    seq = auth.break_glass_reset(db, "admin1@example.org")
    entry = db.execute(select(AuditLog).where(AuditLog.seq == seq)).scalar_one()
    assert entry.severity == "critical" and entry.actor_role == "server_cli"
    deliver_mail()
    notified = {m.to for m in outbox if "emergency" in m.subject.lower()}
    assert notified == {"admin2@example.org", "admin3@example.org"}
    assert db.get(User, target.id).mfa_method == MfaMethod.EMAIL


def test_role_denial_is_audited(client, outbox):
    make_user(Role.TEACHER, "t@example.org")
    login(client, outbox, "t@example.org")
    r = client.get("/api/clusters")
    assert r.status_code == 403
    assert _audit("permission.denied") is not None


def test_emails_follow_user_language(client, outbox):
    user, _ = make_user(Role.TEACHER, "t@example.org")
    with session_factory()() as db:
        db.get(User, user.id).locale = "ar"
        db.commit()
    _start(client, "t@example.org")
    deliver_mail()
    message = outbox[-1]
    assert "رمز" in message.subject and 'dir="rtl"' in message.html


def _audit_actions():
    with session_factory()() as db:
        return db.execute(select(AuditLog.action).order_by(AuditLog.seq)).all()


def _audit(action):
    with session_factory()() as db:
        return db.execute(select(AuditLog).where(AuditLog.action == action)).scalars().first()


def test_csrf_helper_matches_cookie(client, outbox):
    make_user(Role.CLUSTER_HEAD, "head@example.org")
    login(client, outbox, "head@example.org")
    assert csrf(client)["X-CSRF-Token"] == client.cookies.get("sces_csrf")
