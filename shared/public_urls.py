from __future__ import annotations

import re
from urllib.parse import urlsplit


def codespaces_peer_url(url: str, source_port: int, target_port: int) -> str | None:
    """Return the HTTPS origin for another forwarded port in this codespace."""
    hostname = urlsplit(url).hostname or ""
    suffix = f"-{source_port}.app.github.dev"
    if not hostname.endswith(suffix):
        return None
    codespace = hostname[: -len(suffix)]
    if not re.fullmatch(r"[a-z0-9-]+", codespace):
        return None
    return f"https://{codespace}-{target_port}.app.github.dev"
