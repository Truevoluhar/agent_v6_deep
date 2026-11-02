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
    except Exception as exc:
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
    response_schema: dict[str, Any] | None = None,
    max_tokens: int = 8096,
    enable_thinking: bool | None = None,
) -> str:
    import json

    from agent_api.model_factory import build_chat_model


    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    is_bifrost = provider.type == "bifrost_gateway"



    if enable_thinking is None and is_bifrost:
        enable_thinking = False


    additional_body = {}

    if is_bifrost and enable_thinking is not None:
        additional_body["chat_template_kwargs"] = {
            "enable_thinking": enable_thinking
        }



    model = build_chat_model(
        provider,
        response_schema=response_schema,
        additional_body=additional_body or None,
    )

    started = time.perf_counter()

    LOGGER.info(
        "Vision operation started: "
        "operation=%s model=%s image_bytes=%s "
        "structured_output=%s max_tokens=%s "
        "thinking=%s",
        operation,
        provider.model,
        len(image_content),
        response_schema is not None,
        max_tokens,
        enable_thinking,
    )

    try:
        result = await model.ainvoke(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url(
                                    image_content,
                                    mime_type,
                                ),
                            },
                        },
                    ],
                }
            ],
            max_tokens=max_tokens,
        )

        metadata = result.response_metadata or {}
        finish_reason = metadata.get("finish_reason")

        content = message_text(result)
        usage = result.usage_metadata or {}

        tool_calls = (
            getattr(result, "tool_calls", None) or []
        )

        LOGGER.info(
            "Vision response: "
            "operation=%s finish_reason=%s "
            "content_length=%s output_tokens=%s "
            "tool_calls=%s",
            operation,
            finish_reason,
            len(content),
            usage.get("output_tokens"),
            len(tool_calls),
        )


        if finish_reason in {"length", "max_tokens"}:
            raise VisualInputError(
                f"Vision response truncated: {operation}"
            )


        if tool_calls or finish_reason in {
            "tool_calls",
            "function_call",
        }:
            raise VisualInputError(
                f"Unexpected tool call in vision: {operation}"
            )

        if finish_reason not in {None, "stop"}:
            raise VisualInputError(
                f"Unexpected vision finish_reason: "
                f"{finish_reason}"
            )

        if not content.strip():
            raise VisualInputError(
                f"Empty vision response: {operation}"
            )


        if response_schema is not None:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise VisualInputError(
                    f"Invalid structured JSON: {operation}"
                ) from exc

            if not isinstance(parsed, dict):
                raise VisualInputError(
                    f"Structured vision response must be "
                    f"a JSON object: {operation}"
                )



            content = json.dumps(
                parsed,
                ensure_ascii=False,
            )

        LOGGER.info(
            "Vision operation completed: "
            "operation=%s elapsed=%.2fs",
            operation,
            time.perf_counter() - started,
        )

        return content

    except Exception as exc:
        LOGGER.error(
            "Vision operation failed: "
            "operation=%s elapsed=%.2fs "
            "error_type=%s status_code=%s",
            operation,
            time.perf_counter() - started,
            type(exc).__name__,
            getattr(exc, "status_code", None),
            exc_info=True,
        )
        raise
