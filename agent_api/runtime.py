from __future__ import annotations

import shutil
import logging
import time
from dataclasses import dataclass, field, replace
from uuid import UUID
from shared.user_paths import UserPaths
from pathlib import Path
from typing import Any

from agent_api.config import AppConfig
from agent_api.processes import BackgroundProcessManager
from agent_api.tools.context import ToolContext
from agent_api.tools.registry import ToolCollection, build_tool_collection
from agent_api.workspace import WorkspaceManager

LOGGER = logging.getLogger(__name__)


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
    user_id: UUID | None = None
    mcp_client: Any = None
    mcp_tools: list[Any] = field(default_factory=list)
    mcp_status: str = "disabled"
    mcp_error: str | None = None

    @classmethod
    def create(cls, config: AppConfig, user_id: UUID | None = None) -> "AgentRuntime":
        if user_id is not None:
            paths = UserPaths.for_user(user_id)
            agent = replace(config.agent, data_root=paths.root, workspace_root=paths.workspace, session_root=paths.sessions, memory_root=paths.memory, resources_root=paths.resources, runs_root=paths.runs, bifrost_mcp_enabled=False, memory_files=["/.agent/AGENTS.md", "/.agent/MEMORY.md"], skills_root="/.agent/skills")
            config = replace(config, agent=agent)
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
        if user_id is not None:
            memory_file = workspace.resolve_path("/.agent/MEMORY.md")
            durable_memory = config.agent.memory_root / "MEMORY.md"
            if not memory_file.exists():
                if durable_memory.exists():
                    shutil.copyfile(durable_memory, memory_file)
                else:
                    memory_file.write_text("# User memory\n", encoding="utf-8")
            if not durable_memory.exists():
                shutil.copyfile(memory_file, durable_memory)
        _seed_skills(workspace, config.agent.skills_root)
        shell_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }
        process_manager = BackgroundProcessManager(
            workspace=workspace,
            env=shell_env,
            processes_root=config.agent.runs_root / "processes",
            owner_user_id=user_id,
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
            user_id=user_id,
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
        if not self.config.agent.bifrost_mcp_tls_verify:
            import httpx

            def make_mcp_http_client(
                headers: dict[str, str] | None = None,
                timeout: Any = None,
                auth: Any = None,
            ) -> Any:
                return httpx.AsyncClient(
                    verify=False,
                    headers=headers,
                    timeout=timeout,
                    auth=auth,
                )

            connection["httpx_client_factory"] = make_mcp_http_client

        self.mcp_client = MultiServerMCPClient(
            {"bifrost": connection},
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
        attachments: list[str] | None = None,
    ) -> Any:
        from deepagents import create_deep_agent
        from deepagents.middleware.filesystem import FilesystemMiddleware
        from deepagents.middleware.memory import MemoryMiddleware
        from deepagents.middleware.summarization import SummarizationMiddleware
        from agent_api.context_budget import ContextBudgetMiddleware
        from agent_api.quota_backend import QuotaFilesystemBackend

        from agent_api.model_factory import build_chat_model






        attached_paths = attachments or []
        agent_message = message
        if attached_paths:
            attachment_lines = "\n".join(f"- {path}" for path in attached_paths)
            agent_message += (
                "\n\nFiles attached to this message are already in the workspace. "
                "Inspect visual files with the vision tools when relevant:\n"
                f"{attachment_lines}"
            )
        model = build_chat_model(self.config.provider)

        backend = QuotaFilesystemBackend(
            root_dir=self.config.agent.workspace_root,
            virtual_mode=True,
        )
        context_window_tokens = getattr(
            self.config.agent,
            "context_window_tokens",
            128_000,
        )
        # Leave room for generated output, estimation error, and provider overhead.
        input_budget_tokens = max(1, context_window_tokens * 7 // 10)
        # Summarization's native estimator is approximate. Trigger early enough
        # that the stricter final estimate can still keep the call within budget.
        summarization_trigger_tokens = max(1, context_window_tokens * 4 // 10)
        summarization_keep_tokens = max(1, min(20_000, input_budget_tokens // 5))
        summary_source_tokens = max(1_000, min(20_000, summarization_trigger_tokens // 2))
        agent_kwargs = {
            "model": model,
            "tools": self.all_tools(),
            "system_prompt": self.build_system_prompt(),
            "backend": backend,
            "skills": [self.config.agent.skills_root],
            "middleware": [
                # Replace the default filesystem middleware with the same
                # workspace backend and an explicit cap for every tool result.
                FilesystemMiddleware(
                    backend=backend,
                    tool_token_limit_before_evict=6_000,
                ),
                SummarizationMiddleware(
                    model=model,
                    backend=backend,
                    trigger=("tokens", summarization_trigger_tokens),
                    keep=("tokens", summarization_keep_tokens),
                    trim_tokens_to_summarize=summary_source_tokens,
                ),
                # Keep memory injection before the final check. create_deep_agent
                # otherwise adds MemoryMiddleware in its tail, after user hooks.
                MemoryMiddleware(
                    backend=backend,
                    sources=self.config.agent.memory_files,
                ),
                ContextBudgetMiddleware(
                    max_input_tokens=input_budget_tokens,
                    backend=backend,
                    max_tool_result_chars=24_000,
                ),
            ],
        }

        if self.config.agent.use_checkpointer and self.config.agent.database_url:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            LOGGER.info("Agent checkpointer setup started: thread=%s", thread_id)
            async with AsyncPostgresSaver.from_conn_string(
                self.config.agent.database_url
            ) as checkpointer:
                await checkpointer.setup()
                LOGGER.info("Agent checkpointer setup completed: thread=%s", thread_id)
                agent = create_deep_agent(
                    **agent_kwargs,
                    checkpointer=checkpointer,
                )
                invocation_started = time.perf_counter()
                LOGGER.info("DeepAgent graph invocation started: thread=%s", thread_id)
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": agent_message}]},
                    config={
                        "configurable": {"thread_id": f"{self.user_id}:{thread_id}" if self.user_id else thread_id},
                        "recursion_limit": self.config.agent.recursion_limit,
                    },
                )
                LOGGER.info(
                    "DeepAgent graph invocation completed: thread=%s elapsed=%.2fs",
                    thread_id,
                    time.perf_counter() - invocation_started,
                )
        else:
            agent = create_deep_agent(
                **agent_kwargs,
            )
            invocation_started = time.perf_counter()
            LOGGER.info("DeepAgent graph invocation started: thread=%s", thread_id)
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": agent_message}]},
                config={
                    "configurable": {"thread_id": f"{self.user_id}:{thread_id}" if self.user_id else thread_id},
                    "recursion_limit": self.config.agent.recursion_limit,
                },
            )
            LOGGER.info(
                "DeepAgent graph invocation completed: thread=%s elapsed=%.2fs",
                thread_id,
                time.perf_counter() - invocation_started,
            )

        if self.user_id is not None:
            memory_file = self.workspace.resolve_path("/.agent/MEMORY.md")
            if memory_file.exists():
                shutil.copyfile(memory_file, self.config.agent.memory_root / "MEMORY.md")

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
        from agent_api.model_factory import build_chat_model, max_output_tokens

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
        invoke_kwargs = {
            "max_tokens": max_output_tokens(self.config.provider, 2048),
        }
        return await structuring_model.ainvoke([{"role": "user", "content": prompt}], **invoke_kwargs)

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
            "Shell commands run only inside /shell_executions. Put scripts, package environments, temporary files, "
            "and server files there; shell commands cannot read or change workspace data outside that directory. "
            "Use a local virtual environment or local package install instead of system-wide package changes. "
            "Start long-running servers with start_background_process. Use filesystem tools for other workspace files. "
            "Large tool results may be saved to a workspace file; use the returned path and read_file "
            "to retrieve exact details before relying on them, especially schemas and column definitions."
            " Use inspect_image or inspect_pdf to read visual files. For requests to anonymize or redact scanned documents, "
            "use redact_pdf_personal_data and report its verification status accurately. Do not repeat detected personal values "
            "in the final reply; report only the artifact path, counts, and verification result. If the tool returns an output_path "
            "with artifact_created=true and status=review_required, provide that PDF and say it still needs human inspection; "
            "do not say that no PDF was created."
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
        _copy_skill_contents(skill_dir, target_dir)


def _copy_skill_contents(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.iterdir():
        target_path = target_dir / source_path.name
        if source_path.is_dir():
            _copy_skill_contents(source_path, target_path)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
