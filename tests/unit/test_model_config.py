"""Unit tests for models configuration loading and role resolution."""

import pytest

from researchos.core.exceptions import ConfigurationError
from researchos.models.config import (
    ModelRoleConfig,
    ModelsConfig,
    OllamaProviderConfig,
    load_models_config,
)
from researchos.models.types import ModelRole


def test_models_config_defaults():
    cfg = ModelsConfig()
    assert cfg.version == "1.0.0"
    assert cfg.cloud_enabled is False
    assert isinstance(cfg.get_ollama_config(), OllamaProviderConfig)
    assert cfg.get_ollama_config().thread_limit == 4


def test_load_models_config_from_yaml():
    cfg = load_models_config()
    assert cfg.version == "1.0.0"
    assert cfg.cloud_enabled is False

    # Check that standard roles are configured
    fast_router = cfg.get_role_config(ModelRole.FAST_ROUTER)
    assert isinstance(fast_router, ModelRoleConfig)
    assert "qwen2.5:1.5b" in fast_router.model
    assert fast_router.provider == "ollama"

    deep = cfg.get_role_config(ModelRole.DEEP_REASONING)
    assert "qwen2.5:7b" in deep.model
    assert deep.fallback_model is not None


def test_get_role_config_invalid_role():
    cfg = ModelsConfig()
    with pytest.raises(ConfigurationError) as exc_info:
        cfg.get_role_config("nonexistent_role")
    assert "not configured" in str(exc_info.value)


def test_environment_variable_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RESEARCHOS_CLOUD_ENABLED", "true")
    monkeypatch.setenv("RESEARCHOS_OLLAMA_BASE_URL", "http://192.168.1.50:11434")
    monkeypatch.setenv("RESEARCHOS_MODEL_FAST_ROUTER", "custom:1b")

    cfg = load_models_config()
    assert cfg.cloud_enabled is True
    assert cfg.get_ollama_config().base_url == "http://192.168.1.50:11434"
    assert cfg.get_role_config(ModelRole.FAST_ROUTER).model == "custom:1b"
