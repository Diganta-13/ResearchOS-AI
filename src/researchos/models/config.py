"""ResearchOS AI — Configuration Models & Loader for Model Registry."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from researchos.core.config import get_settings
from researchos.core.exceptions import ConfigurationError
from researchos.models.types import ContextBudget, ModelRole


class OllamaProviderConfig(BaseModel):
    """Configuration for local Ollama CPU provider."""

    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 60.0
    connect_timeout_seconds: float = 5.0
    max_retries: int = 2
    thread_limit: int = 4  # Cap to 4 physical cores of i7-8665U
    keep_alive: str = "5m"


class ModelRoleConfig(BaseModel):
    """Configuration for a specific functional model role."""

    provider: str = "ollama"
    model: str
    fallback_model: str | None = None
    context_window: int = 4096
    temperature: float = 0.7
    max_tokens: int | None = None


class ModelsConfig(BaseModel):
    """Master configuration structure loaded from config/models.yaml."""

    version: str = "1.0.0"
    cloud_enabled: bool = False
    providers: dict[str, Any] = Field(default_factory=dict)
    roles: dict[str, ModelRoleConfig] = Field(default_factory=dict)

    def get_ollama_config(self) -> OllamaProviderConfig:
        """Extracts typed Ollama configuration with defaults."""
        raw = self.providers.get("ollama", {})
        if isinstance(raw, OllamaProviderConfig):
            return raw
        return OllamaProviderConfig(**raw)

    def get_role_config(self, role: ModelRole | str) -> ModelRoleConfig:
        """Resolves configuration for a given role enum or string."""
        key = role.value if isinstance(role, ModelRole) else str(role)
        if key not in self.roles:
            raise ConfigurationError(
                f"Model role '{key}' is not configured in models.yaml. "
                f"Configured roles: {list(self.roles.keys())}"
            )
        return self.roles[key]

    def get_context_budget(self, role: ModelRole | str) -> ContextBudget:
        """Constructs ContextBudget for the given role based on its context window and max output tokens."""
        role_cfg = self.get_role_config(role)
        max_output = role_cfg.max_tokens or (512 if "router" in str(role).lower() else 1024)
        return ContextBudget(
            context_window=role_cfg.context_window,
            max_output_tokens=max_output,
            safety_margin_tokens=50,
        )


def load_models_config(config_path: Path | None = None) -> ModelsConfig:
    """Loads and validates models.yaml with environment variable overrides."""
    settings = get_settings()
    if config_path is None:
        config_path = settings.paths.workspace_root / "config" / "models.yaml"
        if not config_path.exists():
            config_path = Path("config/models.yaml")

    data: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            raise ConfigurationError(f"Failed to parse '{config_path}': {e}") from e

    # Apply environment variable overrides if present
    if "RESEARCHOS_CLOUD_ENABLED" in os.environ:
        data["cloud_enabled"] = os.environ["RESEARCHOS_CLOUD_ENABLED"].lower() in (
            "1",
            "true",
            "yes",
        )

    if "RESEARCHOS_OLLAMA_BASE_URL" in os.environ:
        providers = data.setdefault("providers", {})
        ollama = providers.setdefault("ollama", {})
        ollama["base_url"] = os.environ["RESEARCHOS_OLLAMA_BASE_URL"]

    # Role overrides (e.g. RESEARCHOS_MODEL_FAST_ROUTER=qwen2.5:1.5b)
    roles = data.setdefault("roles", {})
    for role_enum in ModelRole:
        env_key = f"RESEARCHOS_MODEL_{role_enum.name}"
        if env_key in os.environ:
            role_dict = roles.setdefault(role_enum.value, {"model": os.environ[env_key]})
            role_dict["model"] = os.environ[env_key]

    return ModelsConfig(**data)
