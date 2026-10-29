"""Object storage for encrypted file content.

Objects are written to a local volume outside the web root. Everything stored
is already encrypted with a per-file key, so the store never sees plaintext.
Another backend, such as an S3-compatible store, can implement the same three
methods later.
"""

import os
import secrets
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def keys(self) -> Iterator[str]: ...


def new_key() -> str:
    return secrets.token_hex(32)


class LocalDiskStore:
    def __init__(self, root: str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError("invalid storage key")
        # Two levels of fan-out keep directories small.
        return self.root / key[:2] / key[2:4] / key

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file, then rename, so a crash never leaves half a file.
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def keys(self) -> Iterator[str]:
        for path in self.root.glob("??/??/*"):
            if path.is_file() and len(path.name) == 64:
                yield path.name


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = LocalDiskStore(get_settings().storage_path)
    return _store


def set_store(store: ObjectStore | None) -> None:
    global _store
    _store = store
