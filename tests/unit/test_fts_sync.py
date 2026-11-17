"""Unit tests for SQLite FTS5 external content synchronization triggers."""

from researchos.memory.db import DatabaseManager


def test_fts5_runtime_availability(isolated_db: DatabaseManager):
    """Verifies that FTS5 is compiled and functional in the host SQLite runtime."""
    assert isolated_db.is_fts5_available() is True
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("CREATE VIRTUAL TABLE temp._fts5_test USING fts5(x);")
        cur.execute("INSERT INTO temp._fts5_test (x) VALUES ('fts5 verification test');")
        cur.execute("SELECT * FROM temp._fts5_test WHERE _fts5_test MATCH 'verification';")
        assert len(cur.fetchall()) == 1
        cur.execute("DROP TABLE temp._fts5_test;")


def test_fts5_insert_synchronization(isolated_db: DatabaseManager):
    """Verifies that INSERT on memory_items automatically populates fts_memory_items."""
    with isolated_db.transaction() as conn:
        conn.execute(
            "INSERT INTO memory_items (id, category, content) VALUES (?, ?, ?);",
            ("mem_1", "research", "Transformer attention mechanisms in vision models"),
        )

    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT rowid FROM fts_memory_items WHERE fts_memory_items MATCH 'attention';")
        rows = cur.fetchall()
        assert len(rows) == 1


def test_fts5_delete_synchronization(isolated_db: DatabaseManager):
    """Verifies that DELETE on memory_items removes records from fts_memory_items."""
    with isolated_db.transaction() as conn:
        conn.execute(
            "INSERT INTO memory_items (id, category, content) VALUES (?, ?, ?);",
            ("mem_del", "study", "Quicksort algorithm recursive partitioning"),
        )

    # Confirm searchable
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT rowid FROM fts_memory_items WHERE fts_memory_items MATCH 'Quicksort';")
        assert len(cur.fetchall()) == 1

    # Delete row
    with isolated_db.transaction() as conn:
        conn.execute("DELETE FROM memory_items WHERE id = 'mem_del';")

    # Verify removed from FTS5
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT rowid FROM fts_memory_items WHERE fts_memory_items MATCH 'Quicksort';")
        assert len(cur.fetchall()) == 0


def test_fts5_update_synchronization(isolated_db: DatabaseManager):
    """Verifies that UPDATE on memory_items updates fts_memory_items accordingly."""
    with isolated_db.transaction() as conn:
        conn.execute(
            "INSERT INTO memory_items (id, category, content) VALUES (?, ?, ?);",
            ("mem_upd", "notes", "Original draft on convolutional neural networks"),
        )

    # Update content
    with isolated_db.transaction() as conn:
        conn.execute(
            "UPDATE memory_items SET content = ? WHERE id = ?;",
            ("Updated draft on graph neural networks and diffusion", "mem_upd"),
        )

    # Old term should no longer match
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT rowid FROM fts_memory_items WHERE fts_memory_items MATCH 'convolutional';"
        )
        assert len(cur.fetchall()) == 0

        # New term should match
        cur.execute("SELECT rowid FROM fts_memory_items WHERE fts_memory_items MATCH 'diffusion';")
        assert len(cur.fetchall()) == 1
