"""Unit tests for configuration loading, storage isolation, and threshold checks."""

from pathlib import Path

import pytest

from researchos.core.config import Settings, StoragePaths
from researchos.core.exceptions import StorageIsolationError


def test_settings_load_defaults():
    settings = Settings()
    assert settings.app_name == "ResearchOS AI"
    assert settings.storage_target_drive == "D:"
    assert settings.paths.workspace_root.drive.upper() == "D:"
    assert settings.paths.storage_root.drive.upper() == "D:"


def test_drive_c_rejection():
    with pytest.raises(StorageIsolationError) as exc_info:
        StoragePaths(storage_root=Path("C:/Users/test/storage"))
    assert "Drive C:" in str(exc_info.value) or "D:" in str(exc_info.value)


def test_yaml_config_loading():
    settings = Settings.load_from_yaml()
    assert settings.spec_version == "2.1.0"
    assert settings.isolation_policy.drive_c_protection == "ENFORCED"
    assert settings.paths.database_file.name == "researchos.db"


def test_disk_threshold_audit():
    settings = Settings()
    audit = settings.verify_disk_thresholds()
    assert "drive_c" in audit
    assert "drive_d" in audit
    assert isinstance(audit["drive_c"]["free_gib"], float)
    assert isinstance(audit["drive_d"]["free_gib"], float)
    assert audit["drive_c"]["compliant"] is True
    assert audit["drive_d"]["compliant"] is True
