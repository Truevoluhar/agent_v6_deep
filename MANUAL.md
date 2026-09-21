# Building a General-Purpose DeepAgents Platform with Docker Compose

**Reference implementation:** `deepagents-platform`  
**Target:** reliable, provider-switchable agentic system for file analysis, artifact creation, code review, defensive vulnerability review, Draw.io generation, research-style multi-step work, and general engineering tasks.  
**Runtime:** Docker Compose  
**LLM backends:** public OpenAI or private OpenAI-compatible vLLM  
**DeepAgents baseline:** `deepagents==0.7.15`

---

## 1. Goals and design constraints

The platform has three logical components:

1. **DeepAgents workflow service** — owns orchestration, model calls, DeepAgents middleware, skills, planning, subagent behavior, checkpoint integration, and the shell/filesystem tool surface.
2. **Persistent data and agent workspace** — owns durable files/artifacts plus persistent graph state. The reference implementation uses a named Docker volume for the workspace and PostgreSQL for LangGraph checkpoints.
3. **Client/chat service** — a separate UI that manages chat sessions and workspace uploads/browsing without embedding the agent runtime into the UI process.

The critical architectural rule is that the agent container is disposable. Rebuilding or replacing `agent-api` must not erase user files or conversation state.

The system also needs a provider abstraction. Application code should not care whether the model is OpenAI-hosted or a private vLLM endpoint. Both are represented as OpenAI-compatible chat models, selected through configuration.

---

## 2. Why DeepAgents fits this architecture

DeepAgents is a LangGraph-based agent harness with built-in planning, filesystem tools, subagents, skills, context management, persistent-memory hooks, and pluggable backends. It is specifically designed for long-running multi-step agent workflows and is model-agnostic as long as the selected model supports tool calling.

Two kinds of persistence must be treated separately:

- **Graph/checkpoint persistence** stores conversation state, interrupts, resumability, and agent graph state.
- **Filesystem/memory persistence** stores files, generated artifacts, durable instructions, project context, and handoff material shared between parent agents and subagents.

DeepAgents itself makes this distinction. Do not assume that durable chat state automatically makes workspace files durable, or vice versa.

---

## 3. Reference architecture

```text
                         +-----------------------------+
                         |        Browser / User       |
                         +--------------+--------------+
                                        |
                                        v
                         +-----------------------------+
                         |       client :8501          |
                         |  Streamlit chat/workspace   |
                         +------+----------------------+
                                | HTTP
                  +-------------+------------------+
                  |                                |
                  v                                v
        +----------------------+         +----------------------+
        | agent-api :8080      |         | workspace-api :8090  |
        | DeepAgents workflow  |         | upload/list/download |
        | LangGraph checkpoint |         | path-safe file API   |
        | shell/filesystem     |         +----------+-----------+
        +----+-------------+---+                    |
             |             |                        |
             |             +------------------------+
             |                      shared named volume
             |                                |
             v                                v
      +-------------+                  +--------------------+
      | PostgreSQL  |                  | agent_workspace    |
      | checkpoints |                  | persistent volume  |
      +-------------+                  +--------------------+
             |
             +--- persistent named volume postgres_data

        agent-api ---> OpenAI API OR private vLLM /v1 endpoint
```

### Docker Compose services

- `postgres` — persistent checkpoint database.
- `workspace-api` — small file-management service that exposes controlled upload/list/download/delete operations.
- `agent-api` — the DeepAgents execution service.
- `client` — the independent chat/workspace UI.

### Docker named volumes

- `postgres_data` — PostgreSQL data directory.
- `agent_workspace` — durable agent workspace.

This is intentionally more durable than putting files in the agent image or container writable layer.

---

## 4. Repository layout

```text
deepagents-platform/
├── docker-compose.yml
├── .env.example
├── Makefile
├── README.md
├── MANUAL.md
├── config/
│   └── providers.yaml
├── agent_api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py
│   ├── model_factory.py
│   └── main.py
├── workspace_api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
├── client/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── skills/
│   ├── file-analysis/SKILL.md
│   ├── drawio/SKILL.md
│   ├── code-review/SKILL.md
│   └── security-review/SKILL.md
├── workspace_seed/
│   └── .agent/AGENTS.md
└── tests/
    └── test_config.py
```

---

## 5. Provider configuration

Provider behavior lives in `config/providers.yaml`.

```yaml
active_provider: ${ACTIVE_PROVIDER:-openai}

providers:
  openai:
    type: openai_compatible
    model: gpt-5.5
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    temperature: 0
    timeout_seconds: 180
    max_retries: 3

  vllm:
    type: openai_compatible
    model: openai/gpt-oss-120b
    base_url: ${VLLM_BASE_URL:-http://host.docker.internal:8000/v1}
    api_key: ${VLLM_API_KEY:-dummy}
    temperature: 0
    timeout_seconds: 180
    max_retries: 2
```

