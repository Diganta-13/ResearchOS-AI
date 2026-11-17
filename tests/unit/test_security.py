"""Unit tests for security boundaries, subprocess harness, and approval tokens."""

import time
from pathlib import Path

import pytest

from researchos.core.config import get_settings
from researchos.core.exceptions import (
    ApprovalRequiredError,
    PathContainmentError,
    SubprocessExecutionError,
)
from researchos.core.security import (
    IS_OS_LEVEL_SANDBOX,
    ApprovalTokenManager,
    RiskTier,
    SecurityHarness,
    validate_path_containment,
)


def test_os_sandbox_disclaimer():
    """Confirms architecture explicitly documents that application controls are not OS sandboxes."""
    assert IS_OS_LEVEL_SANDBOX is False


def test_approval_token_issuance_and_consumption():
    mgr = ApprovalTokenManager(secret_key="test-secret", expiry_seconds=60)
    token = mgr.generate_token(action="run:test", target="workspace")
    assert token is not None

    # First consumption succeeds
    assert (
        mgr.validate_and_consume_token(
            token, expected_action="run:test", expected_target="workspace"
        )
        is True
    )

    # Replay attack fails
    with pytest.raises(ApprovalRequiredError):
        mgr.validate_and_consume_token(
            token, expected_action="run:test", expected_target="workspace"
        )


def test_approval_token_expiration():
    mgr = ApprovalTokenManager(secret_key="test-secret", expiry_seconds=1)
    token = mgr.generate_token(action="run:exp", target="target")
    time.sleep(1.2)  # Wait for expiration

    with pytest.raises(ApprovalRequiredError) as exc_info:
        mgr.validate_and_consume_token(token, expected_action="run:exp", expected_target="target")
    assert "expired" in str(exc_info.value).lower()


def test_path_containment():
    settings = get_settings()
    workspace = settings.paths.workspace_root

    # Valid internal paths
    valid = validate_path_containment(workspace / "src" / "researchos")
    assert valid.exists() or str(valid).startswith(str(workspace))

    # Reject Drive C: path
    with pytest.raises(PathContainmentError):
        validate_path_containment("C:/Windows/System32")

    # Reject path traversal escaping root
    with pytest.raises(PathContainmentError):
        validate_path_containment(workspace / ".." / "OtherProject")


def test_security_harness_disallowed_binary(test_temp_dir: Path):
    harness = SecurityHarness()
    with pytest.raises(SubprocessExecutionError) as exc_info:
        harness.run_command(["powershell.exe", "-Command", "Get-Process"], cwd=test_temp_dir)
    assert "not an approved executable" in str(exc_info.value)


def test_security_harness_argument_injection(test_temp_dir: Path):
    harness = SecurityHarness()
    with pytest.raises(SubprocessExecutionError) as exc_info:
        harness.run_command(["git", "status;", "rm", "-rf"], cwd=test_temp_dir)
    assert "Argument injection attempt" in str(exc_info.value)


def test_security_harness_consequential_approval_gate(test_temp_dir: Path):
    token_mgr = ApprovalTokenManager(secret_key="test-secret")
    harness = SecurityHarness(token_manager=token_mgr)

    # Consequential command without token must fail
    with pytest.raises(ApprovalRequiredError):
        harness.run_command(
            ["python.exe", "--version"],
            cwd=test_temp_dir,
            risk_tier=RiskTier.CONSEQUENTIAL_EXECUTION,
            approval_token=None,
        )

    # Consequential command with valid token succeeds
    action = "run:python.exe"
    token = token_mgr.generate_token(action=action, target=str(test_temp_dir.resolve()))
    result = harness.run_command(
        ["python.exe", "--version"],
        cwd=test_temp_dir,
        risk_tier=RiskTier.CONSEQUENTIAL_EXECUTION,
        approval_token=token,
    )
    assert result["exit_code"] == 0
    assert "Python" in (result["stdout"] + result["stderr"])
