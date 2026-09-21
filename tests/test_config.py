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
                "  vllm:",
                "    type: openai_compatible",
                "    model: vllm-test",
                "    base_url: https://vllm.example.com/v1",
                "    api_key: ${VLLM_API_KEY:-dummy}",
                "    temperature: 0",
                "    timeout_seconds: 120",
                "    max_retries: 2",
                "    tls_verify: ${VLLM_TLS_VERIFY:-true}",
                "    tls_ca_file: ${VLLM_CA_FILE:-}",
                "    tls_client_cert_file: ${VLLM_CLIENT_CERT_FILE:-}",
                "    tls_client_key_file: ${VLLM_CLIENT_KEY_FILE:-}",
            ]
        ),
        encoding="utf-8",
    )

    raw = load_provider_file(config_path, env={"OPENAI_API_KEY": "abc123"})
    assert raw["providers"]["openai"]["api_key"] == "abc123"

    openai_config = load_config(
        config_path=config_path,
        env={
            "OPENAI_API_KEY": "abc123",
            "AGENT_DATA_ROOT": str(tmp_path / "data"),
            "WORKSPACE_ROOT": str(tmp_path / "data" / "agent_workspace"),
            "DATABASE_URL": "postgresql://example",
        },
    )
    assert openai_config.active_provider == "openai"
    assert openai_config.provider.model == "gpt-test"
    assert openai_config.provider.api_key == "abc123"
    assert openai_config.agent.data_root == tmp_path / "data"
    assert openai_config.agent.workspace_root == tmp_path / "data" / "agent_workspace"
    assert openai_config.agent.session_root == tmp_path / "data" / "session"
    assert openai_config.agent.memory_root == tmp_path / "data" / "memory"
    assert openai_config.agent.resources_root == tmp_path / "data" / "resources"
    assert openai_config.agent.runs_root == tmp_path / "data" / "runs"
    assert openai_config.agent.database_url == "postgresql://example"
    assert openai_config.agent.use_checkpointer is True
    assert openai_config.agent.enabled_toolkits == ["filesystem", "shell"]
    assert openai_config.provider.tls_verify is True
    assert openai_config.provider.tls_ca_file is None
    assert openai_config.provider.tls_client_cert_file is None
    assert openai_config.provider.tls_client_key_file is None

    vllm_config = load_config(
        config_path=config_path,
        env={
            "ACTIVE_PROVIDER": "vllm",
            "VLLM_API_KEY": "dummy",
            "VLLM_TLS_VERIFY": str(tmp_path / "certs" / "corp-ca.pem"),
            "VLLM_CA_FILE": str(tmp_path / "certs" / "corp-ca.pem"),
            "VLLM_CLIENT_CERT_FILE": str(tmp_path / "certs" / "client.pem"),
            "VLLM_CLIENT_KEY_FILE": str(tmp_path / "certs" / "client.key"),
        },
    )
    assert vllm_config.active_provider == "vllm"
    assert vllm_config.provider.model == "vllm-test"
    assert vllm_config.provider.tls_verify == str(tmp_path / "certs" / "corp-ca.pem")
    assert vllm_config.provider.tls_ca_file == str(tmp_path / "certs" / "corp-ca.pem")
    assert vllm_config.provider.tls_client_cert_file == str(tmp_path / "certs" / "client.pem")
    assert vllm_config.provider.tls_client_key_file == str(tmp_path / "certs" / "client.key")
