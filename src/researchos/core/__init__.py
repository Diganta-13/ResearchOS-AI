"""Core module: exceptions, configuration, logging, and security boundaries."""

from researchos.core.config import Settings, get_settings
from researchos.core.exceptions import (
    ApprovalRequiredError,
    AuditIntegrityError,
    ConfigurationError,
    DatabaseConfigurationError,
    DatabaseError,
    MigrationError,
    PathContainmentError,
    ResearchOSError,
    SecurityError,
    StateTransitionError,
    StorageIsolationError,
    SubprocessExecutionError,
)
from researchos.core.logging import get_logger, setup_logging
from researchos.core.security import ApprovalTokenManager, RiskTier, SecurityHarness

__all__ = [
    "ApprovalRequiredError",
    "ApprovalTokenManager",
    "AuditIntegrityError",
    "ConfigurationError",
    "DatabaseConfigurationError",
    "DatabaseError",
    "MigrationError",
    "PathContainmentError",
    "ResearchOSError",
    "RiskTier",
    "SecurityError",
    "SecurityHarness",
    "Settings",
    "StateTransitionError",
    "StorageIsolationError",
    "SubprocessExecutionError",
    "get_logger",
    "get_settings",
    "setup_logging",
]
