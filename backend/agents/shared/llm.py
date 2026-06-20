import os
import logging
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


def mask_secret(value: str | None) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


_logged_config = False


def create_chat_llm(timeout: int = 90, **kwargs: Any):
    """Create a LangChain ChatOpenAI client for OpenAI-compatible providers."""
    if ChatOpenAI is None:
        return None

    config = get_llm_config()
    global _logged_config
    if not _logged_config:
        logging.info(
            "LLM config loaded: base_url=%s model=%s api_key=%s",
            config["base_url"],
            config["model"],
            mask_secret(config["api_key"]),
        )
        _logged_config = True
    if not config["api_key"]:
        return None

    return ChatOpenAI(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        timeout=timeout,
        **kwargs,
    )
