import os
from typing import Any

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - exercised only when optional dependency is absent
    ChatOpenAI = None


def _env(name: str, fallback: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    if fallback:
        return os.environ.get(fallback)
    return None


def get_llm_config() -> dict[str, str | None]:
    """Read OpenAI-compatible chat model settings from the environment."""
    return {
        "api_key": _env("LLM_API_KEY", "DEEPSEEK_API_KEY"),
        "base_url": _env("LLM_BASE_URL", "DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com",
        "model": _env("LLM_MODEL", "DEEPSEEK_MODEL") or "deepseek-chat",
    }


def create_chat_llm(timeout: int = 90, **kwargs: Any):
    """Create a LangChain ChatOpenAI client for OpenAI-compatible providers."""
    if ChatOpenAI is None:
        return None

    config = get_llm_config()
    if not config["api_key"]:
        return None

    return ChatOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        timeout=timeout,
        **kwargs,
    )