Secrets should **not** be committed directly into YAML. The YAML is the provider configuration surface, while `.env` supplies the secret values.

The loader supports `${NAME}` and `${NAME:-default}` expansion. This gives you one obvious place to swap provider settings without hard-coding model configuration into Python.

### Switch from OpenAI to vLLM

In `.env`:

```dotenv
ACTIVE_PROVIDER=vllm
VLLM_BASE_URL=http://your-vllm-host:8000/v1
VLLM_API_KEY=dummy-or-real-key
```

Then rebuild/restart:

```bash
docker compose up -d --build agent-api
```

No workflow code changes are required.

---

## 6. OpenAI setup

Create `.env` from the example:

```bash
cp .env.example .env
```

Set:

```dotenv
ACTIVE_PROVIDER=openai
OPENAI_API_KEY=your-real-key
```

Keep the model name in `config/providers.yaml`. The reference implementation uses `ChatOpenAI` and supplies `model`, `api_key`, and `base_url` from the provider configuration.

For production, inject secrets using your deployment secret manager rather than a checked-in `.env` file. Docker secrets, Kubernetes Secrets, Vault, 1Password Connect, AWS Secrets Manager, or a similar system are all better than embedding API keys in source control.

---

## 7. Private vLLM setup

vLLM exposes OpenAI-compatible endpoints, so the same `ChatOpenAI` client class can be used by changing `base_url`, `api_key`, and `model`.

A DeepAgents workload needs reliable **tool calling**, not only normal text generation. Configure vLLM accordingly.

Typical launch pattern:

```bash
vllm serve <your-tool-capable-model> \
  --host 0.0.0.0 \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser <parser-for-your-model> \
  --tool-strict-level function
```

The exact parser is model-specific. Current vLLM documentation includes parsers for families such as OpenAI OSS, Hermes, Kimi, Qwen-derived/tool-aware models, and others. Verify the parser recommended for your model.

### Important vLLM requirements

1. The model must actually be good at structured tool use. An OpenAI-compatible HTTP endpoint alone is not sufficient.
2. `--enable-auto-tool-choice` is required for automatic tool selection.
3. `--tool-call-parser` must match the model/tool protocol.
4. Prefer strict tool-call enforcement when the selected parser/model supports it.
5. Test multi-turn tool calls, not only a one-shot `/v1/chat/completions` response.
6. `VLLM_API_KEY` alone is not a complete perimeter security layer. vLLM documentation warns that some non-`/v1` endpoints may not be protected by that key; put private vLLM behind a reverse proxy, firewall, VPN, or service mesh policy.

### Network note for Docker Compose

`host.docker.internal` works conveniently on Docker Desktop. On native Linux, either:

- use the routable IP/DNS name of the vLLM host, or
- add an `extra_hosts` host-gateway mapping if appropriate for your environment.

If vLLM is another Compose service, put it on a network reachable by `agent-api` and use its Compose service name.

---

## 8. DeepAgents workflow service

The workflow service builds the model, persistent checkpointer, filesystem backend, memory file, skills, and agent graph.

Core construction:

```python
backend = LocalShellBackend(
    root_dir=workspace,
    virtual_mode=True,
    inherit_env=False,
    env={
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/workspace/.agent/home",
    },
)

agent = create_deep_agent(
    model=model,
    system_prompt=cfg.agent.system_prompt,
    backend=backend,
    checkpointer=checkpointer,
    memory=["/.agent/AGENTS.md"],
    skills=["/app/skills/"],
)
```

### Why `inherit_env=False`

A general-purpose shell agent must not automatically inherit API keys and infrastructure secrets into every shell command. The agent service itself needs provider credentials, but the shell subprocess environment should be minimized.

The reference implementation exposes only a small `PATH` and `HOME` to agent-executed commands.

If a task genuinely needs credentials—for example, an authenticated Git clone—pass narrowly scoped temporary credentials through a dedicated tool or controlled execution wrapper rather than exposing every environment variable globally.

---

## 9. Persistent workspace

`agent_workspace` is a Docker named volume mounted at `/workspace` in both `agent-api` and `workspace-api`.

Recommended convention:

```text
/workspace/
├── uploads/                 # user uploads
├── projects/                # checked out or generated projects
├── analysis/                # reports and derived outputs
├── diagrams/                # .drawio and related docs
├── exports/                 # deliverables
└── .agent/
    ├── AGENTS.md             # persistent project/user-approved memory
    ├── home/                 # shell HOME
    └── runs/                 # optional per-thread scratch/history artifacts
```

