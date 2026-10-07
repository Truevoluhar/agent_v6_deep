from __future__ import annotations

import os
import mimetypes
from uuid import uuid4
from shared.quota import quota_bytes, used_bytes
from pathlib import Path
from urllib.parse import quote
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from shared.auth.dependencies import require_user
from shared.auth.models import CurrentUser
from shared.auth.repository import AuthRepository
from shared.auth.providers import make_provider
from shared.user_paths import UserPaths
from agent_api.workspace import WorkspaceEntry, WorkspaceManager


def workspace_for(user: CurrentUser) -> WorkspaceManager:
    workspace = WorkspaceManager(UserPaths.for_user(user.user_id).workspace)
    workspace.ensure_layout()
    return workspace

app = FastAPI(title="deepagents-platform workspace-api", version="0.1.0")



@app.middleware("http")
async def no_store_private(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/v1/") or request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.on_event("startup")
def startup() -> None:
    repository = AuthRepository()
    repository.initialize()
    make_provider(repository)
    app.state.auth_repository = repository


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/files", response_model=list[WorkspaceEntry])
def list_files(path: str = "/", recursive: bool = False, max_entries: int = 200, user: CurrentUser = Depends(require_user)) -> list[WorkspaceEntry]:
    try:
        return [
            WorkspaceEntry(**entry)
            for entry in workspace_for(user).list_dir(path, recursive=recursive, max_entries=max_entries)
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Path not found.") from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail="Path is not a directory.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc


@app.post("/v1/directories", response_model=WorkspaceEntry)
def create_directory(path: str, user: CurrentUser = Depends(require_user)) -> WorkspaceEntry:
    try:
        target = workspace_for(user).resolve_path(path)
        if target.exists():
            raise HTTPException(status_code=409, detail="Directory already exists.")
        return WorkspaceEntry(**workspace_for(user).make_directory(path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Directory could not be created.") from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail="Parent path is not a directory.") from exc


@app.post("/v1/files", response_model=WorkspaceEntry)
async def upload_file(
    file: UploadFile = File(...),
    destination: str = Form("uploads"),
    user: CurrentUser = Depends(require_user),
) -> WorkspaceEntry:
    try:
        target_dir = workspace_for(user).resolve_path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination must be a directory.")

    filename = Path(file.filename or "upload.bin").name
    if filename in {".", ".."}:
        raise HTTPException(400, "Invalid filename")
    try:
        output_path = workspace_for(user).resolve_path(str(Path(destination) / filename))
    except ValueError as exc:
        raise HTTPException(400, "Invalid workspace path") from exc
    workspace = workspace_for(user)
    existing_size = output_path.stat().st_size if output_path.is_file() else 0
    baseline = used_bytes(workspace.root)
    temporary_name = f".upload-{uuid4()}"
    temporary_path = target_dir / temporary_name
    try:
        fd = workspace.open_file(str(Path(destination) / temporary_name), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        total = 0
        with os.fdopen(fd, "wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if baseline - existing_size + total > quota_bytes():
                    raise HTTPException(413, "Workspace quota exceeded")
                handle.write(chunk)
        workspace.resolve_path(str(Path(destination) / filename))
        os.replace(temporary_path, output_path)
    except OSError as exc:
        raise HTTPException(400, "Invalid upload target") from exc
    finally:
        temporary_path.unlink(missing_ok=True)

    return WorkspaceEntry(
        name=output_path.name,
        path=workspace_for(user).relative_path(output_path),
        is_dir=False,
        size=output_path.stat().st_size,
    )


@app.get("/v1/files/{file_path:path}")
def download_file(file_path: str, user: CurrentUser = Depends(require_user)) -> StreamingResponse:
    try:
        target = workspace_for(user).resolve_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Directories cannot be downloaded.")
    try:
        fd = workspace_for(user).open_file(file_path, os.O_RDONLY)
    except OSError as exc:
        raise HTTPException(400, "Invalid file path") from exc
    def chunks():
        with os.fdopen(fd, "rb") as handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk
    return StreamingResponse(chunks(), media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")


@app.get("/v1/archives")
def download_directory_archive(path: str = "/", user: CurrentUser = Depends(require_user)) -> Response:
    try:
        filename, content = workspace_for(user).directory_zip(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Directory not found.") from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail="Path is not a directory.") from exc

    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@app.delete("/v1/files/{file_path:path}")
def delete_file(file_path: str, recursive: bool = False, user: CurrentUser = Depends(require_user)) -> dict[str, object]:
    try:
        return workspace_for(user).delete_path(file_path, recursive=recursive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.")
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Directory deletion requires recursive=true when the directory is not empty.",
        ) from exc
