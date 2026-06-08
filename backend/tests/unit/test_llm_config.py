import importlib.util
from pathlib import Path


def load_llm_config_module():
    module_path = Path(__file__).resolve().parents[2] / "agents" / "shared" / "llm.py"
    spec = importlib.util.spec_from_file_location("llm_config_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_get_llm_config_prefers_generic_env(monkeypatch):
    llm_config = load_llm_config_module()
    monkeypatch.setenv("LLM_API_KEY", "generic-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://generic.example/v1")
    monkeypatch.setenv("LLM_MODEL", "generic-model")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-model")

    assert llm_config.get_llm_config() == {
        "api_key": "generic-key",
        "base_url": "https://generic.example/v1",
        "model": "generic-model",
    }


def test_get_llm_config_falls_back_to_deepseek_env(monkeypatch):
    llm_config = load_llm_config_module()
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-model")

    assert llm_config.get_llm_config() == {
        "api_key": "deepseek-key",
        "base_url": "https://deepseek.example",
        "model": "deepseek-model",
    }


def test_create_chat_llm_returns_none_without_api_key(monkeypatch):
    llm_config = load_llm_config_module()
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert llm_config.create_chat_llm() is None
