"""ResearchOS AI — Centralized Configuration & Storage Policy Enforcement."""

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from researchos.core.exceptions import ConfigurationError, StorageIsolationError


class StoragePaths(BaseModel):
    """Explicit mapping of all storage, cache, and workspace directories."""

    workspace_root: Path = Path("D:/Projects/ResearchOS-AI")
    storage_root: Path = Path("D:/Projects/ResearchOS-AI/storage")
    database_dir: Path = Path("D:/Projects/ResearchOS-AI/storage/db")
    database_file: Path = Path("D:/Projects/ResearchOS-AI/storage/db/researchos.db")
    ollama_models: Path = Path("D:/Projects/ResearchOS-AI/storage/.ollama/models")
    huggingface_cache: Path = Path("D:/Projects/ResearchOS-AI/storage/.cache/huggingface")
    fastembed_cache: Path = Path("D:/Projects/ResearchOS-AI/storage/.cache/fastembed")
    pip_cache: Path = Path("D:/Projects/ResearchOS-AI/storage/.cache/pip")
    temp_dir: Path = Path("D:/Projects/ResearchOS-AI/storage/.cache/tmp")
    vector_index: Path = Path("D:/Projects/ResearchOS-AI/storage/vector_index")
    documents: Path = Path("D:/Projects/ResearchOS-AI/storage/documents")
    scratchpad: Path = Path("D:/Projects/ResearchOS-AI/storage/scratchpad")
    logs: Path = Path("D:/Projects/ResearchOS-AI/storage/logs")

    @field_validator("*", mode="after")
    @classmethod
    def validate_target_drive(cls, v: Any) -> Any:
        """Enforces that all persistent paths reside on Drive D: to protect Drive C:."""
        if isinstance(v, Path):
            path_str = str(v.resolve()) if v.is_absolute() else str(v)
            drive = Path(path_str).drive.upper()
            if drive and drive != "D:":
                raise StorageIsolationError(
                    f"Storage isolation violation: Path '{path_str}' points to drive '{drive}'. "
                    "All persistent project data must reside strictly on Drive D:."
                )
        return v


class IsolationPolicy(BaseModel):
    """Storage isolation and capacity protection constraints."""

    drive_c_protection: str = "ENFORCED"
    drive_c_min_free_threshold_gib: float = 15.0
    drive_d_installation_threshold_gib: float = 130.0
    drive_d_operational_reserve_gib: float = 50.0
    allow_c_drive_writes: bool = False


class Settings(BaseSettings):
    """Master application configuration for ResearchOS AI."""

    app_name: str = "ResearchOS AI"
    app_version: str = "0.1.0"
    spec_version: str = "2.1.0"
    environment: str = Field(default="development")
    storage_target_drive: str = "D:"
    paths: StoragePaths = Field(default_factory=StoragePaths)
    isolation_policy: IsolationPolicy = Field(default_factory=IsolationPolicy)

    # Security & API Configurations
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    approval_secret_key: str = "researchos-ephemeral-local-secret-change-in-prod"
    token_expiry_seconds: int = 300  # 5 minutes for consequential operation approval

    # Hardware Caps
    max_worker_threads: int = 4  # OMP_NUM_THREADS / MKL_NUM_THREADS cap for i7-8665U

    model_config = SettingsConfigDict(
        env_prefix="RESEARCHOS_",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def load_from_yaml(cls, yaml_path: Path | None = None) -> "Settings":
        """Loads configuration from storage_paths.yaml, merging with environment variables."""
        if yaml_path is None:
            # Look in standard config directory relative to workspace root
            yaml_path = Path("D:/Projects/ResearchOS-AI/config/storage_paths.yaml")
            if not yaml_path.exists():
                yaml_path = Path("config/storage_paths.yaml")

        if not yaml_path.exists():
            return cls()

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            paths_data = data.get("paths", {})
            iso_data = data.get("isolation_policy", {})

            # Map legacy YAML keys if present
            if "drive_c_min_free_threshold_gb" in iso_data:
                iso_data["drive_c_min_free_threshold_gib"] = iso_data.pop(
                    "drive_c_min_free_threshold_gb"
                )

            paths = StoragePaths(**paths_data) if paths_data else StoragePaths()
            isolation = IsolationPolicy(**iso_data) if iso_data else IsolationPolicy()

            return cls(
                spec_version=data.get("version", "2.1.0"),
                storage_target_drive=data.get("storage_target_drive", "D:"),
                paths=paths,
                isolation_policy=isolation,
            )
        except Exception as e:
            if isinstance(e, StorageIsolationError):
                raise
            raise ConfigurationError(f"Failed to load configuration from '{yaml_path}': {e}") from e

    def verify_disk_thresholds(self) -> dict[str, Any]:
        """Audits host drive capacities and validates threshold compliance."""
        try:
            c_usage = shutil.disk_usage("C:")
            c_free_gib = c_usage.free / (1024**3)
        except OSError:
            c_free_gib = 0.0

        try:
            d_usage = shutil.disk_usage("D:")
            d_free_gib = d_usage.free / (1024**3)
        except OSError:
            d_free_gib = 0.0

        c_pass = c_free_gib >= self.isolation_policy.drive_c_min_free_threshold_gib
        d_pass = d_free_gib >= self.isolation_policy.drive_d_installation_threshold_gib

        return {
            "drive_c": {
                "free_gib": round(c_free_gib, 2),
                "threshold_gib": self.isolation_policy.drive_c_min_free_threshold_gib,
                "compliant": c_pass,
            },
            "drive_d": {
                "free_gib": round(d_free_gib, 2),
                "threshold_gib": self.isolation_policy.drive_d_installation_threshold_gib,
                "compliant": d_pass,
            },
        }

    def ensure_directories(self) -> None:
        """Safely creates all configured persistent storage directories on Drive D:."""
        for name, path in self.paths.model_dump().items():
            if name == "database_file":
                # Ensure parent directory of DB file exists
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            else:
                Path(path).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns singleton settings instance loaded from YAML and environment."""
    return Settings.load_from_yaml()
