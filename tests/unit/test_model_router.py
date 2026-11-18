"""Unit tests for intelligent model router and local-first policy."""

import pytest

from researchos.core.exceptions import CloudInferenceDisabledError
from researchos.models.config import ModelRoleConfig, ModelsConfig
from researchos.models.router import ModelRouter
from researchos.models.types import ModelRole


def test_router_local_role_resolution():
    cfg = ModelsConfig(
        cloud_enabled=False,
        roles={
            "fast_router": ModelRoleConfig(provider="ollama", model="qwen2.5:1.5b"),
            "deep_reasoning": ModelRoleConfig(
                provider="ollama", model="qwen2.5:7b", fallback_model="qwen2.5:3b"
            ),
        },
    )
    router = ModelRouter(cfg)

    provider, model, role_cfg = router.resolve_role(ModelRole.FAST_ROUTER)
    assert provider == "ollama"
    assert model == "qwen2.5:1.5b"
    assert role_cfg.model == "qwen2.5:1.5b"


def test_router_blocks_cloud_when_disabled():
    cfg = ModelsConfig(
        cloud_enabled=False,
        roles={
            "fast_chat": ModelRoleConfig(provider="gemini", model="gemini-2.0-flash"),
        },
    )
    router = ModelRouter(cfg)

    with pytest.raises(CloudInferenceDisabledError) as exc_info:
        router.resolve_role(ModelRole.FAST_CHAT)
    assert "disabled" in str(exc_info.value).lower()


def test_router_allows_cloud_when_enabled():
    cfg = ModelsConfig(
        cloud_enabled=True,
        roles={
            "fast_chat": ModelRoleConfig(provider="gemini", model="gemini-2.0-flash"),
        },
    )
    router = ModelRouter(cfg)

    provider, model, _ = router.resolve_role(ModelRole.FAST_CHAT)
    assert provider == "gemini"
    assert model == "gemini-2.0-flash"


def test_router_fallback_target():
    cfg = ModelsConfig(
        roles={
            "deep_reasoning": ModelRoleConfig(
                provider="ollama", model="qwen2.5:7b", fallback_model="qwen2.5:3b"
            ),
            "fast_router": ModelRoleConfig(
                provider="ollama", model="qwen2.5:1.5b", fallback_model=None
            ),
        }
    )
    router = ModelRouter(cfg)

    fallback = router.get_fallback_target(ModelRole.DEEP_REASONING)
    assert fallback == ("ollama", "qwen2.5:3b")

    no_fallback = router.get_fallback_target(ModelRole.FAST_ROUTER)
    assert no_fallback is None
