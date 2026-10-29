"""Random tokens, one-time codes and their keyed hashes (FR-A2, FR-A7, FR-A14)."""

import base64
import hashlib
import hmac
import secrets

from app.config import get_settings


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def keyed_hash(*parts: str) -> str:
    """HMAC-SHA256 over the parts, keyed with the deployment secret."""
    message = "\x1f".join(parts).encode()
    return hmac.new(get_settings().secret_key.encode(), message, hashlib.sha256).hexdigest()


def new_numeric_code(digits: int = 6) -> str:
    return f"{secrets.randbelow(10**digits):0{digits}d}"


def new_recovery_code() -> str:
    """Ten base32 characters shown as xxxxx-xxxxx."""
    raw = base64.b32encode(secrets.token_bytes(10)).decode().lower()[:10]
    return f"{raw[:5]}-{raw[5:]}"


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
