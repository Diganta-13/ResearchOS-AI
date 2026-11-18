"""Unit tests for ModelGateway and provider registry."""

from collections.abc import AsyncGenerator

import pytest

from researchos.core.exceptions import (
    ModelNotFoundError,
    ProviderUnavailableError,
)
from researchos.models.base import BaseModelProvider
from researchos.models.config import ModelRoleConfig, ModelsConfig
from researchos.models.gateway import ModelGateway
from researchos.models.router import ModelRouter
from researchos.models.types import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    MessageRole,
    ModelInfo,
    ModelRole,
    ProviderHealth,
)


class MockProvider(BaseModelProvider):
    """Configurable mock provider for isolated gateway testing."""

    def __init__(self, name: str = "mock") -> None:
        self.provider_name = name
        self.should_fail_with: Exception | None = None
        self.recorded_requests: list[ChatCompletionRequest] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.recorded_requests.append(request)
        if self.should_fail_with:
            raise self.should_fail_with

        return ChatCompletionResponse(
            model=request.model,
            provider=self.provider_name,
            message=ChatMessage(
                role=MessageRole.ASSISTANT, content=f"Response from {request.model}"
            ),
        )

    async def stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        self.recorded_requests.append(request)
        if self.should_fail_with:
            raise self.should_fail_with

        yield ChatCompletionChunk(
            id="c1",
            model=request.model,
            provider=self.provider_name,
            delta_content=f"Token from {request.model}",
            finish_reason="stop",
        )

    async def check_health(self) -> ProviderHealth:
        if self.should_fail_with:
            return ProviderHealth(
                provider=self.provider_name, available=False, error_message="Mock error"
            )
        return ProviderHealth(provider=self.provider_name, available=True, models=["m1", "m2"])

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="m1"), ModelInfo(name="m2")]


@pytest.mark.asyncio
async def test_gateway_registration_and_lookup():
    gateway = ModelGateway(config=ModelsConfig())
    mock_prov = MockProvider(name="custom")
    gateway.register_provider("custom", mock_prov)

    assert "custom" in gateway.list_providers()
    assert gateway.get_provider("custom") is mock_prov

    with pytest.raises(ProviderUnavailableError):
        gateway.get_provider("nonexistent")


@pytest.mark.asyncio
async def test_gateway_complete_via_role():
    cfg = ModelsConfig(
        roles={
            "fast_router": ModelRoleConfig(provider="mock", model="fast-1b", temperature=0.1),
        }
    )
    router = ModelRouter(cfg)
    gateway = ModelGateway(config=cfg, router=router)
    mock_prov = MockProvider(name="mock")
    gateway.register_provider("mock", mock_prov)

    resp = await gateway.complete(
        role=ModelRole.FAST_ROUTER,
        messages=[ChatMessage(role=MessageRole.USER, content="Hello")],
    )

    assert resp.provider == "mock"
    assert resp.model == "fast-1b"
    assert resp.message.content == "Response from fast-1b"
    assert len(mock_prov.recorded_requests) == 1
    assert mock_prov.recorded_requests[0].temperature == 0.1


@pytest.mark.asyncio
async def test_gateway_auto_fallback_on_model_not_found():
    cfg = ModelsConfig(
        roles={
            "deep_reasoning": ModelRoleConfig(
                provider="mock", model="heavy-7b", fallback_model="light-3b"
            ),
        }
    )
    router = ModelRouter(cfg)
    gateway = ModelGateway(config=cfg, router=router)

    # Provider that fails on heavy-7b but succeeds on light-3b
    class FallbackMockProvider(MockProvider):
        async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
            self.recorded_requests.append(request)
            if request.model == "heavy-7b":
                raise ModelNotFoundError("heavy-7b not installed")
            return ChatCompletionResponse(
                model=request.model,
                provider=self.provider_name,
                message=ChatMessage(role=MessageRole.ASSISTANT, content="Fallback succeeded"),
            )

    provider = FallbackMockProvider(name="mock")
    gateway.register_provider("mock", provider)

    resp = await gateway.complete(
        role=ModelRole.DEEP_REASONING,
        messages=[ChatMessage(role=MessageRole.USER, content="Complex analysis")],
        auto_fallback=True,
    )

    assert resp.model == "light-3b"
    assert resp.message.content == "Fallback succeeded"
    assert len(provider.recorded_requests) == 2
    assert provider.recorded_requests[0].model == "heavy-7b"
    assert provider.recorded_requests[1].model == "light-3b"


@pytest.mark.asyncio
async def test_gateway_stream_via_role():
    cfg = ModelsConfig(
        roles={
            "fast_chat": ModelRoleConfig(provider="mock", model="chat-3b"),
        }
    )
    router = ModelRouter(cfg)
    gateway = ModelGateway(config=cfg, router=router)
    mock_prov = MockProvider(name="mock")
    gateway.register_provider("mock", mock_prov)

    chunks = []
    async for chunk in gateway.stream(
        role=ModelRole.FAST_CHAT,
        messages=[ChatMessage(role=MessageRole.USER, content="Hi")],
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].delta_content == "Token from chat-3b"


@pytest.mark.asyncio
async def test_gateway_health_checks():
    gateway = ModelGateway(config=ModelsConfig())
    mock_prov = MockProvider(name="mock")
    gateway.register_provider("mock", mock_prov)

    health_map = await gateway.check_health("mock")
    assert "mock" in health_map
    assert health_map["mock"].available is True
