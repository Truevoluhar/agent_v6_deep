# deepagents-platform

General-purpose DeepAgents platform scaffold with Docker Compose, a repo-visible `data/` persistence folder, PostgreSQL-backed checkpoints, a file-management API, and an independent Streamlit client.

## Services

- `agent-api` on `:8080`: DeepAgents workflow runtime.
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
curl http://localhost:8080/health
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

OpenAI needs no certificate files or custom TLS settings.

For private vLLM TLS or mTLS gateways, place your certificate files in the repo-local `certs/` directory and set the vLLM-specific options in `.env`:

```dotenv
VLLM_TLS_VERIFY=true
VLLM_CA_FILE=/certs/internal-ca.pem
VLLM_CLIENT_CERT_FILE=/certs/client.pem
VLLM_CLIENT_KEY_FILE=/certs/client.key
```

Set `VLLM_TLS_VERIFY=false` only when you intentionally want to disable certificate verification.

Provider definitions live in [config/providers.yaml](/workspaces/agent_v6_deep/config/providers.yaml).

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

## Notes

- The scaffold is an MVP and does not implement response streaming, auth, or a dedicated sandbox manager.
- The local shell backend runs inside the `agent-api` container and should not be treated as a production isolation boundary.
