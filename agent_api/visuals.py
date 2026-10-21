from __future__ import annotations

import base64
import io
import logging
import os
import time
from typing import Any

from PIL import Image, ImageOps

from agent_api.workspace import WorkspaceManager

LOGGER = logging.getLogger(__name__)

MAX_VISUAL_FILE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000
MAX_IMAGE_EDGE = 2400


class VisualInputError(ValueError):
    """Raised when a workspace file is not a safe supported visual input."""


def read_workspace_file(workspace: WorkspaceManager, path: str, *, max_bytes: int = MAX_VISUAL_FILE_BYTES) -> bytes:
    target = workspace.resolve_path(path)
    if not target.is_file():
        raise VisualInputError("Path must point to a workspace file.")
    fd = workspace.open_file(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as handle:
        if os.fstat(handle.fileno()).st_size > max_bytes:
            raise VisualInputError(f"File exceeds the {max_bytes // (1024 * 1024)} MiB processing limit.")
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise VisualInputError(f"File exceeds the {max_bytes // (1024 * 1024)} MiB processing limit.")
    return content


def normalize_image(content: bytes) -> tuple[bytes, str, int, int]:
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise VisualInputError("Image dimensions exceed the processing limit.")
            source.seek(0)
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    except VisualInputError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VisualInputError("File is not a supported raster image.") from exc

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue(), "image/png", image.width, image.height


def image_data_url(content: bytes, mime_type: str = "image/png") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"


def message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part).strip()
    return str(content)


async def ask_vision(
    provider: Any,
    image_content: bytes,
    prompt: str,
    *,
    mime_type: str = "image/png",
    operation: str = "visual_inspection",
) -> str:
    from agent_api.model_factory import build_chat_model

    model = build_chat_model(provider)
    started = time.perf_counter()
    LOGGER.info(
        "Vision operation started: operation=%s model=%s image_bytes=%s",
        operation,
        provider.model,
        len(image_content),
    )
    try:
        result = await model.ainvoke(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url(image_content, mime_type)}},
                    ],
                }
            ]
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.error(
            "Vision operation failed: operation=%s elapsed=%.2fs error_type=%s",
            operation,
            time.perf_counter() - started,
            type(exc).__name__,
        )
        raise
    LOGGER.info(
        "Vision operation completed: operation=%s elapsed=%.2fs",
        operation,
        time.perf_counter() - started,
    )
    return message_text(result)