Parent agents and DeepAgents subagents should use filesystem paths as the handoff mechanism for large files and durable work products. Subagents intentionally have isolated context windows; the shared backend/workspace is the reliable bridge.

### Do not store secrets in the workspace

The model has filesystem tools. Anything under the agent-visible workspace should be considered readable by the model and by agent-executed commands.

Do not place `.env`, SSH private keys, cloud credentials, production kubeconfigs, or unrelated host files in this volume.

---

## 10. PostgreSQL checkpoint persistence

The agent uses `PostgresSaver`:

```python
with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    checkpointer.setup()
    agent = create_deep_agent(..., checkpointer=checkpointer)
```

Every chat uses a stable `thread_id`:

```python
config = {
    "configurable": {"thread_id": thread_id},
    "recursion_limit": 120,
}
```

Reuse the same `thread_id` to continue a conversation. Generate a new one to start a fresh chat.

The provided MVP serializes access to the synchronous `PostgresSaver` with a process-local lock. For real horizontal scale, replace this with the async Postgres checkpointer and an async connection pool, and run multiple API workers only after validating concurrent checkpoint semantics.

---

## 11. Client/chat service

The client is intentionally independent from the workflow runtime.

Its responsibilities are:

- create/reuse chat `thread_id` values,
- submit messages to `agent-api`,
- upload input files through `workspace-api`,
- browse workspace files,
- display generated paths and results.

The reference UI uses Streamlit because it keeps the example small. Replace it with React/Next.js/Vue/Svelte or a desktop client later without changing the agent core.

Recommended production API surface:

```text
POST   /v1/threads
GET    /v1/threads
GET    /v1/threads/{id}
POST   /v1/threads/{id}/messages
GET    /v1/threads/{id}/events       # SSE/WebSocket streaming
POST   /v1/files
GET    /v1/files
GET    /v1/files/{path}
DELETE /v1/files/{path}
GET    /v1/runs/{id}
POST   /v1/runs/{id}/cancel
```

The starter keeps only the minimum endpoints needed to demonstrate separation.

---

## 12. Skills: making an “agent for everything” manageable

A general agent should not have one enormous system prompt. Keep the stable behavioral core short and load task-specific instructions as skills.

The scaffold includes four starter skills:

- **file-analysis** — targeted inspection, safe handling of large inputs, derived artifacts.
- **drawio** — editable diagrams.net XML plus a Markdown explanation.
- **code-review** — correctness, maintainability, tests, performance, API risk.
- **security-review** — authorized defensive vulnerability review and remediation.

Add more directories under `skills/`:

```text
skills/
├── pdf-analysis/
│   └── SKILL.md
├── spreadsheet-analysis/
│   └── SKILL.md
├── dependency-upgrade/
│   └── SKILL.md
├── terraform-review/
│   └── SKILL.md
├── kubernetes-review/
│   └── SKILL.md
└── release-engineering/
    └── SKILL.md
```

This is easier to test and evolve than continually expanding a monolithic system prompt.

---

## 13. Draw.io artifact generation

The agent can create `.drawio` files directly because Draw.io uses an XML format.

Recommended contract for the diagram skill:

1. write `diagram.drawio`,
2. validate XML well-formedness,
3. write `diagram.md` describing nodes, flows, assumptions, and editing instructions,
4. optionally render or export SVG/PNG if a renderer is installed.

For a future richer image pipeline, add an artifact-rendering service rather than bloating the core agent image.

---

## 14. Code review workflow

A robust code-review task should roughly follow this sequence:

```text
inspect repository
  -> detect languages/build system
  -> read project instructions
  -> inspect git diff / requested scope
  -> run existing tests/static checks where safe
  -> targeted source review
  -> produce evidence-backed findings
  -> optional patch/artifact
```

Keep generated patches separate unless the user requested in-place modification. This makes review safer and easier to audit.

---

## 15. Defensive vulnerability search

For repository-level vulnerability review, include tools such as these in a hardened agent image as needed:

- `ripgrep`
- `git`
- language package managers
- `semgrep`
- `trivy`
- `grype`
- `syft`
- `pip-audit`
- `npm audit`
- `govulncheck`

Do not install every scanner blindly. Build task-specific worker images or profiles if image size and supply-chain control matter.

A good security finding contains:

- exact file/package,
- affected code or version,
- evidence,
- impact,
- confidence,
- remediation,
- validation method.

Avoid treating scanner output as automatically confirmed vulnerability evidence.

---

## 16. Security model

