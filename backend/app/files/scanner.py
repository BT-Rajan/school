"""Virus scanning with ClamAV over the clamd INSTREAM protocol (FR-FS3)."""

import socket
import struct
from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings

CHUNK = 64 * 1024


@dataclass
class ScanResult:
    clean: bool
    detail: str


class ScannerUnavailable(Exception):
    pass


class Scanner(Protocol):
    def scan(self, content: bytes) -> ScanResult: ...


class ClamdScanner:
    def __init__(self, host: str, port: int, timeout: float = 60):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, content: bytes) -> ScanResult:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as conn:
                conn.sendall(b"zINSTREAM\0")
                for start in range(0, len(content), CHUNK):
                    chunk = content[start : start + CHUNK]
                    conn.sendall(struct.pack("!L", len(chunk)) + chunk)
                conn.sendall(struct.pack("!L", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    part = conn.recv(4096)
                    if not part:
                        break
                    reply += part
        except OSError as exc:
            raise ScannerUnavailable(str(exc)) from exc
        text = reply.rstrip(b"\0").decode(errors="replace")
        # "stream: OK" or "stream: <signature> FOUND"
        if text.endswith("OK"):
            return ScanResult(True, "OK")
        if text.endswith("FOUND"):
            return ScanResult(False, text.removeprefix("stream: ").removesuffix(" FOUND")[:200])
        raise ScannerUnavailable(f"unexpected clamd reply: {text[:200]}")


EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class DevelopmentScanner:
    """For development and tests only: flags the EICAR test string and nothing else."""

    def scan(self, content: bytes) -> ScanResult:
        if EICAR in content:
            return ScanResult(False, "Eicar-Test-Signature")
        return ScanResult(True, "OK (development scanner)")


_scanner: Scanner | None = None


def get_scanner() -> Scanner:
    global _scanner
    if _scanner is None:
        settings = get_settings()
        if settings.virus_scanner == "clamd":
            _scanner = ClamdScanner(settings.clamd_host, settings.clamd_port)
        else:
            _scanner = DevelopmentScanner()
    return _scanner


def set_scanner(scanner: Scanner | None) -> None:
    global _scanner
    _scanner = scanner
