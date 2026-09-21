from __future__ import annotations

from pathlib import Path

from agent_api.config import expand_env_placeholders, load_config, load_provider_file


def test_expand_env_placeholders_handles_defaults() -> None:
    rendered = expand_env_placeholders(
        "provider=${ACTIVE_PROVIDER:-openai} key=${OPENAI_API_KEY:-unset}",
        env={},
    )
    assert rendered == "provider=openai key=unset"


def test_expand_env_placeholders_uses_env_values() -> None:
    rendered = expand_env_placeholders(
        "provider=${ACTIVE_PROVIDER:-openai}",
        env={"ACTIVE_PROVIDER": "vllm"},
    )
    assert rendered == "provider=vllm"


def test_load_provider_file_and_config(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.yaml"
    config_path.write_text(
        "\n".join(
            [
                "active_provider: ${ACTIVE_PROVIDER:-openai}",
                "providers:",
                "  openai:",
                "    type: openai_compatible",
                "    model: gpt-test",
                "    base_url: https://api.example.com/v1",
                "    api_key: ${OPENAI_API_KEY:-test-key}",
                "    temperature: 0",
                "    timeout_seconds: 90",
                "    max_retries: 4",
            ]
        ),
        encoding="utf-8",
    )

    raw = load_provider_file(config_path, env={"OPENAI_API_KEY": "abc123"})
    assert raw["providers"]["openai"]["api_key"] == "abc123"

    config = load_config(
        config_path=config_path,
        env={
            "OPENAI_API_KEY": "abc123",
            "AGENT_DATA_ROOT": str(tmp_path / "data"),
            "WORKSPACE_ROOT": str(tmp_path / "data" / "agent_workspace"),
            "DATABASE_URL": "postgresql://example",
        },
    )
    assert config.active_provider == "openai"
    assert config.provider.model == "gpt-test"
    assert config.provider.api_key == "abc123"
    assert config.agent.data_root == tmp_path / "data"
    assert config.agent.workspace_root == tmp_path / "data" / "agent_workspace"
    assert config.agent.session_root == tmp_path / "data" / "session"
    assert config.agent.memory_root == tmp_path / "data" / "memory"
    assert config.agent.resources_root == tmp_path / "data" / "resources"
    assert config.agent.runs_root == tmp_path / "data" / "runs"
    assert config.agent.database_url == "postgresql://example"
    assert config.agent.use_checkpointer is True
    assert config.agent.enabled_toolkits == ["filesystem", "shell"]
