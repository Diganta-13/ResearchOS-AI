"""Unit tests for transactional database migration manager."""

from pathlib import Path

import pytest

from researchos.core.exceptions import MigrationError
from researchos.memory.db import DatabaseManager
from researchos.memory.migrations.runner import MigrationRunner, split_sql_script


def test_split_sql_script():
    sql = """
    -- Test SQL script
    CREATE TABLE t1 (id INT PRIMARY KEY);
    /* Block comment */
    CREATE TRIGGER trg1 AFTER INSERT ON t1
    BEGIN
        SELECT 1;
        SELECT 2;
    END;
    INSERT INTO t1 VALUES (1);
    """
    stmts = split_sql_script(sql)
    assert len(stmts) == 3
    assert "CREATE TABLE t1" in stmts[0]
    assert "CREATE TRIGGER trg1" in stmts[1]
    assert "SELECT 1;" in stmts[1]
    assert "END" in stmts[1]
    assert "INSERT INTO t1 VALUES (1)" in stmts[2]


def test_migration_execution_and_idempotency(isolated_db: DatabaseManager):
    runner = MigrationRunner(isolated_db)
    applied = runner.get_applied_migrations()
    assert 1 in applied
    assert applied[1]["name"] == "initial_schema"
    assert len(applied[1]["checksum"]) == 64

    # Running migrations again returns empty list (idempotent)
    reapplied = runner.run_all_migrations()
    assert reapplied == []


def test_migration_checksum_tamper_detection(isolated_db: DatabaseManager, test_temp_dir: Path):
    """Verifies that altering an already-applied migration file raises MigrationError."""
    fake_migrations_dir = test_temp_dir / "fake_migrations"
    fake_migrations_dir.mkdir(parents=True, exist_ok=True)

    mig_file = fake_migrations_dir / "001_test_migration.sql"
    mig_file.write_text("CREATE TABLE test_table (id INT);", encoding="utf-8")

    db = DatabaseManager(test_temp_dir / "test_tamper.db")
    runner = MigrationRunner(db, migrations_dir=fake_migrations_dir)
    applied = runner.run_all_migrations()
    assert applied == [1]

    # Tamper with the migration file content
    mig_file.write_text("CREATE TABLE test_table (id INT, modified INT);", encoding="utf-8")

    # Re-running must detect checksum mismatch
    with pytest.raises(MigrationError) as exc_info:
        runner.run_all_migrations()
    assert "Checksum mismatch" in str(exc_info.value) or "tampered" in str(exc_info.value)


def test_migration_transaction_rollback_on_failure(
    isolated_db: DatabaseManager, test_temp_dir: Path
):
    """Verifies that an invalid SQL migration rolls back completely without committing partial state."""
    fake_migrations_dir = test_temp_dir / "fail_migrations"
    fake_migrations_dir.mkdir(parents=True, exist_ok=True)

    bad_mig = fake_migrations_dir / "002_broken.sql"
    bad_mig.write_text(
        """
        CREATE TABLE should_rollback (id INT);
        THIS IS INVALID SQL STATEMENT;
        """,
        encoding="utf-8",
    )

    runner = MigrationRunner(isolated_db, migrations_dir=fake_migrations_dir)
    with pytest.raises(MigrationError):
        runner.run_all_migrations()

    # Verify table should_rollback was rolled back and does not exist
    with isolated_db.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='should_rollback';")
        assert cur.fetchone() is None
