"""Scope, search normalization, reference values and custom fields."""

import re
import unicodedata
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.deps import Principal
from app.errors import AppError, invalid, not_found
from app.models import Cluster, CustomFieldDefinition, EntityStatus, ReferenceValue, Role

REFERENCE_LISTS = ("designation", "subject", "class", "qualification")
CUSTOM_ENTITIES = ("teacher", "school")
CUSTOM_TYPES = ("text", "number", "date", "single_choice", "multi_choice", "yes_no")

_ARABIC_FOLD = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ـ": None,  # tatweel
    }
)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def fold_search(text: str) -> str:
    """Fold text for matching: case, diacritics, Arabic letter forms and digits (FR-I7).

    Stored text is never changed; only this search key is folded.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_ARABIC_FOLD).translate(_DIGITS).casefold()
    return re.sub(r"\s+", " ", text).strip()[:200]


def like_pattern(term: str) -> str:
    folded = fold_search(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{folded}%"


# Scope ------------------------------------------------------------------------


def managed_cluster_ids(db: Session, principal: Principal) -> list[int] | None:
    """Clusters the user manages. None means every cluster (District Admin)."""
    if principal.role == Role.DISTRICT_ADMIN:
        return None
    if principal.role == Role.CLUSTER_HEAD:
        return list(db.execute(select(Cluster.id).where(Cluster.cluster_head_id == principal.user.id)).scalars())
    return []


def ensure_cluster_in_scope(db: Session, principal: Principal, cluster_id: int, *, entity: str, entity_id: Any) -> None:
    allowed = managed_cluster_ids(db, principal)
    if allowed is not None and cluster_id not in allowed:
        deny(db, entity, entity_id)


def deny(db: Session, entity: str, entity_id: Any) -> None:
    """Out-of-scope access: audited, and reported as not found."""
    audit.record_denial(f"{entity}.access", entity_type=entity, entity_id=entity_id, reason="scope", request_db=db)
    raise not_found()


def check_version(sent: int, current: int, current_state: dict[str, Any]) -> None:
    if sent != current:
        raise AppError(409, "version_conflict", {"current": current_state})


# Reference values ---------------------------------------------------------------


def resolve_reference(db: Session, list_name: str, code: str, field: str) -> ReferenceValue:
    value = db.execute(
        select(ReferenceValue).where(ReferenceValue.list_name == list_name, ReferenceValue.code == code)
    ).scalar_one_or_none()
    if value is None or value.status != EntityStatus.ACTIVE:
        raise invalid("reference_unknown", {"field": field, "value": code})
    return value


def find_reference_by_label(db: Session, list_name: str, label: str) -> ReferenceValue | None:
    """Imports may name a value by code, English name or Arabic name."""
    label = label.strip()
    candidates = db.execute(
        select(ReferenceValue).where(
            ReferenceValue.list_name == list_name, ReferenceValue.status == EntityStatus.ACTIVE
        )
    ).scalars()
    folded = fold_search(label)
    for value in candidates:
        if label == value.code or folded in (fold_search(value.name_en), fold_search(value.name_ar)):
            return value
    return None


# Custom fields --------------------------------------------------------------------


def active_custom_fields(db: Session, entity: str) -> list[CustomFieldDefinition]:
    return list(
        db.execute(
            select(CustomFieldDefinition)
            .where(CustomFieldDefinition.entity == entity, CustomFieldDefinition.status == EntityStatus.ACTIVE)
            .order_by(CustomFieldDefinition.sort_order, CustomFieldDefinition.id)
        ).scalars()
    )


def _coerce(definition: CustomFieldDefinition, value: Any) -> Any:
    rules = definition.validation or {}
    codes = {opt["code"] for opt in definition.options or []}
    match definition.field_type:
        case "text":
            value = str(value).strip()
            if len(value) > int(rules.get("max_length", 500)):
                raise ValueError("too_long")
            return value
        case "number":
            number = float(value)
            if "min" in rules and number < float(rules["min"]):
                raise ValueError("below_min")
            if "max" in rules and number > float(rules["max"]):
                raise ValueError("above_max")
            return int(number) if number.is_integer() else number
        case "date":
            return value if isinstance(value, date) else date.fromisoformat(str(value)).isoformat()
        case "single_choice":
            if str(value) not in codes:
                raise ValueError("not_an_option")
            return str(value)
        case "multi_choice":
            items = value if isinstance(value, list) else [v.strip() for v in str(value).split(",") if v.strip()]
            if any(str(v) not in codes for v in items):
                raise ValueError("not_an_option")
            return [str(v) for v in items]
        case "yes_no":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("yes", "true", "1", "نعم"):
                return True
            if text in ("no", "false", "0", "لا"):
                return False
            raise ValueError("not_yes_no")
    raise ValueError("unknown_type")


def validate_custom(
    db: Session, entity: str, values: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate submitted custom values. Values of retired fields are kept."""
    result = dict(existing or {})
    errors = []
    definitions = active_custom_fields(db, entity)
    known = {d.key for d in definitions}
    for key in values:
        if key not in known:
            errors.append({"field": f"custom.{key}", "code": "unknown_field"})
    for definition in definitions:
        if definition.key in values:
            raw = values[definition.key]
            if raw in (None, "", []):
                result.pop(definition.key, None)
            else:
                try:
                    result[definition.key] = _coerce(definition, raw)
                except (ValueError, TypeError) as exc:
                    errors.append({"field": f"custom.{definition.key}", "code": str(exc) or "invalid"})
        if definition.required and result.get(definition.key) in (None, "", []):
            errors.append({"field": f"custom.{definition.key}", "code": "required"})
    if errors:
        raise invalid("custom_fields_invalid", errors)
    return result
