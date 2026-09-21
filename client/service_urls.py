from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable

import requests

DEFAULT_AGENT_API_URLS = (
    "http://agent-api:8080",
    "http://host.docker.internal:8080",
    "http://localhost:8080",
)
DEFAULT_WORKSPACE_API_URLS = (
    "http://workspace-api:8090",
    "http://host.docker.internal:8090",
    "http://localhost:8090",
)


def _split_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def _candidate_urls(
    configured_url: str | None,
    fallback_urls: str | None,
    default_urls: Iterable[str],
) -> list[str]:
    ordered: list[str] = []
    for item in [configured_url, *_split_urls(fallback_urls), *default_urls]:
        if not item:
            continue
        normalized = item.rstrip("/")
        if normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _probe_json(url: str, path: str, *, params: dict[str, str] | None = None, timeout: int = 5) -> bool:
    response = requests.get(f"{url}{path}", params=params, timeout=timeout)
    response.raise_for_status()
    response.json()
    return True


def _resolve_service_url(
    configured_url: str | None,
    fallback_urls: str | None,
    default_urls: Iterable[str],
    *,
    path: str,
    params: dict[str, str] | None = None,
) -> str:
    failures: list[str] = []
    for candidate in _candidate_urls(configured_url, fallback_urls, default_urls):
        try:
            _probe_json(candidate, path, params=params)
            return candidate
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{candidate}: {exc}")
    summary = "; ".join(failures) or "no candidate URLs configured"
    raise RuntimeError(f"Unable to reach service for {path}. Tried: {summary}")


@lru_cache(maxsize=1)
def resolve_agent_api_url() -> str:
    return _resolve_service_url(
        configured_url=os.environ.get("AGENT_API_URL"),
        fallback_urls=os.environ.get("AGENT_API_FALLBACK_URLS"),
        default_urls=DEFAULT_AGENT_API_URLS,
        path="/v1/threads",
    )


@lru_cache(maxsize=1)
def resolve_workspace_api_url() -> str:
    return _resolve_service_url(
        configured_url=os.environ.get("WORKSPACE_API_URL"),
        fallback_urls=os.environ.get("WORKSPACE_API_FALLBACK_URLS"),
        default_urls=DEFAULT_WORKSPACE_API_URLS,
        path="/v1/files",
        params={"path": "/"},
    )
