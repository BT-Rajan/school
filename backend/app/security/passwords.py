"""Password hashing and policy (FR-A7, FR-A11)."""

import hashlib
import logging
from functools import lru_cache
from importlib import resources

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

log = logging.getLogger(__name__)

MIN_LENGTH = 10
_hasher = PasswordHasher()
# Verified against when the email is unknown, so timing does not reveal accounts.
_DUMMY_HASH = _hasher.hash("not-a-real-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


@lru_cache
def _common_passwords() -> frozenset[str]:
    text = resources.files("app.security").joinpath("common_passwords.txt").read_text()
    return frozenset(line.strip().lower() for line in text.splitlines() if line.strip())


def _breached_online(password: str) -> bool:
    digest = hashlib.sha1(password.encode()).hexdigest().upper()  # noqa: S324 - required by the API
    try:
        response = httpx.get(f"https://api.pwnedpasswords.com/range/{digest[:5]}", timeout=3)
        response.raise_for_status()
    except httpx.HTTPError:
        log.warning("breached password check unavailable")
        return False
    return any(line.split(":")[0] == digest[5:] for line in response.text.splitlines())


def policy_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """Return an error code if the password is not acceptable, else None."""
    if len(password) < MIN_LENGTH:
        return "password_too_short"
    lowered = password.lower()
    if lowered in _common_passwords():
        return "password_breached"
    local_part = email.split("@")[0].lower()
    if (local_part and len(local_part) >= 4 and local_part in lowered) or (name and lowered == name.lower()):
        return "password_contains_identity"
    if get_settings().breached_password_api and _breached_online(password):
        return "password_breached"
    return None
