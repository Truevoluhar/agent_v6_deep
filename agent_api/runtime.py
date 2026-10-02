from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_api.config import AppConfig
from agent_api.processes import BackgroundProcessManager
from agent_api.tools.context import ToolContext
from agent_api.tools.registry import ToolCollection, build_tool_collection
from agent_api.workspace import WorkspaceManager


def _last_message_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                content = getattr(message, "content", None)
                if isinstance(content, str) and content.strip():
                    return content
                if isinstance(message, dict):
                    raw_content = message.get("content")
                    if isinstance(raw_content, str) and raw_content.strip():
                        return raw_content
    content = getattr(result, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    return str(result)


@dataclass
class AgentRuntime:
    config: AppConfig
    workspace: WorkspaceManager
    process_manager: BackgroundProcessManager
    shell_env: dict[str, str]
    tool_collection: ToolCollection
    mcp_client: Any = None
    mcp_tools: list[Any] = field(default_factory=list)
    mcp_status: str = "disabled"
    mcp_error: str | None = None

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

    async def initialize_mcp(self) -> None:
        if not self.config.agent.bifrost_mcp_enabled:
            return

        url = self.config.agent.bifrost_mcp_url
        if not url:
            raise ValueError("BIFROST_MCP_ENABLED=true but BIFROST_MCP_URL is empty.")

        from langchain_mcp_adapters.client import MultiServerMCPClient

        connection: dict[str, Any] = {
            "url": url,
            "transport": "streamable_http",
        }
        api_key = self.config.agent.bifrost_mcp_api_key
        if api_key:
            connection["headers"] = {"Authorization": f"Bearer {api_key}"}

        self.mcp_client = MultiServerMCPClient(
            {"bifrost": connection},
            tool_name_prefix=True,
            handle_tool_errors=True,
        )
        self.mcp_tools = await self.mcp_client.get_tools()

    def all_tools(self) -> list[Any]:
        return [*self.tool_collection.tools, *self.mcp_tools]

    async def invoke(
        self,
        thread_id: str,
        message: str,
        response_format: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> Any:
        from deepagents import create_deep_agent
        from deepagents.backends import LocalShellBackend

        from agent_api.model_factory import build_chat_model

        # The agent's own model must stay unconstrained: DeepAgents relies on multi-turn
        # tool calls (skills, file writes, sub-agents) to do real work, and forcing a
        # strict JSON-schema response on every turn makes the model skip tool use and
        # emit a schema-shaped guess immediately. Structured output is applied afterwards,
        # in a separate formatting pass over the agent's finished answer.
        agent_kwargs = {
            "model": build_chat_model(self.config.provider),
            "tools": self.all_tools(),
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
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            async with AsyncPostgresSaver.from_conn_string(
                self.config.agent.database_url
            ) as checkpointer:
                await checkpointer.setup()
                agent = create_deep_agent(
                    **agent_kwargs,
                    checkpointer=checkpointer,
                )
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config={
                        "configurable": {"thread_id": thread_id},
                        "recursion_limit": self.config.agent.recursion_limit,
                    },
                )
        else:
            agent = create_deep_agent(
                **agent_kwargs,
            )
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": message}]},
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": self.config.agent.recursion_limit,
                },
            )

        if response_format is None and response_schema is None:
            return result

        return await self._format_structured_reply(
            raw_reply=_last_message_text(result),
            response_format=response_format,
            response_schema=response_schema,
        )

    async def _format_structured_reply(
        self,
        raw_reply: str,
        response_format: str | None,
        response_schema: dict[str, Any] | None,
    ) -> Any:
        from agent_api.model_factory import build_chat_model

        structuring_model = build_chat_model(
            self.config.provider,
            response_format=response_format,
            response_schema=response_schema,
        )
        prompt = (
            "Restate the following agent answer to satisfy the required response format. "
            "Do not invent new information; only reformat what is already present below.\n\n"
            f"Agent answer:\n{raw_reply}"
        )
        return await structuring_model.ainvoke([{"role": "user", "content": prompt}])

    def build_system_prompt(self, response_format: str | None = None) -> str:
        toolkit_lines = []
        for toolkit in self.tool_collection.toolkits:
            toolkit_lines.append(
                f"- {toolkit['name']}: {toolkit['description']} Tools: {', '.join(toolkit['tools'])}."
            )
        toolkit_text = "\n".join(toolkit_lines)
        prompt = (
            f"{self.config.agent.system_prompt}\n\n"
            "Custom toolkits available in addition to the DeepAgents built-ins:\n"
            f"{toolkit_text}\n\n"
            "Use `run_shell` when you need structured stdout/stderr/return-code output. "
            "Use the background process tools for long-running commands and log inspection."
        )
        if response_format == "json":
            prompt += (
                "\n\nFinal response format: JSON. Return exactly one valid JSON value as the final "
                "response. Do not wrap it in Markdown fences or include commentary outside the JSON."
            )
        return prompt


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
