from __future__ import annotations

import asyncio
import json
import logging
import uuid
import threading
from datetime import UTC, datetime
from pathlib import Path
from fastapi import Depends
from uuid import UUID
from shared.auth.dependencies import require_user
from shared.auth.models import CurrentUser
from shared.auth.repository import AuthRepository
from shared.auth.providers import make_provider
from agent_api.auth_routes import router as auth_router
from agent_api.admin_routes import router as admin_router
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent_api.config import load_config
from agent_api.model_factory import validate_strict_response_schema
from agent_api.runtime import AgentRuntime
from agent_api.workspace import WorkspaceEntry

USER_LOCKS: dict[str, asyncio.Lock] = {}
RUNTIME_LOCK = threading.Lock()
USER_ACTIVE_TASKS: dict[str, set[asyncio.Task]] = {}
LOGGER = logging.getLogger(__name__)


class ThreadInfo(BaseModel):
    thread_id: str
    owner_user_id: str | None = None
    created_at: str
    updated_at: str
    title: str | None = None
    last_message_preview: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1)
    response_format: Literal["json"] | None = None
    response_schema: dict[str, Any] | None = None


class MessageRecord(BaseModel):
    role: str
    content: str
    created_at: str


class MessageResponse(BaseModel):
    thread_id: str
    reply: str
    provider: str
    model: str


class ProcessRequest(BaseModel):
    command: str = Field(..., min_length=1)
    cwd: str = "/"


app = FastAPI(title="deepagents-platform agent-api", version="0.1.0")

