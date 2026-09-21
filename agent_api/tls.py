from __future__ import annotations

import os
import ssl
from pathlib import Path

from agent_api.config import ProviderConfig


def _coerce_path(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _verify_target(provider: ProviderConfig) -> tuple[str | None, str | None]:
    if isinstance(provider.tls_verify, str):
        candidate = provider.tls_verify.strip()
        if candidate:
            path = Path(candidate)
            if path.is_dir():
                return None, candidate
            return candidate, None
    return _coerce_path(provider.tls_ca_file), _coerce_path(provider.tls_ca_path)


def configure_process_tls(provider: ProviderConfig) -> None:
    ca_file, ca_path = _verify_target(provider)
    if ca_file:
        os.environ.setdefault("SSL_CERT_FILE", ca_file)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_file)
        os.environ.setdefault("CURL_CA_BUNDLE", ca_file)
    if ca_path:
        os.environ.setdefault("SSL_CERT_DIR", ca_path)


def build_ssl_context(provider: ProviderConfig) -> ssl.SSLContext:
    if provider.tls_verify is False:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        context = ssl.create_default_context()
        ca_file, ca_path = _verify_target(provider)
        if ca_file or ca_path:
            context.load_verify_locations(cafile=ca_file, capath=ca_path)

    cert_file = _coerce_path(provider.tls_client_cert_file)
    if cert_file:
        context.load_cert_chain(
            certfile=cert_file,
            keyfile=_coerce_path(provider.tls_client_key_file),
            password=_coerce_path(provider.tls_client_key_password),
        )
    return context
