from __future__ import annotations

from typing import Any

import requests

from client import service_urls


class DummyResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self) -> Any:
        return self._payload


def test_resolve_agent_api_url_uses_fallback_when_primary_fails(monkeypatch) -> None:
    service_urls.resolve_agent_api_url.cache_clear()

    def fake_get(url: str, params: dict[str, str] | None = None, timeout: int = 5) -> DummyResponse:
        if url.startswith("http://agent-api:8081"):
            raise requests.ConnectionError("unreachable")
        if url.startswith("http://host.docker.internal:8081") and url.endswith("/health"):
            return DummyResponse({"status": "ok"})
        raise AssertionError(f"unexpected url {url} params={params}")

    monkeypatch.setattr(service_urls.requests, "get", fake_get)
    monkeypatch.setenv("AGENT_API_URL", "http://agent-api:8081")
    monkeypatch.setenv("AGENT_API_FALLBACK_URLS", "http://host.docker.internal:8081")

    assert service_urls.resolve_agent_api_url() == "http://host.docker.internal:8081"


def test_resolve_workspace_api_url_prefers_primary(monkeypatch) -> None:
    service_urls.resolve_workspace_api_url.cache_clear()

    def fake_get(url: str, params: dict[str, str] | None = None, timeout: int = 5) -> DummyResponse:
        assert params is None
        if url.startswith("http://workspace-api:8090") and url.endswith("/health"):
            return DummyResponse({"status": "ok"})
        raise AssertionError(f"unexpected url {url} params={params}")

    monkeypatch.setattr(service_urls.requests, "get", fake_get)
    monkeypatch.setenv("WORKSPACE_API_URL", "http://workspace-api:8090")
    monkeypatch.setenv("WORKSPACE_API_FALLBACK_URLS", "http://host.docker.internal:8090")

    assert service_urls.resolve_workspace_api_url() == "http://workspace-api:8090"


def test_resolve_agent_api_url_skips_non_json_success(monkeypatch) -> None:
    service_urls.resolve_agent_api_url.cache_clear()

    def fake_get(url: str, params: dict[str, str] | None = None, timeout: int = 5) -> DummyResponse:
        if url.startswith("http://agent-api:8081") and url.endswith("/health"):
            return DummyResponse("<html>not json</html>")
        if url.startswith("http://host.docker.internal:8081") and url.endswith("/health"):
            return DummyResponse({"status": "ok"})
        raise AssertionError(f"unexpected url {url} params={params}")

    monkeypatch.setattr(service_urls.requests, "get", fake_get)
    monkeypatch.setenv("AGENT_API_URL", "http://agent-api:8081")
    monkeypatch.setenv("AGENT_API_FALLBACK_URLS", "http://host.docker.internal:8081")

    assert service_urls.resolve_agent_api_url() == "http://host.docker.internal:8081"
