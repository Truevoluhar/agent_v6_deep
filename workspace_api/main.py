from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from agent_api.workspace import WorkspaceEntry, WorkspaceManager

WORKSPACE_ROOT = Path(
    os.environ.get(
        "WORKSPACE_ROOT",
        str(Path(os.environ.get("AGENT_DATA_ROOT", "/data")) / "agent_workspace"),
    )
).resolve()
WORKSPACE = WorkspaceManager(WORKSPACE_ROOT)

app = FastAPI(title="deepagents-platform workspace-api", version="0.1.0")


def ensure_workspace() -> None:
    WORKSPACE.ensure_layout()


@app.on_event("startup")
def startup() -> None:
    ensure_workspace()


@app.get("/health")
def health() -> dict[str, str]:
    ensure_workspace()
    return {"status": "ok"}


@app.get("/v1/files", response_model=list[WorkspaceEntry])
def list_files(path: str = "/", recursive: bool = False, max_entries: int = 200) -> list[WorkspaceEntry]:
    ensure_workspace()
    try:
        return [
            WorkspaceEntry(**entry)
            for entry in WORKSPACE.list_dir(path, recursive=recursive, max_entries=max_entries)
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Path not found.") from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail="Path is not a directory.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc


@app.post("/v1/directories", response_model=WorkspaceEntry)
def create_directory(path: str) -> WorkspaceEntry:
    ensure_workspace()
    try:
        target = WORKSPACE.resolve_path(path)
        if target.exists():
            raise HTTPException(status_code=409, detail="Directory already exists.")
        return WorkspaceEntry(**WORKSPACE.make_directory(path))
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
) -> WorkspaceEntry:
    ensure_workspace()
    try:
        target_dir = WORKSPACE.resolve_path(destination)
        target_dir.mkdir(parents=True, exist_ok=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination must be a directory.")

    filename = Path(file.filename or "upload.bin").name
    output_path = target_dir / filename
    with output_path.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            handle.write(chunk)

    return WorkspaceEntry(
        name=output_path.name,
        path=WORKSPACE.relative_path(output_path),
        is_dir=False,
        size=output_path.stat().st_size,
    )


@app.get("/v1/files/{file_path:path}")
def download_file(file_path: str) -> FileResponse:
    ensure_workspace()
    try:
        target = WORKSPACE.resolve_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Directories cannot be downloaded.")
    return FileResponse(target)


@app.get("/v1/archives")
def download_directory_archive(path: str = "/") -> Response:
    ensure_workspace()
    try:
        filename, content = WORKSPACE.directory_zip(path)
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
def delete_file(file_path: str, recursive: bool = False) -> dict[str, object]:
    ensure_workspace()
    try:
        return WORKSPACE.delete_path(file_path, recursive=recursive)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid workspace path.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.")
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Directory deletion requires recursive=true when the directory is not empty.",
        ) from exc
