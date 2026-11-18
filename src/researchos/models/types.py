"""ResearchOS AI — Common Response & Request Schemas for AI Intelligence Engine."""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ModelRole(str, Enum):
    """Functional roles for intelligent model routing."""

    FAST_ROUTER = "fast_router"
    TOOL_CALLER = "tool_caller"
    FAST_CHAT = "fast_chat"
    DEEP_REASONING = "deep_reasoning"


class MessageRole(str, Enum):
    """Standard message roles across all model providers."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """Discrete message in a conversational thread."""

    role: MessageRole
    content: str
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    """Standardized completion request across all providers."""

    model: str
    messages: list[ChatMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    options: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    """Token consumption accounting."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    """Standardized non-streaming completion response."""

    id: str = Field(default_factory=lambda: f"resp_{uuid4().hex[:12]}")
    model: str
    provider: str
    message: ChatMessage
    finish_reason: str = "stop"
    usage: TokenUsage = Field(default_factory=TokenUsage)
    duration_seconds: float = 0.0
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ChatCompletionChunk(BaseModel):
    """Single incremental chunk in an active streaming response."""

    id: str
    model: str
    provider: str
    delta_content: str = ""
    finish_reason: str | None = None


class ModelInfo(BaseModel):
    """Metadata describing an installed or available model."""

    name: str
    size_bytes: int | None = None
    modified_at: str | None = None
    digest: str | None = None
    family: str | None = None


class ProviderHealth(BaseModel):
    """Health status and diagnostic telemetry for an AI provider."""

    provider: str
    available: bool
    latency_ms: float | None = None
    models: list[str] = Field(default_factory=list)
    error_message: str | None = None


class ContextBudget(BaseModel):
    """Configurable token limits and allocation for an active inference step."""

    context_window: int = Field(default=4096, gt=0)
    max_output_tokens: int = Field(default=1024, gt=0)
    safety_margin_tokens: int = Field(default=50, ge=0)

    @property
    def max_input_tokens(self) -> int:
        """Computes available input token budget after reserving output and safety buffer."""
        available = self.context_window - self.max_output_tokens - self.safety_margin_tokens
        if available <= 0:
            from researchos.core.exceptions import ConfigurationError

            raise ConfigurationError(
                f"Invalid context budget: context_window ({self.context_window}) must be strictly greater "
                f"than max_output_tokens ({self.max_output_tokens}) + safety_margin_tokens ({self.safety_margin_tokens})."
            )
        return available


class ContextDiagnostics(BaseModel):
    """Telemetry report describing context window budgeting and message pruning."""

    total_input_messages: int
    retained_messages: int
    pruned_messages: int
    estimated_input_tokens: int
    max_input_budget: int
    context_window: int
    max_output_tokens: int
    has_pruned: bool
    truncated_tool_messages: int = 0
