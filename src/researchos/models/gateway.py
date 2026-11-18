"""ResearchOS AI — Unified Model Gateway & Provider Registry."""

from collections.abc import AsyncGenerator

from researchos.core.exceptions import (
    ConfigurationError,
    ModelNotFoundError,
    ProviderUnavailableError,
)
from researchos.core.logging import get_logger
from researchos.models.base import BaseModelProvider
from researchos.models.config import ModelsConfig, load_models_config
from researchos.models.providers.ollama import OllamaProvider
from researchos.models.router import ModelRouter
from researchos.models.types import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelRole,
    ProviderHealth,
)

logger = get_logger("models.gateway")


class ModelGateway:
    """
    Central Model Gateway managing provider registration, role-based routing,
    fallback recovery, and health verification.
    """

    def __init__(
        self,
        config: ModelsConfig | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        self.config = config or load_models_config()
        self.router = router or ModelRouter(self.config)
        self._providers: dict[str, BaseModelProvider] = {}
        self._initialize_default_providers()

    def _initialize_default_providers(self) -> None:
        """Initializes default local Ollama provider from configuration."""
        ollama_cfg = self.config.get_ollama_config()
        self.register_provider("ollama", OllamaProvider(ollama_cfg))

    def register_provider(self, name: str, provider: BaseModelProvider) -> None:
        """Registers an AI provider under an identifier."""
        self._providers[name.lower()] = provider
        logger.info(f"Registered model provider: {name.lower()}")

    def get_provider(self, name: str) -> BaseModelProvider:
        """Retrieves a registered provider or raises ProviderUnavailableError."""
        key = name.lower()
        if key not in self._providers:
            raise ProviderUnavailableError(
                f"Provider '{name}' is not registered. Available providers: {list(self._providers.keys())}"
            )
        return self._providers[key]

    def list_providers(self) -> list[str]:
        """Lists names of all registered providers."""
        return list(self._providers.keys())

    async def check_health(self, provider_name: str | None = None) -> dict[str, ProviderHealth]:
        """Checks health of one or all registered providers."""
        results: dict[str, ProviderHealth] = {}
        if provider_name:
            provider = self.get_provider(provider_name)
            results[provider_name.lower()] = await provider.check_health()
        else:
            for name, provider in self._providers.items():
                results[name] = await provider.check_health()
        return results

    async def complete(
        self,
        role: ModelRole | str | None = None,
        messages: list[ChatMessage] | None = None,
        request: ChatCompletionRequest | None = None,
        auto_fallback: bool = True,
    ) -> ChatCompletionResponse:
        """
        Executes a chat completion via role-based routing or direct request.
        Applies automatic fallback if the primary model fails or is unavailable.
        """
        if request is None and (role is None or messages is None):
            raise ConfigurationError(
                "Must provide either a ChatCompletionRequest or (role, messages)."
            )

        provider_name = "ollama"
        model_name = ""
        role_key: ModelRole | str | None = role

        if role is not None:
            provider_name, model_name, role_cfg = self.router.resolve_role(role)
            if request is None:
                request = ChatCompletionRequest(
                    model=model_name,
                    messages=messages or [],
                    temperature=role_cfg.temperature,
                    max_tokens=role_cfg.max_tokens,
                )
            else:
                request = request.model_copy(update={"model": model_name})
        elif request is not None:
            model_name = request.model

        provider = self.get_provider(provider_name)

        try:
            return await provider.complete(request)
        except (ProviderUnavailableError, ModelNotFoundError) as e:
            if not auto_fallback or role_key is None:
                raise

            fallback_target = self.router.get_fallback_target(role_key)
            if not fallback_target:
                raise

            fallback_provider_name, fallback_model = fallback_target
            logger.warning(
                f"Primary model '{model_name}' on '{provider_name}' failed ({e}). "
                f"Triggering fallback to '{fallback_model}' on '{fallback_provider_name}'."
            )

            fallback_provider = self.get_provider(fallback_provider_name)
            fallback_request = request.model_copy(update={"model": fallback_model})
            return await fallback_provider.complete(fallback_request)

    async def stream(
        self,
        role: ModelRole | str | None = None,
        messages: list[ChatMessage] | None = None,
        request: ChatCompletionRequest | None = None,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Streams completion tokens incrementally using role-based routing."""
        if request is None and (role is None or messages is None):
            raise ConfigurationError(
                "Must provide either a ChatCompletionRequest or (role, messages)."
            )

        provider_name = "ollama"
        if role is not None:
            provider_name, model_name, role_cfg = self.router.resolve_role(role)
            if request is None:
                request = ChatCompletionRequest(
                    model=model_name,
                    messages=messages or [],
                    temperature=role_cfg.temperature,
                    max_tokens=role_cfg.max_tokens,
                    stream=True,
                )
            else:
                request = request.model_copy(update={"model": model_name, "stream": True})

        provider = self.get_provider(provider_name)
        async for chunk in provider.stream(request):
            yield chunk
