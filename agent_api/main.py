from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent_api.config import load_config
from agent_api.runtime import AgentRuntime
from agent_api.workspace import WorkspaceEntry

THREAD_LOCK = threading.Lock()


class ThreadInfo(BaseModel):
    thread_id: str
    created_at: str
    updated_at: str
    title: str | None = None
    last_message_preview: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1)


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def get_runtime() -> AgentRuntime:
    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        runtime = AgentRuntime.create(load_config())
        app.state.runtime = runtime
    return runtime


def thread_store_root(runtime: AgentRuntime) -> Path:
    root = runtime.config.agent.session_root / "threads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def transcript_path(runtime: AgentRuntime, thread_id: str) -> Path:
    return thread_store_root(runtime) / f"{thread_id}.jsonl"


def metadata_path(runtime: AgentRuntime, thread_id: str) -> Path:
    return thread_store_root(runtime) / f"{thread_id}.json"


def load_thread_info(runtime: AgentRuntime, thread_id: str) -> ThreadInfo:
    path = metadata_path(runtime, thread_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thread not found.")
    return ThreadInfo.model_validate_json(path.read_text(encoding="utf-8"))


def save_thread_info(runtime: AgentRuntime, info: ThreadInfo) -> None:
    metadata_path(runtime, info.thread_id).write_text(
        info.model_dump_json(indent=2),
        encoding="utf-8",
    )


def ensure_thread(runtime: AgentRuntime, thread_id: str, first_message: str | None = None) -> ThreadInfo:
    path = metadata_path(runtime, thread_id)
    if path.exists():
        return ThreadInfo.model_validate_json(path.read_text(encoding="utf-8"))

    timestamp = utc_now()
    title = first_message[:80] if first_message else None
    info = ThreadInfo(
        thread_id=thread_id,
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
def startup() -> None:
    app.state.runtime = AgentRuntime.create(load_config())


@app.get("/health")
def health() -> dict[str, str]:
    runtime = get_runtime()
    return {
        "status": "ok",
        "provider": runtime.config.active_provider,
        "model": runtime.config.provider.model,
        "toolkits": ",".join(runtime.config.agent.enabled_toolkits),
    }


@app.post("/v1/threads", response_model=ThreadInfo)
def create_thread() -> ThreadInfo:
    runtime = get_runtime()
    thread_id = str(uuid.uuid4())
    return ensure_thread(runtime, thread_id)


@app.get("/v1/threads", response_model=list[ThreadInfo])
def get_threads() -> list[ThreadInfo]:
    runtime = get_runtime()
    threads: list[ThreadInfo] = []
    for path in sorted(thread_store_root(runtime).glob("*.json")):
        threads.append(ThreadInfo.model_validate_json(path.read_text(encoding="utf-8")))
    return sorted(threads, key=lambda item: item.updated_at, reverse=True)


@app.get("/v1/threads/{thread_id}", response_model=ThreadInfo)
def get_thread(thread_id: str) -> ThreadInfo:
    runtime = get_runtime()
    return load_thread_info(runtime, thread_id)


@app.get("/v1/threads/{thread_id}/messages", response_model=list[MessageRecord])
def get_thread_messages(thread_id: str) -> list[MessageRecord]:
    runtime = get_runtime()
    load_thread_info(runtime, thread_id)
    return list_messages(runtime, thread_id)


@app.post("/v1/threads/{thread_id}/messages", response_model=MessageResponse)
def post_thread_message(thread_id: str, request: MessageRequest) -> MessageResponse:
    runtime = get_runtime()
    info = ensure_thread(runtime, thread_id, first_message=request.message)

    user_message = MessageRecord(role="user", content=request.message, created_at=utc_now())
    append_message(runtime, thread_id, user_message)

    with THREAD_LOCK:
        result = runtime.invoke(thread_id=thread_id, message=request.message)

    reply = extract_reply(result)
    assistant_message = MessageRecord(role="assistant", content=reply, created_at=utc_now())
    append_message(runtime, thread_id, assistant_message)

    updated = info.model_copy(
        update={
            "updated_at": utc_now(),
            "title": info.title or request.message[:80],
            "last_message_preview": reply[:120] if reply else request.message[:120],
        }
    )
    save_thread_info(runtime, updated)

    return MessageResponse(
        thread_id=thread_id,
        reply=reply,
        provider=runtime.config.active_provider,
        model=runtime.config.provider.model,
    )


@app.get("/v1/tools")
def get_tools() -> dict[str, Any]:
    runtime = get_runtime()
    return {"toolkits": runtime.tool_collection.toolkits}


@app.get("/v1/files", response_model=list[WorkspaceEntry])
def list_workspace_files(path: str = "/", recursive: bool = False, max_entries: int = 200) -> list[WorkspaceEntry]:
    runtime = get_runtime()
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
def start_process(request: ProcessRequest) -> dict[str, Any]:
    runtime = get_runtime()
    try:
        return runtime.process_manager.start(request.command, cwd=request.cwd)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/processes")
def list_processes() -> list[dict[str, Any]]:
    runtime = get_runtime()
    return runtime.process_manager.list_processes()


@app.get("/v1/processes/{process_id}")
def get_process(process_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    try:
        return runtime.process_manager.get(process_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/processes/{process_id}/output")
def get_process_output(process_id: str, stream: str = "stdout", tail_lines: int = 200) -> dict[str, Any]:
    runtime = get_runtime()
    try:
        return runtime.process_manager.read_output(process_id, stream=stream, tail_lines=tail_lines)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/processes/{process_id}/stop")
def stop_process(process_id: str, force: bool = False) -> dict[str, Any]:
    runtime = get_runtime()
    try:
        return runtime.process_manager.stop(process_id, force=force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
