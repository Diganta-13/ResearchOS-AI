"""Unit tests for AI model types and response contracts."""

from researchos.models.types import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    MessageRole,
    ModelInfo,
    ModelRole,
    ProviderHealth,
    TokenUsage,
)


def test_model_role_enum():
    assert ModelRole.FAST_ROUTER == "fast_router"
    assert ModelRole.TOOL_CALLER == "tool_caller"
    assert ModelRole.FAST_CHAT == "fast_chat"
    assert ModelRole.DEEP_REASONING == "deep_reasoning"


def test_chat_message_creation():
    msg = ChatMessage(role=MessageRole.USER, content="Explain quantum entanglement")
    assert msg.role == MessageRole.USER
    assert msg.content == "Explain quantum entanglement"
    assert msg.name is None


def test_chat_completion_request_defaults():
    req = ChatCompletionRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role=MessageRole.USER, content="Hello")],
    )
    assert req.model == "qwen2.5:1.5b"
    assert req.temperature == 0.7
    assert req.stream is False
    assert req.timeout_seconds == 60.0
    assert req.options == {}


def test_chat_completion_response_contract():
    resp = ChatCompletionResponse(
        model="llama3.2:3b",
        provider="ollama",
        message=ChatMessage(role=MessageRole.ASSISTANT, content="Test output"),
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        duration_seconds=0.42,
    )
    assert resp.model == "llama3.2:3b"
    assert resp.provider == "ollama"
    assert resp.message.content == "Test output"
    assert resp.usage.total_tokens == 15
    assert resp.duration_seconds == 0.42
    assert resp.id.startswith("resp_")


def test_chat_completion_chunk():
    chunk = ChatCompletionChunk(
        id="chunk_1",
        model="qwen2.5:1.5b",
        provider="ollama",
        delta_content="token",
        finish_reason=None,
    )
    assert chunk.delta_content == "token"
    assert chunk.finish_reason is None


def test_provider_health_model():
    health = ProviderHealth(
        provider="ollama",
        available=True,
        latency_ms=12.5,
        models=["qwen2.5:1.5b", "llama3.2:3b"],
    )
    assert health.available is True
    assert health.latency_ms == 12.5
    assert len(health.models) == 2


def test_model_info_model():
    info = ModelInfo(
        name="qwen2.5:1.5b",
        size_bytes=986000000,
        family="qwen2",
    )
    assert info.name == "qwen2.5:1.5b"
    assert info.size_bytes == 986000000
    assert info.family == "qwen2"
