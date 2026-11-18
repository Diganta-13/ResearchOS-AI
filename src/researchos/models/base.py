"""ResearchOS AI — Abstract Base Model Provider Interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from researchos.core.exceptions import ModelError
from researchos.models.types import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelInfo,
    ProviderHealth,
)


class BaseModelProvider(ABC):
    """Abstract interface standardizing all model execution backends."""

    provider_name: str = "base"

    @abstractmethod
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Executes a single non-streaming completion request."""
        ...

    @abstractmethod
    async def stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Streams completion tokens incrementally as server-sent chunks."""
        ...

    @abstractmethod
    async def check_health(self) -> ProviderHealth:
        """Checks provider connectivity, latency, and operational readiness."""
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Enumerates all installed or accessible models under this provider."""
        ...

    def count_tokens(self, text: str, model: str | None = None) -> int:
        """
        Estimates token count for text under this provider.
        Default implementation uses conservative heuristic. Providers may override with exact tokenizers.
        """
        from researchos.models.context import estimate_tokens

        return estimate_tokens(text)

    async def is_model_available(self, model_name: str) -> bool:
        """Helper checking if a specific model tag exists on the provider."""
        try:
            models = await self.list_models()
            model_tag = model_name.split(":")[0] if ":" in model_name else model_name
            for m in models:
                if m.name == model_name or m.name.startswith(f"{model_tag}:"):
                    return True
            return False
        except (ModelError, OSError):
            return False
