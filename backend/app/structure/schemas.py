from datetime import date
from typing import Any

from pydantic import BaseModel, EmailStr, Field

CODE = r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,31}$"
STAFF_ID = r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,63}$"
LOCALE = "^(en|ar)$"


class ClusterIn(BaseModel):
    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=200)
    cluster_head_id: int | None = None


class ClusterUpdate(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    cluster_head_id: int | None = None


class SchoolIn(BaseModel):
    cluster_id: int
    code: str = Field(pattern=CODE)
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=500)
    school_type: str = Field(min_length=1, max_length=64)
    medium: str = Field(min_length=1, max_length=64)
    contact_phone: str = Field(min_length=3, max_length=32)
    contact_email: EmailStr | None = None
    custom: dict[str, Any] = Field(default_factory=dict)


class SchoolUpdate(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    school_type: str | None = Field(default=None, min_length=1, max_length=64)
    medium: str | None = Field(default=None, min_length=1, max_length=64)
    contact_phone: str | None = Field(default=None, min_length=3, max_length=32)
    contact_email: EmailStr | None = None
    custom: dict[str, Any] | None = None


class StaffIn(BaseModel):
    """District Admins and Cluster Heads."""

    staff_id: str = Field(pattern=STAFF_ID)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    locale: str | None = Field(default=None, pattern=LOCALE)


class QualificationIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    year: int | None = Field(default=None, ge=1950, le=2100)


class TeacherIn(BaseModel):
    staff_id: str = Field(pattern=STAFF_ID)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    school_id: int
    designation: str = Field(min_length=1, max_length=64)
    subjects: list[str] = Field(min_length=1)
    classes: list[str] = Field(min_length=1)
    experience_years: int = Field(ge=0, le=60)
    experience_as_of: date | None = None
    qualifications: list[QualificationIn] = Field(min_length=1)
    custom: dict[str, Any] = Field(default_factory=dict)
    locale: str | None = Field(default=None, pattern=LOCALE)


class TeacherUpdate(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    designation: str | None = Field(default=None, min_length=1, max_length=64)
    subjects: list[str] | None = Field(default=None, min_length=1)
    classes: list[str] | None = Field(default=None, min_length=1)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    experience_as_of: date | None = None
    qualifications: list[QualificationIn] | None = Field(default=None, min_length=1)
    custom: dict[str, Any] | None = None


class TransferIn(BaseModel):
    school_id: int
    moved_on: date | None = None


class SupervisorIn(BaseModel):
    staff_id: str = Field(pattern=STAFF_ID)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    cluster_id: int
    locale: str | None = Field(default=None, pattern=LOCALE)


class PersonUpdate(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None


class MoveClusterIn(BaseModel):
    cluster_id: int


class ContactIn(BaseModel):
    teacher_id: int
