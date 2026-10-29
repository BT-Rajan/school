from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base
from app.models.enums import EntityStatus


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    cluster_head_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=EntityStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class School(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    name_search: Mapped[str] = mapped_column(String(200), default="", index=True)
    address: Mapped[str] = mapped_column(String(500))
    school_type: Mapped[str] = mapped_column(String(64))
    medium: Mapped[str] = mapped_column(String(64))
    contact_phone: Mapped[str] = mapped_column(String(32))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    custom: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default=EntityStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    designation_id: Mapped[int] = mapped_column(ForeignKey("reference_values.id"))
    experience_years: Mapped[int]
    # Experience was recorded on this date, so the current figure can be derived.
    experience_as_of: Mapped[date]
    custom: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default=EntityStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}

    def current_experience(self, today: date) -> int:
        return self.experience_years + max(0, (today - self.experience_as_of).days // 365)


class TeacherSubject(Base):
    __tablename__ = "teacher_subjects"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), primary_key=True)
    reference_value_id: Mapped[int] = mapped_column(ForeignKey("reference_values.id"), primary_key=True)


class TeacherClass(Base):
    __tablename__ = "teacher_classes"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), primary_key=True)
    reference_value_id: Mapped[int] = mapped_column(ForeignKey("reference_values.id"), primary_key=True)


class TeacherQualification(Base):
    __tablename__ = "teacher_qualifications"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), primary_key=True)
    reference_value_id: Mapped[int] = mapped_column(ForeignKey("reference_values.id"), primary_key=True)
    year: Mapped[int | None]


class TeacherTransfer(Base):
    __tablename__ = "teacher_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    from_school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    to_school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"))
    moved_on: Mapped[date]
    moved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class SchoolContact(Base):
    """Contact teacher designation history (FR-S6). An open row has no end_date."""

    __tablename__ = "school_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=clock.now)


class Supervisor(Base):
    __tablename__ = "supervisors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=EntityStatus.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class SupervisorClusterMove(Base):
    __tablename__ = "supervisor_cluster_moves"

    id: Mapped[int] = mapped_column(primary_key=True)
    supervisor_id: Mapped[int] = mapped_column(ForeignKey("supervisors.id"), index=True)
    from_cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"))
    to_cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"))
    moved_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    moved_at: Mapped[datetime] = mapped_column(default=clock.now)


class ReferenceValue(Base):
    """Admin-managed lists: designations, subjects, classes, qualifications (FR-T6)."""

    __tablename__ = "reference_values"
    __table_args__ = (UniqueConstraint("list_name", "code", name="uq_reference_values_list_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_name: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str] = mapped_column(String(200))
    name_ar: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(16), default=EntityStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}


class CustomFieldDefinition(Base):
    """Extra admin-defined fields for teachers and schools (FR-T5)."""

    __tablename__ = "custom_field_definitions"
    __table_args__ = (UniqueConstraint("entity", "key", name="uq_custom_field_definitions_entity_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(64))
    field_type: Mapped[str] = mapped_column(String(16))
    label_en: Mapped[str] = mapped_column(String(200))
    label_ar: Mapped[str] = mapped_column(String(200))
    required: Mapped[bool] = mapped_column(default=False)
    # For choice types: [{"code": "...", "en": "...", "ar": "..."}].
    options: Mapped[list[Any]] = mapped_column(default=list)
    # Optional limits: {"min": n, "max": n, "max_length": n}.
    validation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    sort_order: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(16), default=EntityStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}
