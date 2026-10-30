"""Section 13.1: no feature removes data permanently."""

from app.main import create_app

DESTRUCTIVE_WORDS = ("purge", "destroy", "erase", "wipe", "hard-delete", "hard_delete")
# Signing out a device: the session is marked revoked, and its row stays.
REVOKES_ONLY = {"/api/auth/sessions/{session_id}"}


def test_no_endpoint_removes_a_record_permanently():
    paths = create_app().openapi()["paths"]
    assert len(paths) > 100
    # Nothing is deleted through the API: records are deactivated, withdrawn or soft-deleted
    # (marked and hidden), and restored the same way.
    assert [p for p, methods in paths.items() if "delete" in methods and p not in REVOKES_ONLY] == []
    assert [p for p in paths if any(w in p.lower() for w in DESTRUCTIVE_WORDS)] == []
