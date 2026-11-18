"""ResearchOS AI — Models & Inference Package."""

from researchos.models.base import BaseModelProvider
from researchos.models.config import (
    ModelRoleConfig,
    ModelsConfig,
    OllamaProviderConfig,
    load_models_config,
)
from researchos.models.context import (
    ContextManager,
    estimate_message_tokens,
    estimate_tokens,
    truncate_tool_output,
)
from researchos.models.gateway import ModelGateway
from researchos.models.providers.ollama import OllamaProvider
from researchos.models.router import ModelRouter
from researchos.models.types import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ContextBudget,
    ContextDiagnostics,
    MessageRole,
    ModelInfo,
    ModelRole,
    ProviderHealth,
    TokenUsage,
)

__all__ = [
    "BaseModelProvider",
    "ChatCompletionChunk",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "ContextBudget",
    "ContextDiagnostics",
    "ContextManager",
    "MessageRole",
    "ModelGateway",
    "ModelInfo",
    "ModelRole",
    "ModelRoleConfig",
    "ModelRouter",
    "ModelsConfig",
    "OllamaProvider",
    "OllamaProviderConfig",
    "ProviderHealth",
    "TokenUsage",
    "estimate_message_tokens",
    "estimate_tokens",
    "load_models_config",
    "truncate_tool_output",
]
