from enum import IntEnum, StrEnum


class Role(StrEnum):
    DISTRICT_ADMIN = "district_admin"
    FORM_AUTHOR = "form_author"
    CLUSTER_HEAD = "cluster_head"
    SUPERVISOR = "supervisor"
    TEACHER = "teacher"


class UserStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    INACTIVE = "inactive"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MfaMethod(StrEnum):
    EMAIL = "email"
    TOTP = "totp"


class ChallengePurpose(StrEnum):
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"
    ENROLL_TOTP = "enroll_totp"


class MailPriority(IntEnum):
    SECURITY = 1
    INVITATION = 2
    REMINDER = 3
    INFORMATIONAL = 4


class BudgetClass(StrEnum):
    # Security mail may use the whole daily limit, including the reserve.
    RESERVED = "reserved"
    GENERAL = "general"


class MailStatus(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    DIGEST_PENDING = "digest_pending"
    DIGESTED = "digested"
    SENT = "sent"
    FAILED = "failed"
