-- ResearchOS AI — Initial Schema Migration (Version 1)
-- Targets SQLite WAL mode with Foreign Key integrity, tamper-evident audit log, and FTS5 external content triggers

-- 1. Schema Migration History Ledger
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- 2. Append-Only, Tamper-Evident Cryptographic Audit Log
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    user_approved INTEGER NOT NULL DEFAULT 0,
    approval_token TEXT,
    details TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);

-- Prevent unauthorized update or deletion of audit logs via SQLite triggers
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Audit log entries are tamper-evident and append-only: updates disallowed.');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Audit log entries are tamper-evident and append-only: deletions disallowed.');
END;

-- 3. Conversation & Message Threading
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);

-- 4. Agent Task Planning & Steps
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    plan TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

CREATE TABLE IF NOT EXISTS task_steps (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    risk_tier TEXT NOT NULL DEFAULT 'read_only',
    requires_approval INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id);

-- 5. Persistent Knowledge & Memory Items
CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

CREATE INDEX IF NOT EXISTS idx_memory_items_category ON memory_items(category);

-- 6. FTS5 External Content Full-Text Search Virtual Table
CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory_items USING fts5(
    content,
    content='memory_items',
    content_rowid='rowid'
);

-- 7. Atomic Triggers Synchronizing fts_memory_items with memory_items
CREATE TRIGGER IF NOT EXISTS trg_memory_items_ai
AFTER INSERT ON memory_items
BEGIN
    INSERT INTO fts_memory_items(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_items_ad
AFTER DELETE ON memory_items
BEGIN
    INSERT INTO fts_memory_items(fts_memory_items, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_items_au
AFTER UPDATE ON memory_items
BEGIN
    INSERT INTO fts_memory_items(fts_memory_items, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO fts_memory_items(rowid, content)
    VALUES (new.rowid, new.content);
END;
