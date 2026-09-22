from __future__ import annotations

import httpx

from agent_api.config import ProviderConfig
from agent_api.tls import build_ssl_context, configure_process_tls


def build_chat_model(provider: ProviderConfig):
    from langchain_openai import ChatOpenAI

    if provider.type not in {"openai_compatible", "bifrost_gateway"}:
        raise ValueError(f"Unsupported provider type: {provider.type}")

    configure_process_tls(provider)
    ssl_context = build_ssl_context(provider)

    return ChatOpenAI(
        model=provider.model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        temperature=provider.temperature,
        timeout=provider.timeout_seconds,
        max_retries=provider.max_retries,
        http_client=httpx.Client(verify=ssl_context, timeout=provider.timeout_seconds),
        http_async_client=httpx.AsyncClient(verify=ssl_context, timeout=provider.timeout_seconds),
    )
