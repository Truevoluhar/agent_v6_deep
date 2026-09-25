from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_api.config import AppConfig
from agent_api.processes import BackgroundProcessManager
from agent_api.tools.context import ToolContext
from agent_api.tools.registry import ToolCollection, build_tool_collection
from agent_api.workspace import WorkspaceManager


@dataclass
class AgentRuntime:
    config: AppConfig
    workspace: WorkspaceManager
    process_manager: BackgroundProcessManager
    shell_env: dict[str, str]
    tool_collection: ToolCollection

    @classmethod
    def create(cls, config: AppConfig) -> "AgentRuntime":
        workspace = WorkspaceManager(config.agent.workspace_root)
        workspace.ensure_layout()
        for root in (
            config.agent.data_root,
            config.agent.session_root,
            config.agent.memory_root,
            config.agent.resources_root,
            config.agent.runs_root,
        ):
            root.mkdir(parents=True, exist_ok=True)
        _seed_memory(workspace)
        _seed_skills(workspace, config.agent.skills_root)
        shell_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(config.agent.workspace_root / ".agent" / "home"),
        }
        process_manager = BackgroundProcessManager(
            workspace=workspace,
            env=shell_env,
            processes_root=config.agent.runs_root / "processes",
        )
        tool_collection = build_tool_collection(
            ToolContext(
                config=config,
                workspace=workspace,
                process_manager=process_manager,
                shell_env=shell_env,
            ),
            enabled_toolkits=config.agent.enabled_toolkits,
        )
        return cls(
            config=config,
            workspace=workspace,
            process_manager=process_manager,
            shell_env=shell_env,
            tool_collection=tool_collection,
        )

    def invoke(self, thread_id: str, message: str) -> Any:
        from deepagents import create_deep_agent
        from deepagents.backends import LocalShellBackend

        from agent_api.model_factory import build_chat_model

        agent_kwargs = {
            "model": build_chat_model(self.config.provider),
            "tools": self.tool_collection.tools,
            "system_prompt": self.build_system_prompt(),
            "backend": LocalShellBackend(
                root_dir=self.config.agent.workspace_root,
                virtual_mode=True,
                inherit_env=False,
                timeout=self.config.agent.shell_timeout_seconds,
                env=self.shell_env,
            ),
            "memory": self.config.agent.memory_files,
            "skills": [self.config.agent.skills_root],
        }

        if self.config.agent.use_checkpointer and self.config.agent.database_url:
            from langgraph.checkpoint.postgres import PostgresSaver

            with PostgresSaver.from_conn_string(self.config.agent.database_url) as checkpointer:
                checkpointer.setup()
                agent = create_deep_agent(
                    **agent_kwargs,
                    checkpointer=checkpointer,
                )
                return agent.invoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config={
                        "configurable": {"thread_id": thread_id},
                        "recursion_limit": self.config.agent.recursion_limit,
                    },
                )

        agent = create_deep_agent(
            **agent_kwargs,
        )
        return agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": self.config.agent.recursion_limit,
            },
        )

    def build_system_prompt(self) -> str:
        toolkit_lines = []
        for toolkit in self.tool_collection.toolkits:
            toolkit_lines.append(
                f"- {toolkit['name']}: {toolkit['description']} Tools: {', '.join(toolkit['tools'])}."
            )
        toolkit_text = "\n".join(toolkit_lines)
        return (
            f"{self.config.agent.system_prompt}\n\n"
            "Custom toolkits available in addition to the DeepAgents built-ins:\n"
            f"{toolkit_text}\n\n"
            "Use `run_shell` when you need structured stdout/stderr/return-code output. "
            "Use the background process tools for long-running commands and log inspection."
        )


def _seed_memory(workspace: WorkspaceManager) -> None:
    seed = Path("/seed/.agent/AGENTS.md")
    target = workspace.resolve_path("/.agent/AGENTS.md")
    if seed.exists() and not target.exists():
        target.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")


def _seed_skills(
    workspace: WorkspaceManager,
    skills_root: str,
    source_root: Path | None = None,
) -> None:
    source_root = source_root or Path("/app/skills")
    if not source_root.exists():
        return

    target_root = workspace.resolve_path(skills_root)
    target_root.mkdir(parents=True, exist_ok=True)

    for skill_dir in source_root.iterdir():
        if not skill_dir.is_dir():
            continue
        target_dir = target_root / skill_dir.name
        shutil.copytree(skill_dir, target_dir, dirs_exist_ok=True)
