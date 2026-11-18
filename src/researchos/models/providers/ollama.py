"""ResearchOS AI — Local Ollama CPU Model Provider Adapter."""

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from researchos.core.exceptions import (
    ModelError,
    ModelNotFoundError,
    ModelTimeoutError,
    ProviderUnavailableError,
)
from researchos.core.logging import get_logger
from researchos.models.base import BaseModelProvider
from researchos.models.config import OllamaProviderConfig
from researchos.models.types import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    MessageRole,
    ModelInfo,
    ProviderHealth,
    TokenUsage,
)

logger = get_logger("models.providers.ollama")


class OllamaProvider(BaseModelProvider):
    """
    Local Ollama inference adapter tailored for CPU execution.
    Enforces hardware thread caps (4 threads for Intel i7-8665U) and zero cloud dependency.
    """

    provider_name: str = "ollama"

    def __init__(
        self,
        config: OllamaProviderConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or OllamaProviderConfig()
        self._custom_client = client

    def _get_client(self, timeout_seconds: float | None = None) -> httpx.AsyncClient:
        """Returns injected client or instantiates configured httpx client."""
        if self._custom_client:
            return self._custom_client
        timeout = timeout_seconds or self.config.timeout_seconds
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(timeout, connect=self.config.connect_timeout_seconds),
        )

    def _build_payload(
        self, request: ChatCompletionRequest, stream: bool = False
    ) -> dict[str, Any]:
        """Constructs Ollama /api/chat payload with CPU optimization options."""
        messages_payload = [
            {
                "role": msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role),
                "content": msg.content,
            }
            for msg in request.messages
        ]

        # Enforce CPU optimization options (4 threads to prevent thermal throttling on 15W TDP)
        options: dict[str, Any] = {
            "num_thread": self.config.thread_limit,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        options.update(request.options)

        return {
            "model": request.model,
            "messages": messages_payload,
            "stream": stream,
            "options": options,
            "keep_alive": self.config.keep_alive,
        }

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Executes a single non-streaming chat completion."""
        payload = self._build_payload(request, stream=False)
        start_time = time.time()
        client = self._get_client(request.timeout_seconds)

        try:
            should_close = client is not self._custom_client
            try:
                response = await client.post("/api/chat", json=payload)
            finally:
                if should_close:
                    await client.aclose()

            if response.status_code == 404:
                raise ModelNotFoundError(
                    f"Model '{request.model}' not found in local Ollama catalog."
                )

            if response.is_error:
                raise ModelError(f"Ollama error {response.status_code}: {response.text}")

            data = response.json()
            duration = round(time.time() - start_time, 3)

            msg_data = data.get("message", {})
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)

            return ChatCompletionResponse(
                model=request.model,
                provider=self.provider_name,
                message=ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=msg_data.get("content", ""),
                ),
                finish_reason="stop" if data.get("done", True) else "length",
                usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
                duration_seconds=duration,
            )

        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ProviderUnavailableError(
                f"Ollama daemon is unreachable at '{self.config.base_url}'. "
                "Ensure local Ollama service is running."
            ) from e
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(
                f"Ollama request for '{request.model}' timed out after {request.timeout_seconds}s."
            ) from e

    async def stream(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Streams completion tokens incrementally as server-sent chunks."""
        payload = self._build_payload(request, stream=True)
        client = self._get_client(request.timeout_seconds)
        should_close = client is not self._custom_client

        try:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code == 404:
                    raise ModelNotFoundError(
                        f"Model '{request.model}' not found in local Ollama catalog."
                    )
                if response.is_error:
                    error_text = await response.aread()
                    raise ModelError(
                        f"Ollama streaming error {response.status_code}: {error_text.decode('utf-8', errors='replace')}"
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk_data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    delta_content = chunk_data.get("message", {}).get("content", "")
                    done = chunk_data.get("done", False)

                    yield ChatCompletionChunk(
                        id=f"chunk_{int(time.time() * 1000)}",
                        model=request.model,
                        provider=self.provider_name,
                        delta_content=delta_content,
                        finish_reason="stop" if done else None,
                    )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ProviderUnavailableError(
                f"Ollama daemon is unreachable at '{self.config.base_url}' during stream."
            ) from e
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(
                f"Ollama stream for '{request.model}' timed out after {request.timeout_seconds}s."
            ) from e
        finally:
            if should_close:
                await client.aclose()

    async def check_health(self) -> ProviderHealth:
        """Probes Ollama daemon responsiveness and retrieves installed models."""
        client = self._get_client(self.config.connect_timeout_seconds)
        start_time = time.time()
        should_close = client is not self._custom_client

        try:
            response = await client.get("/api/tags")
            duration_ms = round((time.time() - start_time) * 1000, 2)
            if response.status_code == 200:
                data = response.json()
                models = [m.get("name", "") for m in data.get("models", []) if "name" in m]
                return ProviderHealth(
                    provider=self.provider_name,
                    available=True,
                    latency_ms=duration_ms,
                    models=models,
                )
            return ProviderHealth(
                provider=self.provider_name,
                available=False,
                error_message=f"HTTP {response.status_code}: {response.text}",
            )
        except (httpx.HTTPError, OSError) as e:
            return ProviderHealth(
                provider=self.provider_name,
                available=False,
                error_message=str(e),
            )
        finally:
            if should_close:
                await client.aclose()

    async def list_models(self) -> list[ModelInfo]:
        """Lists metadata for all installed local models."""
        client = self._get_client(self.config.connect_timeout_seconds)
        should_close = client is not self._custom_client

        try:
            response = await client.get("/api/tags")
            if response.status_code == 200:
                data = response.json()
                results: list[ModelInfo] = []
                for item in data.get("models", []):
                    details = item.get("details", {})
                    results.append(
                        ModelInfo(
                            name=item.get("name", ""),
                            size_bytes=item.get("size"),
                            modified_at=item.get("modified_at"),
                            digest=item.get("digest"),
                            family=details.get("family"),
                        )
                    )
                return results
            raise ModelError(f"Failed to fetch models from Ollama: HTTP {response.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise ProviderUnavailableError(
                f"Ollama daemon unreachable at '{self.config.base_url}'"
            ) from e
        finally:
            if should_close:
                await client.aclose()
