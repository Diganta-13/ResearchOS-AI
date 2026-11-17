"""Unit tests for cryptographic append-only tamper-evident audit logging."""

import sqlite3

import pytest

from researchos.core.exceptions import AuditIntegrityError
from researchos.memory.db import DatabaseManager


def test_audit_log_append_and_hash_chain(isolated_db: DatabaseManager):
    """Verifies that audit events link into a continuous SHA-256 hash chain."""
    h1 = isolated_db.log_audit_event(
        action="init_session", target="session:1", details={"ip": "127.0.0.1"}
    )
    assert len(h1) == 64

    h2 = isolated_db.log_audit_event(
        action="write_scratchpad", target="file:notes.txt", user_approved=True
    )
    assert len(h2) == 64
    assert h1 != h2

    # Verify chain integrity
    valid, msg = isolated_db.verify_audit_log_chain()
    assert valid is True
    assert "2 entries" in msg


def test_audit_log_sqlite_triggers_prevent_update_delete(isolated_db: DatabaseManager):
    """Verifies that SQLite triggers prohibit UPDATE and DELETE on audit_log."""
    isolated_db.log_audit_event(action="test_action", target="test_target")

    # Attempting UPDATE must fail by trigger
    with pytest.raises(sqlite3.DatabaseError) as exc_info, isolated_db.connection() as conn:
        conn.execute("UPDATE audit_log SET action = 'tampered' WHERE id = 1;")
    assert "tamper-evident" in str(exc_info.value) or "disallowed" in str(exc_info.value)

    # Attempting DELETE must fail by trigger
    with pytest.raises(sqlite3.DatabaseError) as exc_info, isolated_db.connection() as conn:
        conn.execute("DELETE FROM audit_log WHERE id = 1;")
    assert "tamper-evident" in str(exc_info.value) or "disallowed" in str(exc_info.value)


def test_audit_log_tamper_detection(isolated_db: DatabaseManager):
    """Verifies that tampering with historical hashes triggers AuditIntegrityError."""
    isolated_db.log_audit_event(action="event1", target="target1")
    isolated_db.log_audit_event(action="event2", target="target2")

    # Temporarily drop triggers in raw connection to simulate external file tampering
    with isolated_db.connection() as conn:
        conn.execute("DROP TRIGGER trg_audit_log_no_update;")
        # Tamper with an action without updating the entry_hash
        conn.execute("UPDATE audit_log SET action = 'malicious_modification' WHERE id = 1;")

    # Verification must detect the tampering and fail
    with pytest.raises(AuditIntegrityError) as exc_info:
        isolated_db.verify_audit_log_chain()
    assert "tampering detected" in str(exc_info.value).lower()
