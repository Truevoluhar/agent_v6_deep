from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    type: str
    model: str
    base_url: str
    api_key: str
    temperature: float
    timeout_seconds: int
    max_retries: int


@dataclass(frozen=True)
class AgentConfig:
    data_root: Path
    workspace_root: Path
    session_root: Path
    memory_root: Path
    resources_root: Path
    runs_root: Path
    skills_root: str
    system_prompt: str
    memory_files: list[str]
    enabled_toolkits: list[str]
    use_checkpointer: bool
    recursion_limit: int
    shell_timeout_seconds: int
    database_url: str | None


@dataclass(frozen=True)
class AppConfig:
    active_provider: str
    provider: ProviderConfig
    agent: AgentConfig


def expand_env_placeholders(text: str, env: dict[str, str] | None = None) -> str:
    values = env or os.environ

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        if name in values and values[name] != "":
            return values[name]
        if default is not None:
            return default
        raise ValueError(f"Missing required environment variable: {name}")

    return ENV_PATTERN.sub(replace, text)


def load_provider_file(config_path: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    rendered = expand_env_placeholders(config_path.read_text(encoding="utf-8"), env=env)
    data = yaml.safe_load(rendered)
    if not isinstance(data, dict):
        raise ValueError("Provider configuration must be a mapping.")
    return data


def load_config(
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> AppConfig:
    env_values = env or os.environ
    resolved_path = Path(config_path or env_values.get("PROVIDERS_CONFIG_PATH", "/app/config/providers.yaml"))
    data = load_provider_file(resolved_path, env=env_values)

    active_provider = str(data["active_provider"])
    providers = data.get("providers", {})
    if active_provider not in providers:
        raise ValueError(f"Active provider '{active_provider}' not defined in providers.yaml.")

    raw_provider = providers[active_provider]
    provider = ProviderConfig(
        name=active_provider,
        type=str(raw_provider["type"]),
        model=str(raw_provider["model"]),
        base_url=str(raw_provider["base_url"]),
        api_key=str(raw_provider["api_key"]),
        temperature=float(raw_provider.get("temperature", 0)),
        timeout_seconds=int(raw_provider.get("timeout_seconds", 180)),
        max_retries=int(raw_provider.get("max_retries", 2)),
    )

    data_root = Path(env_values.get("AGENT_DATA_ROOT", "/data"))
    workspace_root = Path(env_values.get("WORKSPACE_ROOT", str(data_root / "agent_workspace")))
    session_root = Path(env_values.get("SESSION_ROOT", str(data_root / "session")))
    memory_root = Path(env_values.get("MEMORY_ROOT", str(data_root / "memory")))
    resources_root = Path(env_values.get("RESOURCES_ROOT", str(data_root / "resources")))
    runs_root = Path(env_values.get("RUNS_ROOT", str(data_root / "runs")))
    skills_root = env_values.get("SKILLS_ROOT", "/app/skills")
    enabled_toolkits = [
        item.strip()
        for item in env_values.get("AGENT_ENABLED_TOOLKITS", "filesystem,shell").split(",")
        if item.strip()
    ]
    use_checkpointer = env_values.get("AGENT_USE_CHECKPOINTER", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "",
    }
    database_url = env_values.get(
        "DATABASE_URL",
        "postgresql://deepagents:deepagents@postgres:5432/deepagents",
    ).strip() or None
    agent = AgentConfig(
        data_root=data_root,
        workspace_root=workspace_root,
        session_root=session_root,
        memory_root=memory_root,
        resources_root=resources_root,
        runs_root=runs_root,
        skills_root=skills_root,
        system_prompt=env_values.get(
            "AGENT_SYSTEM_PROMPT",
            (
                "You are a reliable engineering agent. Prefer careful inspection, "
                "create durable artifacts in the workspace, explain assumptions "
                "clearly, and use the available skills when they fit the task."
            ),
        ),
        memory_files=["/.agent/AGENTS.md"],
        enabled_toolkits=enabled_toolkits,
        use_checkpointer=use_checkpointer,
        recursion_limit=int(env_values.get("AGENT_RECURSION_LIMIT", "120")),
        shell_timeout_seconds=int(env_values.get("AGENT_SHELL_TIMEOUT_SECONDS", "120")),
        database_url=database_url,
    )
    return AppConfig(active_provider=active_provider, provider=provider, agent=agent)