@app.middleware("http")
async def no_store_private(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/v1/") or request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
    return response

app.include_router(auth_router)
app.include_router(admin_router)


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def get_runtime(user: CurrentUser) -> AgentRuntime:
    registry = getattr(app.state, "runtime_registry", None)
    if registry is None:
        registry = {}
        app.state.runtime_registry = registry
    key = str(user.user_id)
    with RUNTIME_LOCK:
        if key not in registry:
            config = getattr(app.state, "base_config", None) or load_config()
            registry[key] = AgentRuntime.create(config, user.user_id)
    return registry[key]


def cancel_user_tasks(user_id: UUID) -> None:
    key = str(user_id)
    for task in list(USER_ACTIVE_TASKS.get(key, ())):
        task.cancel()
    getattr(app.state, "runtime_registry", {}).pop(key, None)


def user_lock(user: CurrentUser) -> asyncio.Lock:
    return USER_LOCKS.setdefault(str(user.user_id), asyncio.Lock())


def checked_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(422, "Invalid UUID") from exc


def thread_store_root(runtime: AgentRuntime) -> Path:
    root = runtime.config.agent.session_root / "threads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def transcript_path(runtime: AgentRuntime, thread_id: str) -> Path:
    path = thread_store_root(runtime) / f"{checked_id(thread_id)}.jsonl"
    if path.is_symlink():
        raise HTTPException(404, "Thread not found")
    return path


def metadata_path(runtime: AgentRuntime, thread_id: str) -> Path:
    path = thread_store_root(runtime) / f"{checked_id(thread_id)}.json"
    if path.is_symlink():
        raise HTTPException(404, "Thread not found")
    return path


def load_thread_info(runtime: AgentRuntime, thread_id: str) -> ThreadInfo:
    path = metadata_path(runtime, thread_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thread not found.")
    info = ThreadInfo.model_validate_json(path.read_text(encoding="utf-8"))
    if info.owner_user_id != str(runtime.user_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    return info


def save_thread_info(runtime: AgentRuntime, info: ThreadInfo) -> None:
    path = metadata_path(runtime, info.thread_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(info.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure_thread(runtime: AgentRuntime, thread_id: str, first_message: str | None = None) -> ThreadInfo:
    path = metadata_path(runtime, thread_id)
    if path.exists():
        return load_thread_info(runtime, thread_id)

    timestamp = utc_now()
    title = first_message[:80] if first_message else None
    info = ThreadInfo(
        thread_id=thread_id,
        owner_user_id=str(runtime.user_id),
        created_at=timestamp,
        updated_at=timestamp,
        title=title,
        last_message_preview=first_message[:120] if first_message else None,
    )
    save_thread_info(runtime, info)
    return info


def append_message(runtime: AgentRuntime, thread_id: str, record: MessageRecord) -> None:
    path = transcript_path(runtime, thread_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json())
        handle.write("\n")


def list_messages(runtime: AgentRuntime, thread_id: str) -> list[MessageRecord]:
    path = transcript_path(runtime, thread_id)
    if not path.exists():
        return []
    records: list[MessageRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(MessageRecord.model_validate(json.loads(line)))
    return records


def extract_reply(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if isinstance(result.get("output"), str):
            return result["output"]
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
                    if isinstance(raw_content, list):
                        text_chunks = [
                            chunk.get("text", "")
                            for chunk in raw_content
                            if isinstance(chunk, dict) and chunk.get("type") == "text"
                        ]
                        combined = "".join(text_chunks).strip()
                        if combined:
                            return combined
    content = getattr(result, "content", None)
    if isinstance(content, str) and content.strip():
        return content
    return str(result)


@app.on_event("startup")
async def startup() -> None:
    repository = AuthRepository()
    repository.initialize()
    make_provider(repository)
    app.state.auth_repository = repository
    app.state.base_config = load_config()
    app.state.runtime_registry = {}
    app.state.cancel_user_tasks = cancel_user_tasks



@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/threads", response_model=ThreadInfo)
def create_thread(user: CurrentUser = Depends(require_user)) -> ThreadInfo:
    runtime = get_runtime(user)
    thread_id = str(uuid.uuid4())
    return ensure_thread(runtime, thread_id)


@app.get("/v1/threads", response_model=list[ThreadInfo])
def get_threads(user: CurrentUser = Depends(require_user)) -> list[ThreadInfo]:
    runtime = get_runtime(user)
    threads: list[ThreadInfo] = []
    for path in sorted(thread_store_root(runtime).glob("*.json")):
        if path.is_symlink():
            continue
        info = ThreadInfo.model_validate_json(path.read_text(encoding="utf-8"))
        if info.owner_user_id == str(user.user_id):
            threads.append(info)
    return sorted(threads, key=lambda item: item.updated_at, reverse=True)


@app.get("/v1/threads/{thread_id}", response_model=ThreadInfo)
def get_thread(thread_id: str, user: CurrentUser = Depends(require_user)) -> ThreadInfo:
    runtime = get_runtime(user)
    return load_thread_info(runtime, thread_id)


@app.get("/v1/threads/{thread_id}/messages", response_model=list[MessageRecord])
def get_thread_messages(thread_id: str, user: CurrentUser = Depends(require_user)) -> list[MessageRecord]:
    runtime = get_runtime(user)
    load_thread_info(runtime, thread_id)
    return list_messages(runtime, thread_id)


@app.post("/v1/threads/{thread_id}/messages", response_model=MessageResponse)
async def post_thread_message(thread_id: str, request: MessageRequest, user: CurrentUser = Depends(require_user)) -> MessageResponse:
    runtime = get_runtime(user)
    info = load_thread_info(runtime, thread_id)
    if request.response_format and request.response_schema is not None:
        raise HTTPException(
            status_code=422,
            detail="Choose either response_format or response_schema, not both.",
        )
    if request.response_schema is not None:
        try:
            validate_strict_response_schema(request.response_schema)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with user_lock(user):
        info = load_thread_info(runtime, thread_id)
        task = asyncio.current_task()
        if task is not None:
            USER_ACTIVE_TASKS.setdefault(str(user.user_id), set()).add(task)
        try:
            result = await runtime.invoke(
                thread_id=thread_id,
                message=request.message,
                response_format=request.response_format,
                response_schema=request.response_schema,
            )
        except Exception as exc:
            LOGGER.exception("Agent invocation failed for thread %s", thread_id)
            raise HTTPException(502, "Agent invocation failed. Check the agent-api logs.") from exc
        finally:
            if task is not None:
                USER_ACTIVE_TASKS.get(str(user.user_id), set()).discard(task)
        reply = extract_reply(result)
        append_message(runtime, thread_id, MessageRecord(role="user", content=request.message, created_at=utc_now()))
        append_message(runtime, thread_id, MessageRecord(role="assistant", content=reply, created_at=utc_now()))
        updated = info.model_copy(update={
            "updated_at": utc_now(),
            "title": info.title or request.message[:80],
            "last_message_preview": reply[:120] if reply else request.message[:120],
        })
        save_thread_info(runtime, updated)

    return MessageResponse(
        thread_id=thread_id,
        reply=reply,
        provider=runtime.config.active_provider,
        model=runtime.config.provider.model,
    )


@app.get("/v1/tools")
def get_tools(user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime(user)
    return {
        "toolkits": runtime.tool_collection.toolkits,
        "mcp_status": runtime.mcp_status,
        "mcp_error": runtime.mcp_error,
        "mcp_tools": [
            {"name": tool.name, "description": tool.description}
            for tool in runtime.mcp_tools
        ],
    }


@app.get("/v1/files", response_model=list[WorkspaceEntry])
def list_workspace_files(path: str = "/", recursive: bool = False, max_entries: int = 200, user: CurrentUser = Depends(require_user)) -> list[WorkspaceEntry]:
    runtime = get_runtime(user)
    try:
        items = runtime.workspace.list_dir(path, recursive=recursive, max_entries=max_entries)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Path not found: {exc}") from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [WorkspaceEntry(**item) for item in items]


@app.post("/v1/processes")
def start_process(request: ProcessRequest, user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    raise HTTPException(403, "Shell execution is disabled")
    runtime = get_runtime(user)
    try:
        return runtime.process_manager.start(request.command, cwd=request.cwd)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/processes")
def list_processes(user: CurrentUser = Depends(require_user)) -> list[dict[str, Any]]:
    runtime = get_runtime(user)
    return runtime.process_manager.list_processes()


@app.get("/v1/processes/{process_id}")
def get_process(process_id: str, user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    checked_id(process_id)
    runtime = get_runtime(user)
    try:
        return runtime.process_manager.get(process_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/processes/{process_id}/output")
def get_process_output(process_id: str, stream: str = "stdout", tail_lines: int = 200, user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    checked_id(process_id)
    runtime = get_runtime(user)
    try:
        return runtime.process_manager.read_output(process_id, stream=stream, tail_lines=tail_lines)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/processes/{process_id}/stop")
def stop_process(process_id: str, force: bool = False, user: CurrentUser = Depends(require_user)) -> dict[str, Any]:
    checked_id(process_id)
    runtime = get_runtime(user)
    try:
        return runtime.process_manager.stop(process_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
