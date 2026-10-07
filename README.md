# deepagents-platform

General-purpose DeepAgents platform scaffold with Docker Compose, a repo-visible `data/` persistence folder, PostgreSQL-backed checkpoints, a file-management API, and an independent Streamlit client.

## Services

- `agent-api` on `:8081`: DeepAgents workflow runtime.
- `workspace-api` on `:8090`: safe upload/list/download/delete API for the shared workspace.
- `client` on `:8501`: simple chat and workspace browser UI.
- `postgres`: LangGraph checkpoint storage.

## Quick start

```bash
cp .env.example .env
docker compose up -d --build
```

Health checks:

```bash
curl http://localhost:8081/health
curl http://localhost:8090/health
```

Open `http://localhost:8501`.

## Provider switching

Edit `.env`:

```dotenv
ACTIVE_PROVIDER=openai
OPENAI_API_KEY=your-real-key
```

Or:

```dotenv
ACTIVE_PROVIDER=vllm
VLLM_BASE_URL=http://your-vllm-host:8000/v1
VLLM_API_KEY=dummy
```

Or:

```dotenv
ACTIVE_PROVIDER=bifrost
BIFROST_BASE_URL=http://your-bifrost-host:8080/openai
BIFROST_MODEL=openai/gpt-4o-mini
BIFROST_API_KEY=dummy-key
```

OpenAI needs no certificate files or custom TLS settings.

Bifrost also needs no extra certificate settings in the local/private setup you described. Point the OpenAI-compatible client at the gateway's `/openai` base URL and keep the upstream provider keys inside Bifrost.

For private vLLM TLS or mTLS gateways, place your certificate files in the repo-local `certs/` directory and set the vLLM-specific options in `.env`:

```dotenv
VLLM_TLS_VERIFY=true
VLLM_CA_FILE=/certs/internal-ca.pem
VLLM_CLIENT_CERT_FILE=/certs/client.pem
VLLM_CLIENT_KEY_FILE=/certs/client.key
```

Set `VLLM_TLS_VERIFY=false` only when you intentionally want to disable certificate verification.

Provider definitions live in [config/providers.yaml](/workspaces/agent_v6_deep/config/providers.yaml).

## Structured responses

In the chat UI, select **JSON Schema** and edit the schema for the response. The API accepts the schema on a per-message basis:

```json
{
  "message": "Summarize the report",
  "response_schema": {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": false
  }
}
```

The agent sends this using strict JSON Schema output mode through the configured OpenAI-compatible provider. Strict mode requires every object property to be listed in `required` and `additionalProperties` to be `false`. Schema adherence depends on the routed model/provider supporting structured outputs; refusals and incomplete responses may not match the schema.

## Persistence

Persistent data lives in the repo-local `data/` folder, following the same broad shape as `agent_v5_1`:

```text
data/
  agent_workspace/   Agent-visible workspace files
  session/           Thread metadata and transcripts
  memory/            Reserved durable memory area
  resources/         Shared resources area
  runs/              Background process logs and run artifacts
```

The agent workspace is `data/agent_workspace/`. Rebuilding or restarting the services does not remove the contents of `data/`. PostgreSQL remains durable through its own Docker volume.

## Layout

```text
config/           Provider configuration
agent_api/        DeepAgents FastAPI service
workspace_api/    Workspace FastAPI service
client/           Streamlit UI
data/             Visible persistent data root
skills/           Starter DeepAgents skills
workspace_seed/   Initial AGENTS.md memory seed
tests/            Config loader tests
```

## Multi-user access

Local login, per-user workspaces, administrator account management, and mandatory `guid` query authentication are described in [MULTIUSER.md](MULTIUSER.md). The initial account is `admin` / `admin123`; change its password after the first login. Shell execution and shared MCP tools are disabled because this Compose deployment has no verified execution sandbox.

## Notes

- The application does not implement response streaming.
- Use a single agent-api worker; invocation locks are local to that process.
