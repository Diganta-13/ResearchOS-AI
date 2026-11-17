"""ResearchOS AI — Transactional Database Migration Runner."""

import hashlib
import re
from pathlib import Path
from typing import Any

from researchos.core.exceptions import MigrationError
from researchos.core.logging import get_logger
from researchos.memory.db import DatabaseManager

logger = get_logger("memory.migrations")


def split_sql_script(sql_content: str) -> list[str]:
    """
    Safely splits SQL content into executable statements without using executescript().
    Avoids executescript() implicit transaction COMMITs, and correctly handles
    semicolons nested inside CREATE TRIGGER ... BEGIN ... END; blocks and quotes.
    """
    statements: list[str] = []
    current_stmt: list[str] = []
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    trigger_depth = 0

    i = 0
    length = len(sql_content)

    while i < length:
        char = sql_content[i]
        next_char = sql_content[i + 1] if i + 1 < length else ""

        # Handle comments
        if not in_single_quote and not in_double_quote:
            if not in_block_comment and char == "-" and next_char == "-":
                in_line_comment = True
                i += 2
                continue
            if in_line_comment:
                if char == "\n":
                    in_line_comment = False
                i += 1
                continue
            if not in_line_comment and char == "/" and next_char == "*":
                in_block_comment = True
                i += 2
                continue
            if in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    i += 2
                else:
                    i += 1
                continue

        # Handle strings
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current_stmt.append(char)
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current_stmt.append(char)
            i += 1
            continue

        # Detect trigger block nesting (BEGIN ... END)
        if not in_single_quote and not in_double_quote:
            # Check for word boundary matches
            sub = sql_content[i:].upper()
            if re.match(r"\bBEGIN\b", sub):
                trigger_depth += 1
            elif re.match(r"\bEND\b", sub) and trigger_depth > 0:
                trigger_depth -= 1

            # Semicolon outside trigger block terminates statement
            if char == ";" and trigger_depth == 0:
                stmt_str = "".join(current_stmt).strip()
                if stmt_str:
                    statements.append(stmt_str)
                current_stmt = []
                i += 1
                continue

        current_stmt.append(char)
        i += 1

    remaining = "".join(current_stmt).strip()
    if remaining:
        statements.append(remaining)

    return statements


class MigrationRunner:
    """Discovers, validates checksums, and applies transactional database schema migrations."""

    def __init__(
        self, db_manager: DatabaseManager, migrations_dir: Path | str | None = None
    ) -> None:
        self.db = db_manager
        self.migrations_dir = Path(migrations_dir or Path(__file__).parent).resolve()

    def _ensure_migration_ledger_table(self) -> None:
        """Bootstraps the schema_migrations ledger if not yet present."""
        with self.db.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
                );
                """
            )

    def get_applied_migrations(self) -> dict[int, dict[str, Any]]:
        """Returns map of version -> {name, checksum, applied_at} for all recorded migrations."""
        self._ensure_migration_ledger_table()
        with self.db.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version ASC;"
            )
            return {
                row["version"]: {
                    "name": row["name"],
                    "checksum": row["checksum"],
                    "applied_at": row["applied_at"],
                }
                for row in cur.fetchall()
            }

    def discover_migrations(self) -> list[tuple[int, str, Path]]:
        """Finds all *.sql migration files in order (e.g., 001_initial_schema.sql)."""
        pattern = re.compile(r"^(\d+)_([a-zA-Z0-9_\-]+)\.sql$")
        discovered: list[tuple[int, str, Path]] = []

        if not self.migrations_dir.exists():
            return []

        for p in self.migrations_dir.glob("*.sql"):
            m = pattern.match(p.name)
            if m:
                version = int(m.group(1))
                name = m.group(2)
                discovered.append((version, name, p))

        return sorted(discovered, key=lambda x: x[0])

    def apply_migration(self, version: int, name: str, file_path: Path) -> bool:
        """
        Applies a single migration file atomically within an isolated transaction.
        Validates SHA-256 checksum against existing records.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        applied = self.get_applied_migrations()

        # Check for tampering of already-applied migrations
        if version in applied:
            recorded = applied[version]
            if recorded["checksum"] != checksum:
                raise MigrationError(
                    f"Checksum mismatch for migration {version} ('{name}'). "
                    f"Recorded '{recorded['checksum']}' != Actual '{checksum}'. "
                    "Schema migration file has been tampered with!"
                )
            logger.debug(f"Migration {version} ('{name}') already applied. Skipping.")
            return False

        # Execute statements inside an explicit atomic transaction
        statements = split_sql_script(content)
        logger.info(f"Applying migration {version} ('{name}') with {len(statements)} statements.")

        try:
            with self.db.transaction() as conn:
                cur = conn.cursor()
                for stmt in statements:
                    cur.execute(stmt)

                # Record successful migration in ledger
                cur.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum)
                    VALUES (?, ?, ?);
                    """,
                    (version, name, checksum),
                )
        except Exception as e:
            msg = f"Failed to apply migration {version} ('{name}'): {e}"
            logger.error(msg)
            raise MigrationError(msg) from e

        logger.info(f"Migration {version} ('{name}') successfully applied and recorded.")
        return True

    def run_all_migrations(self) -> list[int]:
        """Discovers and runs all pending migrations in ascending version sequence."""
        self._ensure_migration_ledger_table()
        discovered = self.discover_migrations()
        applied_versions: list[int] = []

        for version, name, path in discovered:
            if self.apply_migration(version, name, path):
                applied_versions.append(version)

        return applied_versions
