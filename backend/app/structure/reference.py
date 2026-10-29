"""Reference lists and custom field definitions, managed by the District Admin (FR-T5, FR-T6)."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.district import get_district
from app.errors import AppError, invalid, not_found
from app.models import CustomFieldDefinition, EntityStatus, ReferenceValue

from .common import CUSTOM_ENTITIES, CUSTOM_TYPES, REFERENCE_LISTS, check_version

KEY = r"^[a-z][a-z0-9_]{0,63}$"


class ReferenceIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
    name_en: str = Field(min_length=1, max_length=200)
    name_ar: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class ReferenceUpdate(BaseModel):
    version: int
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None


class OptionIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
    en: str = Field(min_length=1, max_length=200)
    ar: str = Field(min_length=1, max_length=200)


class CustomFieldIn(BaseModel):
    entity: str
    key: str = Field(pattern=KEY)
    field_type: str
    label_en: str = Field(min_length=1, max_length=200)
    label_ar: str = Field(min_length=1, max_length=200)
    required: bool = False
    options: list[OptionIn] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class CustomFieldUpdate(BaseModel):
    version: int
    label_en: str | None = Field(default=None, min_length=1, max_length=200)
    label_ar: str | None = Field(default=None, min_length=1, max_length=200)
    required: bool | None = None
    options: list[OptionIn] | None = None
    validation: dict[str, Any] | None = None
    sort_order: int | None = None


def reference_out(value: ReferenceValue) -> dict[str, Any]:
    return {
        "id": value.id,
        "list": value.list_name,
        "code": value.code,
        "name_en": value.name_en,
        "name_ar": value.name_ar,
        "sort_order": value.sort_order,
        "status": value.status,
        "version": value.version,
    }


def list_reference(db: Session, list_name: str, include_retired: bool = False) -> list[dict[str, Any]]:
    if list_name not in REFERENCE_LISTS:
        raise not_found()
    query = select(ReferenceValue).where(ReferenceValue.list_name == list_name)
    if not include_retired:
        query = query.where(ReferenceValue.status == EntityStatus.ACTIVE)
    query = query.order_by(ReferenceValue.sort_order, ReferenceValue.name_en)
    return [reference_out(v) for v in db.execute(query).scalars()]


def create_reference(db: Session, list_name: str, body: ReferenceIn) -> dict[str, Any]:
    if list_name not in REFERENCE_LISTS:
        raise not_found()
    exists = db.execute(
        select(ReferenceValue.id).where(ReferenceValue.list_name == list_name, ReferenceValue.code == body.code)
    ).first()
    if exists:
        raise AppError(409, "code_taken")
    value = ReferenceValue(list_name=list_name, **body.model_dump())
    db.add(value)
    db.flush()
    audit.record(
        db,
        "reference.created",
        entity_type="reference_value",
        entity_id=value.id,
        after={"list": list_name, "code": value.code, "name_en": value.name_en, "name_ar": value.name_ar},
    )
    db.commit()
    return reference_out(value)


def update_reference(db: Session, value_id: int, body: ReferenceUpdate) -> dict[str, Any]:
    value = db.get(ReferenceValue, value_id)
    if value is None:
        raise not_found()
    check_version(body.version, value.version, reference_out(value))
    before = reference_out(value)
    for field in ("name_en", "name_ar", "sort_order"):
        if getattr(body, field) is not None:
            setattr(value, field, getattr(body, field))
    db.flush()
    old, new = audit.changed_fields(before, reference_out(value))
    new.pop("version", None)
    old.pop("version", None)
    if new:
        audit.record(db, "reference.updated", entity_type="reference_value", entity_id=value.id, before=old, after=new)
    db.commit()
    return reference_out(value)


def set_reference_status(db: Session, value_id: int, status: EntityStatus) -> dict[str, Any]:
    """Values in use are retired, never deleted."""
    value = db.get(ReferenceValue, value_id)
    if value is None:
        raise not_found()
    value.status = status
    db.flush()
    audit.record(
        db,
        f"reference.{'retired' if status == EntityStatus.INACTIVE else 'restored'}",
        entity_type="reference_value",
        entity_id=value.id,
    )
    db.commit()
    return reference_out(value)


def custom_field_out(field: CustomFieldDefinition) -> dict[str, Any]:
    return {
        "id": field.id,
        "entity": field.entity,
        "key": field.key,
        "field_type": field.field_type,
        "label_en": field.label_en,
        "label_ar": field.label_ar,
        "required": field.required,
        "options": field.options or [],
        "validation": field.validation or {},
        "sort_order": field.sort_order,
        "status": field.status,
        "version": field.version,
    }


def list_custom_fields(db: Session, entity: str, include_retired: bool = False) -> list[dict[str, Any]]:
    if entity not in CUSTOM_ENTITIES:
        raise not_found()
    query = select(CustomFieldDefinition).where(CustomFieldDefinition.entity == entity)
    if not include_retired:
        query = query.where(CustomFieldDefinition.status == EntityStatus.ACTIVE)
    query = query.order_by(CustomFieldDefinition.sort_order, CustomFieldDefinition.id)
    return [custom_field_out(f) for f in db.execute(query).scalars()]


def _validate_definition(field_type: str, options: list[OptionIn], validation: dict[str, Any]) -> None:
    if field_type not in CUSTOM_TYPES:
        raise invalid("field_type_invalid")
    if field_type in ("single_choice", "multi_choice"):
        if not options:
            raise invalid("options_required")
        if len({o.code for o in options}) != len(options):
            raise invalid("options_duplicate")
    unknown = set(validation) - {"min", "max", "max_length"}
    if unknown:
        raise invalid("validation_invalid", sorted(unknown))


def create_custom_field(db: Session, body: CustomFieldIn) -> dict[str, Any]:
    if body.entity not in CUSTOM_ENTITIES:
        raise invalid("entity_invalid")
    _validate_definition(body.field_type, body.options, body.validation)
    limit = int(get_district(db).setting("custom_field_limit"))
    active = db.execute(
        select(func.count())
        .select_from(CustomFieldDefinition)
        .where(CustomFieldDefinition.entity == body.entity, CustomFieldDefinition.status == EntityStatus.ACTIVE)
    ).scalar_one()
    if active >= limit:
        raise AppError(409, "custom_field_limit", {"limit": limit})
    exists = db.execute(
        select(CustomFieldDefinition.id).where(
            CustomFieldDefinition.entity == body.entity, CustomFieldDefinition.key == body.key
        )
    ).first()
    if exists:
        raise AppError(409, "key_taken")
    field = CustomFieldDefinition(
        **body.model_dump(exclude={"options"}),
        options=[o.model_dump() for o in body.options],
    )
    db.add(field)
    db.flush()
    audit.record(
        db, "custom_field.created", entity_type="custom_field", entity_id=field.id, after=custom_field_out(field)
    )
    db.commit()
    return custom_field_out(field)


def update_custom_field(db: Session, field_id: int, body: CustomFieldUpdate) -> dict[str, Any]:
    field = db.get(CustomFieldDefinition, field_id)
    if field is None:
        raise not_found()
    check_version(body.version, field.version, custom_field_out(field))
    before = custom_field_out(field)
    options = body.options if body.options is not None else [OptionIn(**o) for o in field.options or []]
    _validate_definition(
        field.field_type, options, body.validation if body.validation is not None else field.validation
    )
    for attr in ("label_en", "label_ar", "required", "validation", "sort_order"):
        if getattr(body, attr) is not None:
            setattr(field, attr, getattr(body, attr))
    if body.options is not None:
        field.options = [o.model_dump() for o in body.options]
    db.flush()
    old, new = audit.changed_fields(before, custom_field_out(field))
    old.pop("version", None)
    new.pop("version", None)
    if new:
        audit.record(db, "custom_field.updated", entity_type="custom_field", entity_id=field.id, before=old, after=new)
    db.commit()
    return custom_field_out(field)


def set_custom_field_status(db: Session, field_id: int, status: EntityStatus) -> dict[str, Any]:
    """Retiring hides a field but keeps its stored values."""
    field = db.get(CustomFieldDefinition, field_id)
    if field is None:
        raise not_found()
    field.status = status
    db.flush()
    audit.record(
        db,
        f"custom_field.{'retired' if status == EntityStatus.INACTIVE else 'restored'}",
        entity_type="custom_field",
        entity_id=field.id,
    )
    db.commit()
    return custom_field_out(field)