### MVP boundary

The reference implementation uses `LocalShellBackend` **inside the `agent-api` container**. This is materially safer than running it directly on the Docker host, but it is still an unrestricted shell inside that container and can modify everything mounted read-write into it.

Security properties included in the Compose scaffold:

- no Docker socket mount,
- non-root application users,
- Linux capabilities dropped,
- `no-new-privileges`,
- agent shell does not inherit the full process environment,
- persistent workspace mounted explicitly,
- config/skills mounted read-only,
- database isolated on an internal Compose network.

### Production boundary

For multi-user or untrusted input, use a real execution isolation layer:

```text
agent-api
   |
   +--> sandbox manager
           |
           +--> ephemeral container/VM per task or per tenant
                   |
                   +--> scoped workspace mount/object store
```

Options include dedicated Docker containers without exposing the Docker socket to the agent, Kubernetes Jobs/Pods, Firecracker microVMs, or a managed sandbox provider.

DeepAgents documentation explicitly warns that its local shell backend is not a production sandbox. Treat this as a hard architectural boundary, not a prompt-engineering problem.

### Network egress

For sensitive deployments, default-deny sandbox egress and expose only approved destinations through a proxy. A general coding agent with arbitrary shell and unrestricted outbound network access creates a straightforward secret-exfiltration path if credentials are ever accidentally mounted.

---

## 17. Reliability practices

A reliable general-purpose agent is mostly an engineering problem around the model.

### Use timeouts everywhere

- model request timeout,
- shell command timeout,
- HTTP upload/download timeout,
- client request timeout,
- long-run cancellation deadline.

### Bound agent recursion

The reference config uses a `recursion_limit`. Tune it by workload and model. Extremely large limits can turn a bad plan into an expensive loop.

### Preserve intermediate artifacts

For expensive analyses, write intermediate results to workspace files. This makes runs inspectable and resumable and reduces dependence on an ever-growing context window.

### Idempotency

For mutation-heavy tasks, make tools or task instructions idempotent when practical. Prefer `mkdir -p`, explicit output paths, temporary files followed by atomic rename, and checksum-based decisions.

### Model capability tests

A provider should pass a minimum acceptance suite before being enabled:

1. simple answer,
2. one tool call,
3. multiple sequential tool calls,
4. tool call followed by filesystem read,
5. write file and read it back,
6. shell command,
7. long multi-step plan,
8. recover from a failed tool,
9. continue the same thread after restart,
10. generate a valid Draw.io XML artifact.

This is especially important for private vLLM models because tool-call quality varies significantly by model and parser.

---

## 18. Observability

For production, capture at least:

- request ID,
- thread ID,
- run ID,
- model/provider name,
- model latency,
- tool name and duration,
- tool exit status,
- token/cost usage where available,
- workspace artifacts generated,
- error class,
- retry count.

Never log API keys, authorization headers, or complete secret-bearing environment dumps.

LangSmith can be added for LangGraph/DeepAgents tracing, but it should be optional if your environment must remain fully private. An OpenTelemetry-based path is a good provider-neutral complement.

---

## 19. Human-in-the-loop controls

For powerful tasks, add approval gates for operations such as:

- destructive file deletion,
- `git push`,
- external network writes,
- package publishing,
- deployment commands,
- database mutations,
- changes outside the designated project path.

DeepAgents supports human-in-the-loop interruption patterns. Use them for high-impact tools rather than relying solely on natural-language instructions.

---

## 20. Running the reference stack

### Step 1 — configure

```bash
cd deepagents-platform
cp .env.example .env
```

Edit `.env` and `config/providers.yaml`.

### Step 2 — build and start

```bash
docker compose up -d --build
```

### Step 3 — check health

```bash
curl http://localhost:8080/health
curl http://localhost:8090/health
```

### Step 4 — open the client

Open:

```text
http://localhost:8501
```

### Step 5 — test persistence

1. Upload a file.
2. Ask the agent to analyze it and create a report.
3. Note the thread ID.
4. Run `docker compose restart agent-api client`.
5. Reopen the same thread ID and verify the workspace files still exist.
6. Continue the conversation and verify graph state is available.

### Step 6 — test full restart

```bash
docker compose down
docker compose up -d
```

Named volumes remain. `docker compose down -v` intentionally removes them.

---

## 21. Provider smoke tests

### OpenAI-compatible endpoint check

Before involving DeepAgents, validate the endpoint itself:

```bash
curl "$BASE_URL/models" \
  -H "Authorization: Bearer $API_KEY"
```

Then test a basic chat response using the official OpenAI SDK or a small script.

### Tool-calling check

