from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import Principal, admin_only, current_principal
from app.db import get_db
from app.models import EntityStatus
from app.structure import reference
from app.structure.reference import CustomFieldIn, CustomFieldUpdate, ReferenceIn, ReferenceUpdate

router = APIRouter(prefix="/api", tags=["reference"])


@router.get("/reference/{list_name}")
def list_reference(
    list_name: str,
    include_retired: bool = False,
    _: Principal = Depends(current_principal),
    db: Session = Depends(get_db),
):
    return reference.list_reference(db, list_name, include_retired)


@router.post("/reference/{list_name}", status_code=201)
def create_reference(
    list_name: str, body: ReferenceIn, _: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    return reference.create_reference(db, list_name, body)


@router.patch("/reference-values/{value_id}")
def update_reference(
    value_id: int, body: ReferenceUpdate, _: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    return reference.update_reference(db, value_id, body)


@router.post("/reference-values/{value_id}/retire")
def retire_reference(value_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return reference.set_reference_status(db, value_id, EntityStatus.INACTIVE)


@router.post("/reference-values/{value_id}/restore")
def restore_reference(value_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return reference.set_reference_status(db, value_id, EntityStatus.ACTIVE)


@router.get("/custom-fields/{entity}")
def list_custom_fields(
    entity: str, include_retired: bool = False, _: Principal = Depends(current_principal), db: Session = Depends(get_db)
):
    return reference.list_custom_fields(db, entity, include_retired)


@router.post("/custom-fields", status_code=201)
def create_custom_field(body: CustomFieldIn, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return reference.create_custom_field(db, body)


@router.patch("/custom-fields/{field_id}")
def update_custom_field(
    field_id: int, body: CustomFieldUpdate, _: Principal = Depends(admin_only), db: Session = Depends(get_db)
):
    return reference.update_custom_field(db, field_id, body)


@router.post("/custom-fields/{field_id}/retire")
def retire_custom_field(field_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return reference.set_custom_field_status(db, field_id, EntityStatus.INACTIVE)


@router.post("/custom-fields/{field_id}/restore")
def restore_custom_field(field_id: int, _: Principal = Depends(admin_only), db: Session = Depends(get_db)):
    return reference.set_custom_field_status(db, field_id, EntityStatus.ACTIVE)
