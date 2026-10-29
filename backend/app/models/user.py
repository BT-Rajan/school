from datetime import datetime

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app import clock
from app.db import Base
from app.models.enums import MfaMethod, Role, UserStatus


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    email_verified_at: Mapped[datetime | None]
    # District-unique staff ID. Form Authors belong to the implementation team and have none.
    staff_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    # Name folded for search across Arabic letter forms and diacritics (FR-I7).
    name_search: Mapped[str] = mapped_column(String(200), default="", index=True)
    locale: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(16), default=UserStatus.INVITED)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    mfa_method: Mapped[str] = mapped_column(String(16), default=MfaMethod.EMAIL)
    totp_secret_enc: Mapped[str | None] = mapped_column(String(255))
    # Last accepted TOTP time step, so a code cannot be used twice (FR-A12).
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    failed_code_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(default=clock.now, onupdate=clock.now)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}

    @property
    def role_enum(self) -> Role:
        return Role(self.role)

    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > clock.now()