The important test is not merely “can it answer hello?” but “can it choose and format tools correctly?”. Use a minimal tool schema, request `tool_choice=auto`, and confirm the response contains a valid structured tool call.

For vLLM, run this test after every model/parser/chat-template change.

---

## 22. Production evolution path

### Phase 1 — single-user / trusted environment

Use this scaffold almost as-is:

- one `agent-api`,
- shared named workspace volume,
- PostgreSQL checkpointer,
- Streamlit client,
- agent shell inside its container.

### Phase 2 — team usage

Add:

- authentication,
- per-user/per-project workspace namespaces,
- explicit database tables for thread metadata,
- async streaming,
- run cancellation,
- quotas,
- per-tool approval policy,
- audit logs,
- reverse proxy/TLS.

### Phase 3 — untrusted/multi-tenant

Replace local shell execution with isolated sandboxes:

- sandbox per run/project/user,
- scoped filesystem/object storage,
- network policy,
- CPU/memory/PID quotas,
- execution TTL,
- artifact synchronization back to the persistent workspace,
- secret broker rather than static credentials.

### Phase 4 — high availability

Add:

- async PostgreSQL pool,
- multiple stateless agent-api replicas,
- queue/worker model for long-running jobs,
- Redis/NATS/Kafka if needed for event delivery,
- object storage for large artifacts,
- database backups,
- volume/object-store retention policy.

---

## 23. Recommended future service split

For a mature “Claude Code / Codex-like” internal platform, evolve toward:

```text
web-client
api-gateway
identity-service
conversation-service
agent-orchestrator
sandbox-manager
artifact-service
postgres
object-storage
observability stack
optional vector/search service
```

Do not start with all of these unless you need them. The provided four-service Compose setup is deliberately small enough to understand and operate.

---

## 24. Configuration philosophy

Keep three layers distinct:

### Non-secret, deploy-time configuration

`config/providers.yaml`

Examples:

- active model,
- base URL,
- timeouts,
- retry count,
- recursion limit,
- default agent instructions.

### Secrets

`.env` for local development; secret manager in production.

Examples:

- OpenAI API key,
- vLLM bearer token,
- database password,
- external tool credentials.

### Durable agent/project memory

`/workspace/.agent/AGENTS.md`

Examples:

- coding conventions,
- stable repository context,
- user-approved project instructions.

Never mix these layers.

---

## 25. Known limitations of the starter

The reference implementation is intentionally an MVP and has these limitations:

- response streaming is not implemented,
- only one synchronous agent invocation is processed at a time per `agent-api` process,
- no authentication or authorization,
- no tenant separation,
- file deletion API handles files only, not recursive directories,
- no dedicated sandbox service,
- no background job queue/cancellation API,
- no first-class artifact preview,
- no explicit conversation index table in the client,
- no object storage for very large files,
- no provider capability registry beyond OpenAI-compatible endpoints.

These are the first items to address when moving from a private/internal prototype to a production platform.

---

## 26. Test status for this generated scaffold

The source tree was statically checked with Python `compileall`; the Python files compile successfully.

A full Docker Compose live test could not be executed in the environment that generated this package because the Docker CLI/daemon is not available there.

A real provider call also could not be executed because no usable `.env`/`OPENAI_API_KEY` was mounted into that runtime, and package installation from PyPI was unavailable from the local shell environment due to network/DNS restrictions. Therefore, treat the included version pins and code as a verified design/statically checked starter, then run the provider acceptance tests above on the target Docker host.

---

## 27. Recommended first changes after you clone it

1. Put a real provider key in your local `.env` or secret manager.
2. Confirm the OpenAI model name you want to use.
3. For vLLM, select a strong tool-calling model and the exact parser recommended by your vLLM version.
4. Run the 10-point provider acceptance suite.
5. Add SSE/WebSocket streaming.
6. Add authentication before exposing the services beyond localhost/private network.
7. Move shell execution into a dedicated sandbox before accepting untrusted users or files.
8. Add task-specific tools and skills rather than expanding the system prompt indefinitely.
9. Add automated integration tests that restart services and verify both checkpoint and workspace persistence.
10. Back up PostgreSQL and the workspace/object storage before treating the platform as durable production infrastructure.

---

## 28. Primary upstream references

- DeepAgents repository and current README: https://github.com/langchain-ai/deepagents
- DeepAgents architecture: https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md
- DeepAgents local shell backend security notes: https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/backends/local_shell.py
- LangGraph persistence documentation: https://docs.langchain.com/oss/python/langgraph/add-memory
- vLLM OpenAI-compatible server: https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/
- vLLM tool calling: https://docs.vllm.ai/en/latest/features/tool_calling/

