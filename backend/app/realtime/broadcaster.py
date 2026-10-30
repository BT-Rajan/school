"""The in-process broadcaster (FR-RT1, FR-RT2, FR-RT4).

Connected screens register here. Committed changes arrive from events.py and are
resolved by one dispatcher thread: for each connection it asks the same access
rule the API uses whether that user may see the record, and only then delivers.
So scope is enforced here, at the broadcaster, not in the browser (FR-RT2).

v1 runs in the single API process, which a district of about 212 users fits
comfortably; there is no presence indicator (FR-RT4).
"""

import asyncio
import itertools
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.db import preload, session_factory

log = logging.getLogger(__name__)


@dataclass
class Connection:
    id: int
    user_id: int
    session_id: int
    loop: asyncio.AbstractEventLoop
    outbox: asyncio.Queue = field(default_factory=asyncio.Queue)


class Broadcaster:
    def __init__(self) -> None:
        self._connections: dict[int, Connection] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._events: queue.Queue[list[dict[str, Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    # Connections --------------------------------------------------------------------------

    def connect(self, user_id: int, session_id: int) -> Connection:
        connection = Connection(next(self._ids), user_id, session_id, asyncio.get_running_loop())
        with self._lock:
            self._connections[connection.id] = connection
        return connection

    def disconnect(self, connection: Connection) -> None:
        with self._lock:
            self._connections.pop(connection.id, None)

    def connected(self) -> list[Connection]:
        with self._lock:
            return list(self._connections.values())

    # Events -------------------------------------------------------------------------------

    def publish(self, events: list[dict[str, Any]]) -> None:
        """Called after a commit, from any thread. Never blocks the request."""
        if not self.connected():
            return
        self._ensure_thread()
        self._events.put(events)

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="realtime", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            events = self._events.get()
            if events is None:
                return
            try:
                self.dispatch(events)
            except Exception:  # noqa: BLE001 - a bad event must not stop live updates
                log.exception("realtime dispatch failed")
            finally:
                self._events.task_done()

    def wait_idle(self) -> None:
        """For tests: block until every published event has been delivered."""
        self._events.join()

    def dispatch(self, events: list[dict[str, Any]]) -> None:
        connections = self.connected()
        if not connections:
            return
        from app.models import User

        with session_factory()() as db:
            # One query for everyone connected, and one decision per person and event, however
            # many tabs and devices they have open (section 15: delivery under 2 s).
            preload(db, User, {c.user_id for c in connections})
            for event in events:
                decided = self._audience(db, connections, event)
                message = (
                    {"type": "notification"}
                    if event["entity"] == "notification"
                    else {"type": "changed", "entity": event["entity"], "id": event["id"]}
                )
                for connection in connections:
                    if connection.user_id not in decided:
                        decided[connection.user_id] = self._may_see(db, connection.user_id, event)
                    if decided[connection.user_id]:
                        connection.loop.call_soon_threadsafe(connection.outbox.put_nowait, dict(message))

    def _audience(self, db: Session, connections: list[Connection], event: dict[str, Any]) -> dict[int, bool]:
        """Decisions for everyone at once where the record's rule allows it: scanned reports, the
        busiest and most sensitive. Anything else is decided person by person."""
        if event["entity"] != "document" or event["user_id"] is not None:
            return {}
        from app.auth.deps import Principal
        from app.documents import access
        from app.models import User, UserStatus

        users = {c.user_id: db.get(User, c.user_id) for c in connections}
        principals = [Principal(u, None) for u in users.values() if u is not None and u.status == UserStatus.ACTIVE]
        allowed = access.audience(db, principals, int(event["id"]))
        return {user_id: user_id in allowed for user_id in users}

    def _may_see(self, db: Session, user_id: int, event: dict[str, Any]) -> bool:
        if event["user_id"] is not None:
            return event["user_id"] == user_id
        rule = AUDIENCE.get(event["entity"])
        if rule is None:
            return False
        from app.auth.deps import Principal
        from app.models import User, UserStatus

        user = db.get(User, user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            return False
        try:
            return bool(rule(db, Principal(user, None), event["id"]))  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001 - an access rule that refuses by raising means no
            db.rollback()
            return False


# Who may hear about a change: the same rules the API applies to the record itself.

AudienceRule = Callable[[Session, Any, str], bool]


def _document(db, principal, entity_id):
    from app.documents import access

    return access.can_access(db, principal, int(entity_id))


def _evaluation(db, principal, entity_id):
    from app.evaluations.service import can_read
    from app.models import Evaluation

    e = db.get(Evaluation, int(entity_id))
    return e is not None and can_read(db, principal, e)


def _request(db, principal, entity_id):
    from app.models import TeacherRequest
    from app.requests import access

    query = access.visible_query(db, principal).where(TeacherRequest.id == int(entity_id))
    return db.execute(query).first() is not None


def _assignment(db, principal, entity_id):
    from app.assignments import queries
    from app.models import Role, School, SupervisorAssignment
    from app.structure.common import managed_cluster_ids

    a = db.get(SupervisorAssignment, int(entity_id))
    if a is None:
        return False
    if principal.role == Role.SUPERVISOR:
        own = queries.supervisor_for_user(db, principal.user.id)
        return own is not None and own.id == a.supervisor_id
    if principal.role in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
        allowed = managed_cluster_ids(db, principal)
        return allowed is None or db.get(School, a.school_id).cluster_id in allowed
    return False


def _form(db, principal, entity_id):
    from app.models import FormVersion, Role

    form = db.get(FormVersion, int(entity_id))
    if form is None:
        return False
    if principal.role in (Role.DISTRICT_ADMIN, Role.FORM_AUTHOR):
        return True
    return form.status == "published" and principal.role in (Role.CLUSTER_HEAD, Role.SUPERVISOR)


def _structure(cluster_of: Callable[[Session, str], int | None]) -> AudienceRule:
    def rule(db, principal, entity_id):
        from app.models import Role
        from app.structure.common import managed_cluster_ids

        if principal.role not in (Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD):
            return False
        allowed = managed_cluster_ids(db, principal)
        return allowed is None or cluster_of(db, entity_id) in allowed

    return rule


def _cluster_of_school(db, entity_id):
    from app.models import School

    school = db.get(School, int(entity_id))
    return school.cluster_id if school else None


def _cluster_of_teacher(db, entity_id):
    from app.models import School, Teacher

    teacher = db.get(Teacher, int(entity_id))
    return db.get(School, teacher.school_id).cluster_id if teacher else None


def _cluster_of_supervisor(db, entity_id):
    from app.models import Supervisor

    supervisor = db.get(Supervisor, int(entity_id))
    return supervisor.cluster_id if supervisor else None


def _user(db, principal, entity_id):
    """Accounts: admins, and the Cluster Head managing that teacher or supervisor."""
    from app.models import Role
    from app.structure import people

    if principal.role == Role.DISTRICT_ADMIN:
        return True
    if principal.role != Role.CLUSTER_HEAD:
        return False
    from app.models import User

    user = db.get(User, int(entity_id))
    if user is None or user.role not in (Role.TEACHER, Role.SUPERVISOR):
        return False
    from app.structure.common import managed_cluster_ids

    return people._cluster_of(db, user) in (managed_cluster_ids(db, principal) or [])


AUDIENCE: dict[str, AudienceRule] = {
    "assignment": _assignment,
    "cluster": _structure(lambda _db, entity_id: int(entity_id)),
    "document": _document,
    "evaluation": _evaluation,
    "form": _form,
    "request": _request,
    "school": _structure(_cluster_of_school),
    "supervisor": _structure(_cluster_of_supervisor),
    "teacher": _structure(_cluster_of_teacher),
    "user": _user,
}

broadcaster = Broadcaster()
