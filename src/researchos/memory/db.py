"""ResearchOS AI — SQLite Database Engine with WAL, Foreign Keys & Audit Integrity."""

import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from researchos.core.config import get_settings
from researchos.core.exceptions import (
    AuditIntegrityError,
    DatabaseConfigurationError,
)
from researchos.core.logging import get_logger

logger = get_logger("memory.db")


class DatabaseManager:
    """Thread-safe SQLite connection factory enforcing WAL mode, foreign keys, and safe transactions."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path or settings.paths.database_file).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_wal_initialized()

    def _ensure_wal_initialized(self) -> None:
        """Sets PRAGMA journal_mode=WAL during database file initialization."""
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode = WAL;")
            mode = cur.fetchone()[0]
            if mode.lower() != "wal":
                raise DatabaseConfigurationError(
                    f"Failed to initialize WAL mode on '{self.db_path}'. Current mode: {mode}"
                )
        finally:
            conn.close()

    def _create_connection(self) -> sqlite3.Connection:
        """Creates and configures a raw connection handle with strict pragmas."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            isolation_level=None,  # Autocommit mode; manual BEGIN/COMMIT control
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        try:
            # 1. Verify WAL mode persistence
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode;")
            mode = cur.fetchone()[0]
            if mode.lower() != "wal":
                conn.close()
                raise DatabaseConfigurationError(
                    f"WAL mode check failed on connection. Expected 'wal', got '{mode}'."
                )

            # 2. Enforce per-connection session constraints
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA cache_size = -64000;")  # 64 MiB page cache

            # 3. Verify FTS5 runtime availability
            self._verify_fts5_support(conn)

            return conn
        except Exception:
            conn.close()
            raise

    @staticmethod
    def _verify_fts5_support(conn: sqlite3.Connection) -> None:
        """Verifies that FTS5 full-text search is compiled and available in SQLite."""
        try:
            cur = conn.cursor()
            cur.execute("CREATE VIRTUAL TABLE temp._fts5_probe USING fts5(x);")
            cur.execute("DROP TABLE temp._fts5_probe;")
        except sqlite3.OperationalError as e:
            raise DatabaseConfigurationError(
                f"SQLite runtime lacks functional FTS5 support: {e}"
            ) from e

    def is_fts5_available(self) -> bool:
        """Checks if FTS5 is functional in the active database engine."""
        try:
            with self.connection() as conn:
                self._verify_fts5_support(conn)
                return True
        except (sqlite3.Error, DatabaseConfigurationError):
            return False

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing a configured connection with guaranteed closure."""
        conn = self._create_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Transactional context manager acquiring an immediate write lock.
        Guarantees rollback ONLY when conn.in_transaction is True,
        preventing secondary double-fault OperationalErrors.
        """
        with self.connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE;")
                yield conn
                conn.execute("COMMIT;")
            except Exception:
                if conn.in_transaction:
                    try:
                        conn.execute("ROLLBACK;")
                    except sqlite3.OperationalError:
                        pass
                raise

    # =========================================================================
    # Cryptographic Tamper-Evident Audit Logging
    # =========================================================================

    def log_audit_event(
        self,
        action: str,
        target: str,
        user_approved: bool = False,
        approval_token: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        """
        Appends an immutable audit event linked into a SHA-256 cryptographic hash-chain.
        Returns the computed entry hash.
        """
        with self.transaction() as conn:
            cur = conn.cursor()
            # Fetch the hash of the latest audit log entry
            cur.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1;")
            row = cur.fetchone()
            prev_hash = row[0] if row else "0" * 64

            timestamp = datetime.now(UTC).isoformat()
            details_json = json.dumps(details or {}, sort_keys=True)
            approved_int = 1 if user_approved else 0

            # Compute entry hash chaining with prev_hash
            raw_payload = f"{prev_hash}|{timestamp}|{action}|{target}|{approved_int}|{approval_token or ''}|{details_json}"
            entry_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

            cur.execute(
                """
                INSERT INTO audit_log (timestamp, action, target, user_approved, approval_token, details, prev_hash, entry_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    timestamp,
                    action,
                    target,
                    approved_int,
                    approval_token,
                    details_json,
                    prev_hash,
                    entry_hash,
                ),
            )
            return entry_hash

    def verify_audit_log_chain(self) -> tuple[bool, str]:
        """
        Traverses the audit log ledger and verifies SHA-256 hash chaining integrity.
        Raises AuditIntegrityError on any detected tampering or chain fracture.
        """
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, timestamp, action, target, user_approved, approval_token, details, prev_hash, entry_hash
                FROM audit_log
                ORDER BY id ASC;
                """
            )
            rows = cur.fetchall()

            expected_prev_hash = "0" * 64
            for row in rows:
                row_id = row["id"]
                timestamp = row["timestamp"]
                action = row["action"]
                target = row["target"]
                approved_int = row["user_approved"]
                token = row["approval_token"]
                details_json = row["details"] or "{}"
                prev_hash = row["prev_hash"]
                stored_entry_hash = row["entry_hash"]

                # 1. Verify link to previous entry
                if prev_hash != expected_prev_hash:
                    msg = (
                        f"Audit log chain fracture at entry ID {row_id}: "
                        f"recorded prev_hash '{prev_hash}' != expected '{expected_prev_hash}'"
                    )
                    logger.error(msg)
                    raise AuditIntegrityError(msg)

                # 2. Recompute current entry hash
                raw_payload = f"{prev_hash}|{timestamp}|{action}|{target}|{approved_int}|{token or ''}|{details_json}"
                recomputed_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

                if recomputed_hash != stored_entry_hash:
                    msg = (
                        f"Audit log tampering detected at entry ID {row_id}: "
                        f"computed hash '{recomputed_hash}' != stored hash '{stored_entry_hash}'"
                    )
                    logger.error(msg)
                    raise AuditIntegrityError(msg)

                expected_prev_hash = stored_entry_hash

            return True, f"Audit chain verified successfully ({len(rows)} entries)."
