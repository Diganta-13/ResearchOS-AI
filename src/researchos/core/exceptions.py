"""ResearchOS AI — Comprehensive Domain Exception Hierarchy."""


class ResearchOSError(Exception):
    """Base exception for all ResearchOS domain errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# =====================================================================
# Configuration & Storage Errors
# =====================================================================


class ConfigurationError(ResearchOSError):
    """Raised when application configuration is missing, invalid, or unparseable."""


class StorageIsolationError(ConfigurationError):
    """Raised when a storage path violates Drive C: isolation or Drive D: workspace policies."""


# =====================================================================
# Security & Process Execution Errors
# =====================================================================


class SecurityError(ResearchOSError):
    """Base exception for security boundary violations."""


class PathContainmentError(SecurityError):
    """Raised when a file operation attempts directory traversal or escapes workspace boundaries."""


class SubprocessExecutionError(SecurityError):
    """Raised when an unallowlisted executable, invalid argument, or timeout occurs."""


class ApprovalRequiredError(SecurityError):
    """Raised when a consequential operation is attempted without a valid human approval token."""


class AuditIntegrityError(SecurityError):
    """Raised when the cryptographic hash-chain of the audit log fails verification."""


# =====================================================================
# Database & Migration Errors
# =====================================================================


class DatabaseError(ResearchOSError):
    """Base exception for database failures."""


class DatabaseConfigurationError(DatabaseError):
    """Raised when database PRAGMAs (WAL mode, foreign keys, busy timeout) fail enforcement."""


class MigrationError(DatabaseError):
    """Raised when a schema migration fails to execute or exhibits a checksum mismatch."""


# =====================================================================
# Agent Lifecycle & Orchestration Errors
# =====================================================================


class StateTransitionError(ResearchOSError):
    """Raised when an illegal or non-deterministic agent state transition is attempted."""


# =====================================================================
# Model & Provider Errors
# =====================================================================


class ModelError(ResearchOSError):
    """Base exception for all AI model and provider operations."""


class ProviderUnavailableError(ModelError):
    """Raised when an AI provider endpoint is unreachable, offline, or unresponsive."""


class ModelNotFoundError(ModelError):
    """Raised when a requested model is not found in the provider's active catalog."""


class ModelTimeoutError(ModelError):
    """Raised when a model inference request exceeds the configured timeout."""


class CloudInferenceDisabledError(ModelError):
    """Raised when cloud inference is attempted while disabled in configuration."""


class ModelContextLimitError(ModelError):
    """Raised when prompt tokens exceed the model's configured context window."""
