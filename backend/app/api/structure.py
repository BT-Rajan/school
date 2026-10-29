from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.deps import Principal, admin_only, current_principal, require_roles, structure_managers
from app.db import get_db
from app.models import EntityStatus, Role
from app.structure import people, service
from app.structure.schemas import (
    ClusterIn,
    ClusterUpdate,
    ContactIn,
    MoveClusterIn,
    PersonUpdate,
    SchoolIn,
    SchoolUpdate,
    SupervisorIn,
    TeacherIn,
    TeacherUpdate,
    TransferIn,
)

router = APIRouter(prefix="/api", tags=["structure"])
# Supervisors may read the schools and teachers assigned to them; services scope the results.
readers = require_roles(Role.DISTRICT_ADMIN, Role.CLUSTER_HEAD, Role.SUPERVISOR)


# Clusters


@router.get("/clusters")
def list_clusters(principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return service.list_clusters(db, principal)


@router.post("/clusters", status_code=201)
def create_cluster(body: ClusterIn, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return service.create_cluster(db, body)


@router.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    cluster = service.get_cluster(db, principal, cluster_id)
    return next(c for c in service.list_clusters(db, principal) if c["id"] == cluster.id)


@router.patch("/clusters/{cluster_id}")
def update_cluster(
    cluster_id: int, body: ClusterUpdate, _: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    return service.update_cluster(db, cluster_id, body)


@router.post("/clusters/{cluster_id}/deactivate")
def deactivate_cluster(cluster_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return service.set_cluster_status(db, cluster_id, EntityStatus.INACTIVE)


@router.post("/clusters/{cluster_id}/reactivate")
def reactivate_cluster(cluster_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return service.set_cluster_status(db, cluster_id, EntityStatus.ACTIVE)


# Schools


@router.get("/schools")
def list_schools(
    q: str | None = Query(default=None, max_length=100),
    status: EntityStatus | None = None,
    cluster_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(readers),
    db: Session = Depends(get_db),
):
    return service.list_schools(
        db, principal, q=q, status=status, cluster_id=cluster_id, page=page, page_size=page_size
    )


@router.post("/schools", status_code=201)
def create_school(body: SchoolIn, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return service.school_out(db, service.create_school(db, principal, body))


@router.get("/schools/{school_id}")
def get_school(school_id: int, principal: Principal = Depends(readers), db: Session = Depends(get_db)):
    return service.school_out(db, service.get_school(db, principal, school_id))


@router.patch("/schools/{school_id}")
def update_school(
    school_id: int,
    body: SchoolUpdate,
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    return service.school_out(db, service.update_school(db, principal, school_id, body))


@router.post("/schools/{school_id}/deactivate")
def deactivate_school(
    school_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)
):
    return service.school_out(db, service.set_school_status(db, principal, school_id, EntityStatus.INACTIVE))


@router.post("/schools/{school_id}/reactivate")
def reactivate_school(
    school_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)
):
    return service.school_out(db, service.set_school_status(db, principal, school_id, EntityStatus.ACTIVE))


@router.put("/schools/{school_id}/contact")
def set_contact(
    school_id: int, body: ContactIn, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)
):
    return service.school_out(db, service.set_contact_teacher(db, principal, school_id, body.teacher_id))


@router.get("/schools/{school_id}/contacts")
def contact_history(school_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return service.school_contact_history(db, principal, school_id)


# Teachers


@router.get("/teachers")
def list_teachers(
    q: str | None = Query(default=None, max_length=100),
    status: EntityStatus | None = None,
    school_id: int | None = None,
    cluster_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(readers),
    db: Session = Depends(get_db),
):
    return people.list_teachers(
        db, principal, q=q, status=status, school_id=school_id, cluster_id=cluster_id, page=page, page_size=page_size
    )


@router.post("/teachers", status_code=201)
def create_teacher(body: TeacherIn, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)):
    return people.teacher_out(db, people.create_teacher(db, principal, body))


@router.get("/teachers/{teacher_id}")
def get_teacher(teacher_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return people.teacher_out(db, people.get_teacher(db, principal, teacher_id))


@router.patch("/teachers/{teacher_id}")
def update_teacher(
    teacher_id: int,
    body: TeacherUpdate,
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    return people.teacher_out(db, people.update_teacher(db, principal, teacher_id, body))


@router.post("/teachers/{teacher_id}/transfer")
def transfer_teacher(
    teacher_id: int, body: TransferIn, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)
):
    return people.teacher_out(db, people.transfer_teacher(db, principal, teacher_id, body))


@router.get("/teachers/{teacher_id}/transfers")
def teacher_transfers(
    teacher_id: int, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)
):
    return people.teacher_transfers(db, principal, teacher_id)


# Supervisors


@router.get("/supervisors")
def list_supervisors(
    q: str | None = Query(default=None, max_length=100),
    status: EntityStatus | None = None,
    cluster_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    return people.list_supervisors(
        db, principal, q=q, status=status, cluster_id=cluster_id, page=page, page_size=page_size
    )


@router.post("/supervisors", status_code=201)
def create_supervisor(
    body: SupervisorIn, principal: Principal = Depends(structure_managers), db: Session = Depends(get_db)
):
    return people.supervisor_out(db, people.create_supervisor(db, principal, body))


@router.get("/supervisors/{supervisor_id}")
def get_supervisor(
    supervisor_id: int, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return people.supervisor_out(db, people.get_supervisor(db, principal, supervisor_id))


@router.patch("/supervisors/{supervisor_id}")
def update_supervisor(
    supervisor_id: int,
    body: PersonUpdate,
    principal: Principal = Depends(structure_managers),
    db: Session = Depends(get_db),
):
    return people.supervisor_out(db, people.update_supervisor(db, principal, supervisor_id, body))


@router.post("/supervisors/{supervisor_id}/move")
def move_supervisor(
    supervisor_id: int, body: MoveClusterIn, principal: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    return people.supervisor_out(db, people.move_supervisor(db, principal, supervisor_id, body.cluster_id))
