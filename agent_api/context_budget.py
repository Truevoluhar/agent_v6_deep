from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langchain.agents.middleware.types import AgentMiddleware, TracePolicy, omit_payload
from langchain_core.exceptions import ContextOverflowError
from langchain_core.messages import ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.types import Command

LOGGER = logging.getLogger(__name__)


class ContextBudgetExceeded(ContextOverflowError):
    """Raised before a model call when its effective input exceeds the budget."""


class ContextBudgetMiddleware(AgentMiddleware):
    """Final input-size check, ordered after DeepAgents summarization and memory.

    The regular DeepAgents summarization middleware compacts history before this
    middleware runs. This guard counts the resulting request, including the
    injected memory, system message, and tool schemas. It reserves part of the
    model window for model output and token-count estimation error.
    """

    # Tool-hook requests contain the complete payload; omit them from traces.
    trace_policy = TracePolicy(process_inputs=omit_payload)

    def __init__(
        self,
        max_input_tokens: int,
        backend: Any,
        max_tool_result_chars: int = 24_000,
    ) -> None:
        if max_input_tokens < 1:
            raise ValueError("max_input_tokens must be a positive integer")
        if max_tool_result_chars < 1:
            raise ValueError("max_tool_result_chars must be a positive integer")
        self.max_input_tokens = max_input_tokens
        self.backend = backend
        self.max_tool_result_chars = max_tool_result_chars

    @staticmethod
    def _tool_content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, default=str)

    def _offload_tool_message(self, message: Any, tool_name: str) -> Any:
        if not isinstance(message, ToolMessage):
            return message
        content = self._tool_content_text(message.content)
        if len(content) <= self.max_tool_result_chars:
            return message

        file_path = f"/large_tool_results/mcp_{uuid4().hex}.txt"
        try:
            self.backend.write(file_path, content)
        except Exception:
            LOGGER.exception(
                "Could not persist oversized tool result: tool=%s chars=%s",
                tool_name,
                len(content),
            )
            raise

        preview_chars = 1_500
        preview = content[:preview_chars]
        if len(content) > preview_chars * 2:
            preview += "\n...[middle omitted; full result is in the workspace file]...\n"
            preview += content[-preview_chars:]
        replacement = (
            f"Tool result ({len(content):,} characters) saved to {file_path}. "
            "Read that file with read_file and pagination to retrieve exact details.\n\n"
            f"Preview:\n{preview}"
        )
        LOGGER.info(
            "Offloaded oversized tool result: tool=%s chars=%s path=%s",
            tool_name,
            len(content),
            file_path,
        )
        return message.model_copy(update={"content": replacement})

    def _offload_response(self, response: Any, tool_name: str) -> Any:
        if isinstance(response, ToolMessage):
            return self._offload_tool_message(response, tool_name)
        if isinstance(response, Command) and isinstance(response.update, dict):
            updates = dict(response.update)
            messages = updates.get("messages")
            if isinstance(messages, list):
                updates["messages"] = [
                    self._offload_tool_message(message, tool_name)
                    for message in messages
                ]
                return Command(
                    graph=response.graph,
                    update=updates,
                    resume=response.resume,
                    goto=response.goto,
                )
        return response

    @staticmethod
    def _tool_name(request: Any) -> str:
        tool_call = getattr(request, "tool_call", None)
        if isinstance(tool_call, dict):
            return str(tool_call.get("name") or "tool")
        return "tool"

    def _request_token_count(self, request: Any) -> int:
        messages = list(request.messages)
        system_message = getattr(request, "system_message", None)
        if system_message is not None:
            messages.insert(0, system_message)
        approximate = count_tokens_approximately(
            messages,
            tools=getattr(request, "tools", None),
        )
        # The default counter assumes roughly four characters per token. Some
        # tool payloads and non-English text tokenize more densely, so leave a
        # 50% safety factor before comparing against the provider's hard limit.
        return math.ceil(approximate * 1.5)

    def _check_budget(self, request: Any) -> None:
        token_count = self._request_token_count(request)
        LOGGER.info(
            "Pre-model context check: estimated_tokens=%s budget_tokens=%s "
            "messages=%s tools=%s",
            token_count,
            self.max_input_tokens,
            len(request.messages),
            len(getattr(request, "tools", None) or []),
        )
        if token_count > self.max_input_tokens:
            LOGGER.error(
                "Model request exceeds context budget after summarization: "
                "estimated_tokens=%s budget_tokens=%s",
                token_count,
                self.max_input_tokens,
            )
            raise ContextBudgetExceeded(
                "The agent context remains too large after summarization "
                f"({token_count:,} estimated input tokens; "
                f"budget {self.max_input_tokens:,}). Large tool results are "
                "available in workspace files; retrieve only the needed sections."
            )
        LOGGER.debug(
            "Model request context checked: estimated_tokens=%s budget_tokens=%s",
            token_count,
            self.max_input_tokens,
        )

    def wrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        self._check_budget(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        self._check_budget(request)
        return await handler(request)

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        response = handler(request)
        return self._offload_response(response, self._tool_name(request))

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        response = await handler(request)
        tool_name = self._tool_name(request)
        if (
            isinstance(response, ToolMessage)
            and len(self._tool_content_text(response.content)) > self.max_tool_result_chars
        ):
            return await asyncio.to_thread(self._offload_tool_message, response, tool_name)
        if isinstance(response, Command) and isinstance(response.update, dict):
            messages = response.update.get("messages")
            if isinstance(messages, list):
                oversized = any(
                    isinstance(message, ToolMessage)
                    and len(self._tool_content_text(message.content)) > self.max_tool_result_chars
                    for message in messages
                )
                if oversized:
                    return await asyncio.to_thread(self._offload_response, response, tool_name)
        return response
