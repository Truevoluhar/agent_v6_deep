from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from agent_api.config import ProviderConfig
from agent_api.tls import build_ssl_context, configure_process_tls

LOGGER = logging.getLogger(__name__)


def _record_model_request_start(request: httpx.Request, model: str) -> None:
    request_id = uuid.uuid4().hex[:8]
    request.extensions["agent_api_model_request_id"] = request_id
    request.extensions["agent_api_model_request_started"] = time.perf_counter()
    LOGGER.info("Provider request started: model=%s request=%s", model, request_id)


def _record_model_response(response: httpx.Response, model: str) -> None:
    request = response.request
    request_id = request.extensions.get("agent_api_model_request_id", "unknown")
    started = request.extensions.get("agent_api_model_request_started")
    elapsed = time.perf_counter() - started if isinstance(started, float) else -1.0
    LOGGER.info(
        "Provider response received: model=%s request=%s status=%s elapsed=%.2fs",
        model,
        request_id,
        response.status_code,
        elapsed,
    )


def _sync_request_hook(model: str):
    def hook(request: httpx.Request) -> None:
        _record_model_request_start(request, model)

    return hook


def _sync_response_hook(model: str):
    def hook(response: httpx.Response) -> None:
        _record_model_response(response, model)

    return hook


def _async_request_hook(model: str):
    async def hook(request: httpx.Request) -> None:
        _record_model_request_start(request, model)

    return hook


def _async_response_hook(model: str):
    async def hook(response: httpx.Response) -> None:
        _record_model_response(response, model)

    return hook


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
    additional_body: dict[str, Any] | None = None,
):
    from langchain_openai import ChatOpenAI

    if provider.type not in {
        "openai_compatible",
        "bifrost_gateway",
    }:
        raise ValueError(
            f"Unsupported provider type: {provider.type}"
        )

    if response_schema is not None:
        validate_strict_response_schema(response_schema)

    configure_process_tls(provider)
    ssl_context = build_ssl_context(provider)

    extra_body: dict[str, Any] = {}

    if response_schema is not None:
        extra_body["response_format"] = (
            build_json_schema_response_format(
                response_schema
            )
        )
    elif response_format == "json":
        extra_body["response_format"] = {
            "type": "json_object"
        }

    # Izklopi thinking za Qwen3.6 prek Bifrost -> vLLM
    if provider.type == "bifrost_gateway":
        if extra_body is None:
            extra_body = {}

        extra_body["chat_template_kwargs"] = {
            "enable_thinking": False
        }


    if additional_body:
        for key, value in additional_body.items():
            if key == "response_format" and (
                response_schema is not None
                or response_format == "json"
            ):
                raise ValueError(
                    "response_format must not be overridden "
                    "through additional_body."
                )
            extra_body[key] = value

    chat_model_kwargs = {
        "model": provider.model,
        "api_key": provider.api_key,
        "base_url": provider.base_url,
        "temperature": provider.temperature,
        "timeout": provider.timeout_seconds,
        "max_retries": provider.max_retries,
        "http_client": httpx.Client(
            verify=ssl_context,
            timeout=provider.timeout_seconds,
            event_hooks={
                "request": [
                    _sync_request_hook(provider.model)
                ],
                "response": [
                    _sync_response_hook(provider.model)
                ],
            },
        ),
        "http_async_client": httpx.AsyncClient(
            verify=ssl_context,
            timeout=provider.timeout_seconds,
            event_hooks={
                "request": [
                    _async_request_hook(provider.model)
                ],
                "response": [
                    _async_response_hook(provider.model)
                ],
            },
        ),
    }

    if extra_body:
        chat_model_kwargs["extra_body"] = extra_body

    return ChatOpenAI(**chat_model_kwargs)
