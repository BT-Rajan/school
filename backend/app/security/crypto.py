"""Encryption for secrets stored in the database, such as TOTP keys (FR-A13)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def _key() -> bytes:
    key = base64.urlsafe_b64decode(get_settings().encryption_key + "==")
    if len(key) != 32:
        raise ValueError("SCES_ENCRYPTION_KEY must be 32 bytes, base64url encoded")
    return key


def encrypt(plaintext: str, *, context: str) -> str:
    """AES-256-GCM. The context string is bound as associated data."""
    nonce = os.urandom(12)
    sealed = AESGCM(_key()).encrypt(nonce, plaintext.encode(), context.encode())
    return base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt(token: str, *, context: str) -> str:
    raw = base64.urlsafe_b64decode(token)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], context.encode()).decode()


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


# Envelope encryption for stored files (FR-D50): each file has its own random data
# key; only the data key, wrapped with the master key, is kept in the database.


def new_data_key() -> bytes:
    return os.urandom(32)


def wrap_key(data_key: bytes, *, context: str) -> str:
    return encrypt(base64.urlsafe_b64encode(data_key).decode(), context=f"wrap:{context}")


def unwrap_key(wrapped: str, *, context: str) -> bytes:
    return base64.urlsafe_b64decode(decrypt(wrapped, context=f"wrap:{context}"))


def seal(data: bytes, key: bytes, *, context: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, context.encode())


def open_sealed(blob: bytes, key: bytes, *, context: str) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], context.encode())
