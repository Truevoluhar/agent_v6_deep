from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_api.workspace import WorkspaceManager


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class LiveProcess:
    process: subprocess.Popen[str]
    stdout_handle: Any
    stderr_handle: Any


class BackgroundProcessManager:
    def __init__(self, workspace: WorkspaceManager, env: dict[str, str], processes_root: Path) -> None:
        self.workspace = workspace
        self.env = env
        self.processes_dir = processes_root
        self.processes_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._live: dict[str, LiveProcess] = {}

    def start(self, command: str, cwd: str = "/") -> dict[str, Any]:
        process_id = str(uuid.uuid4())
        cwd_path = self.workspace.resolve_path(cwd)
        if not cwd_path.is_dir():
            raise NotADirectoryError(cwd)

        record_dir = self.processes_dir / process_id
        record_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = record_dir / "stdout.log"
        stderr_path = record_dir / "stderr.log"
        meta_path = record_dir / "metadata.json"

        stdout_handle = stdout_path.open("a", encoding="utf-8")
        stderr_handle = stderr_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            ["bash", "-lc", command],
            cwd=cwd_path,
            env=self.env,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            preexec_fn=os.setsid,
        )
        metadata = {
            "process_id": process_id,
            "command": command,
            "cwd": self.workspace.relative_path(cwd_path),
            "status": "running",
            "pid": process.pid,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "return_code": None,
            "stdout_path": self.workspace.relative_path(stdout_path),
            "stderr_path": self.workspace.relative_path(stderr_path),
        }
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with self._lock:
            self._live[process_id] = LiveProcess(
                process=process,
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
            )
        return metadata

    def _metadata_path(self, process_id: str) -> Path:
        return self.processes_dir / process_id / "metadata.json"

    def _load_metadata(self, process_id: str) -> dict[str, Any]:
        path = self._metadata_path(process_id)
        if not path.exists():
            raise FileNotFoundError(process_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_metadata(self, metadata: dict[str, Any]) -> None:
        path = self._metadata_path(metadata["process_id"])
        path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _sync_live_state(self, process_id: str) -> dict[str, Any]:
        metadata = self._load_metadata(process_id)
        with self._lock:
            live = self._live.get(process_id)
        if live is None:
            return metadata

        return_code = live.process.poll()
        if return_code is None:
            metadata["status"] = "running"
        else:
            metadata["status"] = "completed" if return_code == 0 else "failed"
            metadata["return_code"] = return_code
            live.stdout_handle.close()
            live.stderr_handle.close()
            with self._lock:
                self._live.pop(process_id, None)
        metadata["updated_at"] = utc_now()
        self._save_metadata(metadata)
        return metadata

    def list_processes(self) -> list[dict[str, Any]]:
        processes: list[dict[str, Any]] = []
        for path in sorted(self.processes_dir.glob("*/metadata.json")):
            process_id = path.parent.name
            processes.append(self._sync_live_state(process_id))
        return sorted(processes, key=lambda item: item["created_at"], reverse=True)

    def get(self, process_id: str) -> dict[str, Any]:
        return self._sync_live_state(process_id)

    def read_output(self, process_id: str, stream: str = "stdout", tail_lines: int = 200) -> dict[str, Any]:
        metadata = self._sync_live_state(process_id)
        if stream not in {"stdout", "stderr"}:
            raise ValueError("stream must be 'stdout' or 'stderr'")
        path_key = "stdout_path" if stream == "stdout" else "stderr_path"
        output_path = self.workspace.resolve_path(metadata[path_key])
        if not output_path.exists():
            content = ""
        else:
            lines = output_path.read_text(encoding="utf-8").splitlines()
            content = "\n".join(lines[-tail_lines:])
        return {
            "process": metadata,
            "stream": stream,
            "content": content,
        }

    def stop(self, process_id: str, force: bool = False) -> dict[str, Any]:
        metadata = self._sync_live_state(process_id)
        with self._lock:
            live = self._live.get(process_id)
        if live is None:
            return metadata

        sig = signal.SIGKILL if force else signal.SIGTERM
        os.killpg(os.getpgid(live.process.pid), sig)
        metadata["status"] = "stopped" if not force else "killed"
        metadata["updated_at"] = utc_now()
        metadata["return_code"] = live.process.wait(timeout=10)
        live.stdout_handle.close()
        live.stderr_handle.close()
        with self._lock:
            self._live.pop(process_id, None)
        self._save_metadata(metadata)
        return metadata


def run_shell_command(
    command: str,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    completed = subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "return_code": completed.returncode,
        "stdout": completed.stdout[-20_000:],
        "stderr": completed.stderr[-20_000:],
    }
