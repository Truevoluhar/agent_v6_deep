from __future__ import annotations

from dataclasses import dataclass

from agent_api.config import AppConfig
from agent_api.processes import BackgroundProcessManager
from agent_api.workspace import WorkspaceManager


@dataclass(frozen=True)
class ToolContext:
    config: AppConfig
    workspace: WorkspaceManager
    process_manager: BackgroundProcessManager
    shell_env: dict[str, str]
