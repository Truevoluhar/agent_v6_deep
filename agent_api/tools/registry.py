from __future__ import annotations

import importlib
import json
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_api.tools.context import ToolContext

ToolkitBuilder = Callable[[ToolContext], list[Any]]

_TOOLKITS: dict[str, tuple[str, ToolkitBuilder]] = {}
_DISCOVERED = False


@dataclass(frozen=True)
class ToolCollection:
    tools: list[Any]
    toolkits: list[dict[str, Any]]

    def summary(self) -> str:
        return json.dumps(self.toolkits, indent=2)


def register_toolkit(name: str, description: str) -> Callable[[ToolkitBuilder], ToolkitBuilder]:
    def decorator(builder: ToolkitBuilder) -> ToolkitBuilder:
        _TOOLKITS[name] = (description, builder)
        return builder

    return decorator


def discover_toolkits() -> None:
    global _DISCOVERED
    if _DISCOVERED:
        return
    package = importlib.import_module("agent_api.tools")
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name in {"context", "registry"} or module_info.name.startswith("_"):
            continue
        importlib.import_module(f"agent_api.tools.{module_info.name}")
    _DISCOVERED = True


def build_tool_collection(context: ToolContext, enabled_toolkits: list[str] | None = None) -> ToolCollection:
    discover_toolkits()
    enabled = set(enabled_toolkits or _TOOLKITS.keys())
    tools: list[Any] = []
    toolkits: list[dict[str, Any]] = []
    for name in sorted(enabled):
        if name not in _TOOLKITS:
            raise ValueError(f"Unknown toolkit: {name}")
        description, builder = _TOOLKITS[name]
        toolkit_tools = builder(context)
        tools.extend(toolkit_tools)
        toolkits.append(
            {
                "name": name,
                "description": description,
                "tools": [getattr(tool, "name", repr(tool)) for tool in toolkit_tools],
            }
        )
    return ToolCollection(tools=tools, toolkits=toolkits)
