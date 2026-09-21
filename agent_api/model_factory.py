from __future__ import annotations

from agent_api.config import ProviderConfig


def build_chat_model(provider: ProviderConfig):
    from langchain_openai import ChatOpenAI

    if provider.type != "openai_compatible":
        raise ValueError(f"Unsupported provider type: {provider.type}")

    return ChatOpenAI(
        model=provider.model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        temperature=provider.temperature,
        timeout=provider.timeout_seconds,
        max_retries=provider.max_retries,
    )
