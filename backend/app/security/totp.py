"""Authenticator app codes, RFC 6238 (FR-A12)."""

from datetime import UTC

import pyotp

from app import clock

STEP_SECONDS = 30
DRIFT_STEPS = 1


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, *, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def current_step() -> int:
    return int(clock.now().replace(tzinfo=UTC).timestamp() // STEP_SECONDS)


def code_at_step(secret: str, step: int) -> str:
    return pyotp.TOTP(secret).at(step * STEP_SECONDS)


def matching_step(secret: str, code: str, last_used_step: int | None) -> int | None:
    """Return the time step the code belongs to, if valid and not yet used.

    One step of drift either way is accepted. A step at or before the last
    accepted one is rejected, so a code cannot be replayed.
    """
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    now_step = current_step()
    for step in range(now_step - DRIFT_STEPS, now_step + DRIFT_STEPS + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if pyotp.utils.strings_equal(code_at_step(secret, step), code):
            return step
    return None
