"""ResearchOS AI — Intelligent Model Router with Local-First Policy."""

from researchos.core.exceptions import (
    CloudInferenceDisabledError,
    ConfigurationError,
)
from researchos.core.logging import get_logger
from researchos.models.config import ModelRoleConfig, ModelsConfig, load_models_config
from researchos.models.types import ModelRole

logger = get_logger("models.router")

CLOUD_PROVIDERS: set[str] = {
    "gemini",
    "claude",
    "anthropic",
    "openai",
    "azure",
    "mistral",
    "groq",
}


def is_cloud_provider(name: str) -> bool:
    """Returns True if provider targets remote cloud endpoints."""
    return name.lower() in CLOUD_PROVIDERS


class ModelRouter:
    """
    Intelligent model routing engine enforcing local-first AI policy.
    Resolves functional roles to concrete providers and models with fallback chains.
    """

    def __init__(self, config: ModelsConfig | None = None) -> None:
        self.config = config or load_models_config()

    def resolve_role(self, role: ModelRole | str) -> tuple[str, str, ModelRoleConfig]:
        """
        Resolves a functional role to (provider_name, model_name, role_config).
        Enforces cloud opt-in boundaries and local defaults.
        """
        role_key = role.value if isinstance(role, ModelRole) else str(role)
        role_config = self.config.get_role_config(role_key)

        provider_name = role_config.provider.lower()
        model_name = role_config.model

        # Guard against unauthorized cloud routing
        if is_cloud_provider(provider_name) and not self.config.cloud_enabled:
            raise CloudInferenceDisabledError(
                f"Role '{role_key}' targets cloud provider '{provider_name}', "
                "but cloud inference is currently disabled in configuration."
            )

        return provider_name, model_name, role_config

    def get_fallback_target(self, role: ModelRole | str) -> tuple[str, str] | None:
        """
        Returns (provider_name, fallback_model) if a fallback model is configured.
        Returns None if no fallback is available.
        """
        role_key = role.value if isinstance(role, ModelRole) else str(role)
        try:
            role_config = self.config.get_role_config(role_key)
        except ConfigurationError:
            return None

        if role_config.fallback_model:
            # Fallback always defaults to local provider unless cloud is explicitly enabled
            return role_config.provider, role_config.fallback_model

        return None
