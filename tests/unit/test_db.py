"""Unit tests for SQLite database manager: WAL mode, foreign keys, and transaction guards."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from researchos.memory.db import DatabaseManager


def test_wal_mode_and_pragmas(isolated_db: DatabaseManager):
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode;")
        assert cur.fetchone()[0].lower() == "wal"

        cur.execute("PRAGMA foreign_keys;")
        assert cur.fetchone()[0] == 1

        cur.execute("PRAGMA busy_timeout;")
        assert cur.fetchone()[0] == 5000


def test_database_reopening(isolated_db: DatabaseManager):
    """Verifies that closing and reopening the database maintains WAL mode and data."""
    db_path = isolated_db.db_path

    # Insert test record in first instance
    with isolated_db.transaction() as conn:
        conn.execute("INSERT INTO conversations (id, title) VALUES (?, ?);", ("c1", "Session 1"))

    # Instantiate new DatabaseManager instance pointing to same file
    reopened_db = DatabaseManager(db_path)
    with reopened_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title FROM conversations WHERE id = 'c1';")
        assert cur.fetchone()[0] == "Session 1"
        cur.execute("PRAGMA journal_mode;")
        assert cur.fetchone()[0].lower() == "wal"


def test_foreign_key_cascade_deletion(isolated_db: DatabaseManager):
    with isolated_db.transaction() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?);", ("c_cascade", "Parent")
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?);",
            ("m1", "c_cascade", "user", "Hello"),
        )
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?);",
            ("m2", "c_cascade", "assistant", "Hi"),
        )

    # Verify messages exist
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = 'c_cascade';")
        assert cur.fetchone()[0] == 2

    # Delete conversation parent record
    with isolated_db.transaction() as conn:
        conn.execute("DELETE FROM conversations WHERE id = 'c_cascade';")

    # Verify messages were cascaded and deleted
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = 'c_cascade';")
        assert cur.fetchone()[0] == 0


def test_transaction_rollback_safety(isolated_db: DatabaseManager):
    """Verifies that an error inside transaction rolls back safely without double-faulting."""
    with pytest.raises(ValueError), isolated_db.transaction() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?);", ("c_roll", "Rollback Me")
        )
        raise ValueError("Forced error inside transaction")

    # Verify record was rolled back
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM conversations WHERE id = 'c_roll';")
        assert cur.fetchone()[0] == 0


def test_concurrent_readers(isolated_db: DatabaseManager):
    """Verifies multiple background threads can read concurrently while a transaction is active."""
    # Seed data
    with isolated_db.transaction() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title) VALUES (?, ?);", ("c_conc", "Concurrent Data")
        )

    def read_query(index: int) -> str:
        with isolated_db.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT title FROM conversations WHERE id = 'c_conc';")
            return cur.fetchone()[0]

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(read_query, i) for i in range(10)]
        results = [f.result() for f in futures]

    assert all(r == "Concurrent Data" for r in results)


def test_serialized_writers(isolated_db: DatabaseManager):
    """Verifies serialized writes succeed across threads."""

    def write_item(item_id: int):
        with isolated_db.transaction() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title) VALUES (?, ?);",
                (f"thread_{item_id}", f"Thread {item_id}"),
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(write_item, i) for i in range(8)]
        for f in futures:
            f.result()

    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM conversations WHERE id LIKE 'thread_%';")
        assert cur.fetchone()[0] == 8
