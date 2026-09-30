from __future__ import annotations

from typing import Any

import httpx

from agent_api.config import ProviderConfig
from agent_api.tls import build_ssl_context, configure_process_tls


def validate_strict_response_schema(schema: dict[str, Any]) -> None:
    if schema.get("type") != "object":
        raise ValueError("The root JSON Schema type must be 'object'.")

    def validate_node(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                properties = node.get("properties", {})
                required = node.get("required", [])
                if not isinstance(properties, dict):
                    raise ValueError(f"{path}.properties must be an object.")
                if (
                    not isinstance(required, list)
                    or not all(isinstance(key, str) for key in required)
                    or len(required) != len(properties)
                    or set(required) != set(properties)
                ):
                    raise ValueError(f"{path}.required must list every property exactly once.")
                if node.get("additionalProperties") is not False:
                    raise ValueError(f"{path}.additionalProperties must be false.")
            for key, value in node.items():
                validate_node(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                validate_node(value, f"{path}[{index}]")

    validate_node(schema, "$")


def build_json_schema_response_format(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": schema,
        },
    }


def build_chat_model(
    provider: ProviderConfig,
    response_format: str | None = None,
    response_schema: dict[str, Any] | None = None,
):
    from langchain_openai import ChatOpenAI

    if provider.type not in {"openai_compatible", "bifrost_gateway"}:
        raise ValueError(f"Unsupported provider type: {provider.type}")

    configure_process_tls(provider)
    ssl_context = build_ssl_context(provider)

    extra_body: dict[str, Any] | None = None
    if response_schema is not None:
        extra_body = {"response_format": build_json_schema_response_format(response_schema)}
    elif response_format == "json":
        extra_body = {"response_format": {"type": "json_object"}}

    chat_model_kwargs = {
        "model": provider.model,
        "api_key": provider.api_key,
        "base_url": provider.base_url,
        "temperature": provider.temperature,
        "timeout": provider.timeout_seconds,
        "max_retries": provider.max_retries,
        "http_client": httpx.Client(verify=ssl_context, timeout=provider.timeout_seconds),
        "http_async_client": httpx.AsyncClient(verify=ssl_context, timeout=provider.timeout_seconds),
    }
    if extra_body is not None:
        chat_model_kwargs["extra_body"] = extra_body
    return ChatOpenAI(**chat_model_kwargs)
