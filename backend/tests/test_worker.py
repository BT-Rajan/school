from datetime import datetime

from sqlalchemy import func, select

from app import clock, worker
from app.cli import main as cli_main
from app.models import AuditVerification, Job


def test_daily_tasks_run_once_after_their_local_time(db):
    # 22:00 UTC on 4 Nov is 01:00 on 5 Nov in Kuwait: before the 02:00 audit check.
    clock.freeze(datetime(2026, 11, 4, 22, 0))
    worker.housekeeping(db)
    assert db.execute(select(func.count()).select_from(AuditVerification)).scalar_one() == 0
    # 23:30 UTC is 02:30 local: the check runs, once.
    clock.freeze(datetime(2026, 11, 4, 23, 30))
    worker.housekeeping(db)
    worker.housekeeping(db)
    db.rollback()
    assert db.execute(select(func.count()).select_from(AuditVerification)).scalar_one() == 1
    job = db.execute(select(Job).where(Job.type == "daily:audit_verify")).scalar_one()
    assert job.status == "done" and job.payload == {"day": "2026-11-05"}


def test_grants_sql_keeps_audit_insert_only(capsys):
    cli_main(["grants-sql", "--database", "sces"])
    output = capsys.readouterr().out
    assert "GRANT SELECT, INSERT ON `sces`.`audit_log`" in output
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON `sces`.`users`" in output


def test_create_admin_sends_one_invitation_and_prints_it(capsys, db):
    from app.models import Invitation, MailMessage, User

    cli_main(["create-admin", "--email", "first.admin@example.org", "--name", "First Admin", "--staff-id", "FA1"])
    link = capsys.readouterr().out.strip().rsplit(" ", 1)[-1]
    user = db.execute(select(User).where(User.email == "first.admin@example.org")).scalar_one()
    invitations = list(db.execute(select(Invitation).where(Invitation.user_id == user.id)).scalars())
    # The printed link is the emailed one: a single invitation, still open.
    assert len(invitations) == 1 and invitations[0].revoked_at is None and "/invite/" in link
    mails = db.execute(select(func.count()).select_from(MailMessage).where(MailMessage.user_id == user.id)).scalar_one()
    assert mails == 1
