"""ResearchOS AI — Security Boundaries, Process Harness & Approval Gate."""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import psutil

from researchos.core.config import get_settings
from researchos.core.exceptions import (
    ApprovalRequiredError,
    PathContainmentError,
    SubprocessExecutionError,
)
from researchos.core.logging import get_logger

logger = get_logger("core.security")

# Explicit statement of architectural boundary:
# Application-level approval gating and subprocess allowlisting DO NOT constitute an OS-level sandbox.
IS_OS_LEVEL_SANDBOX: bool = False


class RiskTier(str, Enum):
    """Tiered risk classification for operations."""

    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    CONSEQUENTIAL_EXECUTION = "consequential_execution"


class ApprovalTokenManager:
    """Manages single-use cryptographic approval tokens for consequential operations."""

    def __init__(self, secret_key: str | None = None, expiry_seconds: int = 300) -> None:
        settings = get_settings()
        self.secret_key = (secret_key or settings.approval_secret_key).encode("utf-8")
        self.expiry_seconds = expiry_seconds
        self._consumed_tokens: set[str] = set()

    def generate_token(self, action: str, target: str) -> str:
        """Generates an HMAC-SHA256 signed approval token incorporating timestamp."""
        timestamp = time.time()
        payload_data = json.dumps(
            {"action": action, "target": target, "ts": timestamp},
            separators=(",", ":"),
        )
        encoded_payload = base64.urlsafe_b64encode(payload_data.encode("utf-8")).decode("ascii")
        signature = hmac.new(
            self.secret_key, encoded_payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"{encoded_payload}.{signature}"

    def validate_and_consume_token(
        self, token: str, expected_action: str, expected_target: str
    ) -> bool:
        """Validates token signature, expiration, and consumes it against replay attacks."""
        if not token or token in self._consumed_tokens:
            raise ApprovalRequiredError("Approval token has already been consumed or is missing.")

        parts = token.split(".")
        if len(parts) != 2:
            raise ApprovalRequiredError("Malformed approval token structure.")

        encoded_payload, signature = parts
        expected_sig = hmac.new(
            self.secret_key, encoded_payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            raise ApprovalRequiredError("Invalid approval token signature.")

        try:
            raw_json = base64.urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8")
            data = json.loads(raw_json)
            action = data["action"]
            target = data["target"]
            timestamp = float(data["ts"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            raise ApprovalRequiredError("Malformed approval token structure.") from None

        # Verify expiration
        current_time = time.time()
        if (current_time - timestamp) > self.expiry_seconds:
            raise ApprovalRequiredError("Approval token has expired.")

        # Verify action and target match
        if action != expected_action or target != expected_target:
            raise ApprovalRequiredError(
                f"Token target mismatch: token for '{action}:{target}', requested '{expected_action}:{expected_target}'."
            )

        # Consume token to prevent replay
        self._consumed_tokens.add(token)
        return True


def validate_path_containment(
    target_path: Path | str, allowed_root: Path | str | None = None
) -> Path:
    """
    Enforces strict path containment within Drive D: workspace and storage roots.
    Prevents path traversal and writing to Drive C:.
    """
    settings = get_settings()
    path = Path(target_path).resolve()
    root = Path(allowed_root or settings.paths.workspace_root).resolve()

    # Reject Drive C: target writes
    if path.drive.upper() == "C:":
        raise PathContainmentError(
            f"Path containment violation: '{path}' targets Drive C:. All operations must reside on Drive D:."
        )

    # Verify path is contained within the allowed root
    try:
        path.relative_to(root)
    except ValueError:
        raise PathContainmentError(
            f"Path traversal detected: Target '{path}' escapes allowed root '{root}'."
        ) from None

    return path


class SecurityHarness:
    """
    Restricted process execution harness.
    Enforces executable allowlisting, argument sanitization, path containment, and process tree timeouts.
    """

    ALLOWED_EXECUTABLES: ClassVar[set[str]] = {
        "git",
        "git.exe",
        "pdflatex",
        "pdflatex.exe",
        "python",
        "python.exe",
    }

    DISALLOWED_CHARS: ClassVar[set[str]] = {";", "&", "|", ">", "<", "`", "$"}

    def __init__(self, token_manager: ApprovalTokenManager | None = None) -> None:
        self.token_manager = token_manager or ApprovalTokenManager()

    def run_command(
        self,
        command_args: list[str],
        cwd: Path | str,
        timeout_seconds: int = 30,
        risk_tier: RiskTier = RiskTier.READ_ONLY,
        approval_token: str | None = None,
    ) -> dict[str, Any]:
        """
        Executes an allowlisted subprocess safely with shell=False, sanitized env, and process tree termination.
        """
        if not command_args:
            raise SubprocessExecutionError("Empty command array provided.")

        raw_binary = command_args[0]
        binary_name = Path(raw_binary).name.lower()

        # 1. Allowlist Enforcement
        if binary_name not in self.ALLOWED_EXECUTABLES:
            raise SubprocessExecutionError(
                f"Execution rejected: '{binary_name}' is not an approved executable. "
                f"Approved binaries: {sorted(self.ALLOWED_EXECUTABLES)}"
            )

        # 2. Argument Validation (Static Injection Prevention)
        for arg in command_args:
            if any(char in arg for char in self.DISALLOWED_CHARS):
                raise SubprocessExecutionError(
                    f"Argument injection attempt: Argument contains prohibited characters {self.DISALLOWED_CHARS}: '{arg}'"
                )

        # 3. Path Containment on CWD
        working_dir = validate_path_containment(cwd)

        # 4. Approval Gate Enforcement
        if risk_tier == RiskTier.CONSEQUENTIAL_EXECUTION:
            action_desc = f"run:{binary_name}"
            self.token_manager.validate_and_consume_token(
                approval_token or "", expected_action=action_desc, expected_target=str(working_dir)
            )

        # 5. Sanitized Environment Setup
        settings = get_settings()
        clean_env = os.environ.copy()
        clean_env["OLLAMA_MODELS"] = str(settings.paths.ollama_models)
        clean_env["HF_HOME"] = str(settings.paths.huggingface_cache)
        clean_env["PIP_CACHE_DIR"] = str(settings.paths.pip_cache)
        clean_env["TEMP"] = str(settings.paths.temp_dir)
        clean_env["TMP"] = str(settings.paths.temp_dir)
        clean_env["OMP_NUM_THREADS"] = str(settings.max_worker_threads)
        clean_env["MKL_NUM_THREADS"] = str(settings.max_worker_threads)

        logger.info(
            f"Executing verified subprocess: {command_args[0]} in {working_dir}",
            extra={"details": {"args": command_args, "cwd": str(working_dir)}},
        )

        start_time = time.time()
        proc = None
        try:
            proc = subprocess.Popen(
                command_args,
                cwd=str(working_dir),
                env=clean_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,  # Strictly shell=False
            )

            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            duration = round(time.time() - start_time, 3)

            return {
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_seconds": duration,
                "command": command_args,
            }

        except subprocess.TimeoutExpired:
            # Terminate entire process tree cleanly using psutil
            if proc:
                try:
                    parent = psutil.Process(proc.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            raise SubprocessExecutionError(
                f"Command timed out after {timeout_seconds} seconds: {command_args}"
            ) from None
        except Exception as e:
            if isinstance(e, SubprocessExecutionError):
                raise
            raise SubprocessExecutionError(f"Subprocess invocation failure: {e}") from e
