"""Who can see a scanned report: the one rule every code path uses (FR-D10 to FR-D16).

- The owning supervisor sees their own documents, except deleted ones.
- Active District Admins see every document, including drafts and deleted ones.
- A Cluster Head sees a document only while an admin's forward to their
  cluster is active and they head that cluster now.
- Nobody else sees anything: not other supervisors, not teachers, not Form Authors.

Lists, search, counts, dashboards, links and notifications all build on
visible_query, so no path can skip the rule. can_access asks the same query.
audience answers it for many people at once, for live updates; a test holds it to
can_access for every user and document.
"""

from sqlalchemy import Select, exists, false, select
from sqlalchemy.orm import Session

from app.assignments import queries as assignments
from app.audit import service as audit
from app.auth.deps import Principal
from app.errors import not_found
from app.models import Cluster, Document, DocumentForward, Role, Supervisor


def visible_query(db: Session, principal: Principal) -> Select:
    query = select(Document)
    if principal.role == Role.DISTRICT_ADMIN:
        return query
    if principal.role == Role.SUPERVISOR:
        own = assignments.supervisor_for_user(db, principal.user.id)
        if own is None:
            return query.where(false())
        return query.where(Document.owner_supervisor_id == own.id, Document.deleted_at.is_(None))
    if principal.role == Role.CLUSTER_HEAD:
        forwarded = exists().where(
            DocumentForward.document_id == Document.id,
            DocumentForward.revoked_at.is_(None),
            DocumentForward.cluster_id == Cluster.id,
            Cluster.cluster_head_id == principal.user.id,
        )
        return query.where(
            forwarded,
            Document.deleted_at.is_(None),
            Document.status.notin_(("draft", "withdrawn")),
        )
    return query.where(false())


def can_access(db: Session, principal: Principal, document_id: int) -> bool:
    query = visible_query(db, principal).where(Document.id == document_id).with_only_columns(Document.id)
    return db.execute(query).first() is not None


def audience(db: Session, principals: list[Principal], document_id: int) -> set[int]:
    """The user IDs among these principals for whom can_access holds, in three queries."""
    document = db.execute(
        select(Document.deleted_at, Document.status, Supervisor.user_id)
        .join(Supervisor, Supervisor.id == Document.owner_supervisor_id)
        .where(Document.id == document_id)
    ).first()
    if document is None:
        return set()
    deleted_at, status, owner_user_id = document
    heads: set[int] = set()
    if deleted_at is None and status not in ("draft", "withdrawn"):
        heads = set(
            db.execute(
                select(Cluster.cluster_head_id)
                .join(DocumentForward, DocumentForward.cluster_id == Cluster.id)
                .where(DocumentForward.document_id == document_id, DocumentForward.revoked_at.is_(None))
            ).scalars()
        )
    allowed = set()
    for p in principals:
        if p.role == Role.DISTRICT_ADMIN:
            allowed.add(p.user.id)
        elif p.role == Role.SUPERVISOR and deleted_at is None and p.user.id == owner_user_id:
            # The owner is the supervisor row's user; visible_query asks the same through
            # supervisor_for_user.
            allowed.add(p.user.id)
        elif p.role == Role.CLUSTER_HEAD and p.user.id in heads:
            allowed.add(p.user.id)
    return allowed


def get_visible(db: Session, principal: Principal, document_id: int) -> Document:
    """A document the principal may see. Anything else is 404, and the attempt is audited (FR-D11)."""
    document = db.get(Document, document_id)
    if document is None:
        raise not_found()
    if not can_access(db, principal, document_id):
        audit.record_denial(
            "document.access", entity_type="document", entity_id=document_id, reason="scope", request_db=db
        )
        raise not_found()
    return document


def is_owner(db: Session, principal: Principal, document: Document) -> bool:
    if principal.role != Role.SUPERVISOR:
        return False
    own = assignments.supervisor_for_user(db, principal.user.id)
    return own is not None and own.id == document.owner_supervisor_id
