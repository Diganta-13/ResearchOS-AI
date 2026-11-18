"""Unit tests for local Ollama CPU provider using mocked HTTP transport."""

import json

import httpx
import pytest

from researchos.core.exceptions import (
    ModelError,
    ModelNotFoundError,
    ModelTimeoutError,
    ProviderUnavailableError,
)
from researchos.models.config import OllamaProviderConfig
from researchos.models.providers.ollama import OllamaProvider
from researchos.models.types import (
    ChatCompletionRequest,
    ChatMessage,
    MessageRole,
)


@pytest.mark.asyncio
async def test_ollama_completion_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "qwen2.5:1.5b"
        assert payload["stream"] is False
        assert payload["options"]["num_thread"] == 4  # CPU thread cap

        response_body = {
            "model": "qwen2.5:1.5b",
            "message": {"role": "assistant", "content": "Paris is the capital of France."},
            "done": True,
            "prompt_eval_count": 12,
            "eval_count": 8,
            "total_duration": 150000000,
        }
        return httpx.Response(200, json=response_body)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(config=OllamaProviderConfig(thread_limit=4), client=client)

    req = ChatCompletionRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role=MessageRole.USER, content="What is capital of France?")],
    )

    resp = await provider.complete(req)
    assert resp.model == "qwen2.5:1.5b"
    assert resp.provider == "ollama"
    assert resp.message.role == MessageRole.ASSISTANT
    assert "Paris" in resp.message.content
    assert resp.usage.prompt_tokens == 12
    assert resp.usage.completion_tokens == 8
    assert resp.usage.total_tokens == 20
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_ollama_streaming_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["stream"] is True

        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": False}),
            json.dumps({"message": {"content": "!"}, "done": True}),
        ]
        content = "\n".join(lines).encode("utf-8")
        return httpx.Response(200, content=content)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(client=client)

    req = ChatCompletionRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
        stream=True,
    )

    chunks = []
    async for chunk in provider.stream(req):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].delta_content == "Hello"
    assert chunks[1].delta_content == " world"
    assert chunks[2].delta_content == "!"
    assert chunks[2].finish_reason == "stop"


@pytest.mark.asyncio
async def test_ollama_model_not_found_404():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"error":"model \'nonexistent\' not found"}')

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(client=client)

    req = ChatCompletionRequest(
        model="nonexistent",
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    with pytest.raises(ModelNotFoundError) as exc_info:
        await provider.complete(req)
    assert "not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_server_error_500():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal engine fault")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(client=client)

    req = ChatCompletionRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    with pytest.raises(ModelError) as exc_info:
        await provider.complete(req)
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_provider_unavailable_connect_error():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by target daemon")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(client=client)

    req = ChatCompletionRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    )

    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.complete(req)
    assert "unreachable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_timeout_error():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out on socket")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(client=client)

    req = ChatCompletionRequest(
        model="qwen2.5:1.5b",
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
        timeout_seconds=5.0,
    )

    with pytest.raises(ModelTimeoutError) as exc_info:
        await provider.complete(req)
    assert "timed out" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ollama_health_and_list_models():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        data = {
            "models": [
                {"name": "qwen2.5:1.5b-instruct-q4_K_M", "size": 986000000},
                {"name": "llama3.2:3b-instruct-q4_K_M", "size": 2000000000},
            ]
        }
        return httpx.Response(200, json=data)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), base_url="http://127.0.0.1:11434"
    )
    provider = OllamaProvider(client=client)

    health = await provider.check_health()
    assert health.available is True
    assert health.provider == "ollama"
    assert len(health.models) == 2
    assert "qwen2.5:1.5b-instruct-q4_K_M" in health.models

    models = await provider.list_models()
    assert len(models) == 2
    assert models[0].name == "qwen2.5:1.5b-instruct-q4_K_M"

    assert await provider.is_model_available("qwen2.5:1.5b") is True
    assert await provider.is_model_available("nonexistent") is False
