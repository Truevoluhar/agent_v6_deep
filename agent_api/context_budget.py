from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages.utils import count_tokens_approximately

LOGGER = logging.getLogger(__name__)


class ContextBudgetExceeded(RuntimeError):
    """Raised before a model call when its effective input exceeds the budget."""


class ContextBudgetMiddleware(AgentMiddleware):
    """Final input-size check, ordered after DeepAgents summarization.

    The regular DeepAgents summarization middleware compacts history before this
    middleware runs. This guard counts the resulting request, including the
    system message and tool schemas, and reserves part of the model window for
    later prompt additions, model output, and token-count estimation error.
    """

    def __init__(self, max_input_tokens: int) -> None:
        if max_input_tokens < 1:
            raise ValueError("max_input_tokens must be a positive integer")
        self.max_input_tokens = max_input_tokens

    def _request_token_count(self, request: Any) -> int:
        messages = list(request.messages)
        system_message = getattr(request, "system_message", None)
        if system_message is not None:
            messages.insert(0, system_message)
        return count_tokens_approximately(messages, tools=getattr(request, "tools", None))

    def _check_budget(self, request: Any) -> None:
        token_count = self._request_token_count(request)
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
