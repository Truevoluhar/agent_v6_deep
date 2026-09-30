from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import agent_api.model_factory as model_factory
from agent_api.model_factory import build_json_schema_response_format, validate_strict_response_schema
from agent_api.runtime import AgentRuntime, _seed_skills
from agent_api.workspace import WorkspaceManager


def test_seed_skills_copies_bundled_skills_into_workspace(tmp_path: Path) -> None:
    source_root = tmp_path / "app-skills"
    source_skill = source_root / "demo-skill"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill\n---\n",
        encoding="utf-8",
    )

    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_layout()

    _seed_skills(workspace, "/.agent/skills", source_root=source_root)

    copied_skill = workspace.resolve_path("/.agent/skills/demo-skill/SKILL.md")
    assert copied_skill.exists()
    assert "demo-skill" in copied_skill.read_text(encoding="utf-8")


def test_build_system_prompt_adds_json_instructions_only_when_selected() -> None:
    runtime = AgentRuntime(
        config=SimpleNamespace(agent=SimpleNamespace(system_prompt="Base instructions")),
        workspace=None,
        process_manager=None,
        shell_env={},
        tool_collection=SimpleNamespace(toolkits=[]),
    )

    default_prompt = runtime.build_system_prompt()
    json_prompt = runtime.build_system_prompt(response_format="json")

    assert default_prompt.startswith("Base instructions")
    assert "Final response format: JSON" not in default_prompt
    assert "Final response format: JSON" in json_prompt
    assert "Do not wrap it in Markdown fences" in json_prompt


def test_json_schema_response_format_uses_native_strict_mode() -> None:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }

    response_format = build_json_schema_response_format(schema)

    assert response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": schema,
        },
    }


def test_build_chat_model_passes_schema_to_openai_compatible_client(monkeypatch) -> None:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    langchain_openai = ModuleType("langchain_openai")
    langchain_openai.ChatOpenAI = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "langchain_openai", langchain_openai)
    monkeypatch.setattr(model_factory, "configure_process_tls", lambda provider: None)
    monkeypatch.setattr(model_factory, "build_ssl_context", lambda provider: False)
    monkeypatch.setattr(model_factory.httpx, "Client", lambda **kwargs: "sync-client")
    monkeypatch.setattr(model_factory.httpx, "AsyncClient", lambda **kwargs: "async-client")
    provider = SimpleNamespace(
        type="openai_compatible",
        model="test-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
        temperature=0,
        timeout_seconds=30,
        max_retries=1,
    )

    model_kwargs = model_factory.build_chat_model(provider, response_schema=schema)

    assert model_kwargs["extra_body"]["response_format"] == build_json_schema_response_format(schema)


def test_validate_strict_response_schema_accepts_nested_required_objects() -> None:
    validate_strict_response_schema(
        {
            "type": "object",
            "properties": {
                "result": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                }
            },
            "required": ["result"],
            "additionalProperties": False,
        }
    )


def test_validate_strict_response_schema_rejects_missing_required_properties() -> None:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    }

    try:
        validate_strict_response_schema(schema)
    except ValueError as exc:
        assert str(exc) == "$.required must list every property exactly once."
    else:
        raise AssertionError("Invalid strict schema was accepted.")
