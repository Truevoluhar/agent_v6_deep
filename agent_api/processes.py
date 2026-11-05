from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from agent_api.shell_sandbox import sandboxed_shell_argv
from agent_api.workspace import WorkspaceManager


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def build_shell_environment(execution_root: Path, base_env: dict[str, str]) -> dict[str, str]:
    root = execution_root
    home = root / ".home"
    temp = root / ".tmp"
    runtime = root / ".run"
    cache = root / ".cache"
    local = root / ".local"
    for path in (home, temp, runtime, cache, local):
        path.mkdir(parents=True, exist_ok=True)
    env = dict(base_env)
    env.update(
        {
            "PATH": os.pathsep.join(
                [str(local / "bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
            ),
            "HOME": str(home),
            "TMPDIR": str(temp),
            "TMP": str(temp),
            "TEMP": str(temp),
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_CACHE_HOME": str(cache),
            "PIP_CACHE_DIR": str(cache / "pip"),
            "PIP_USER": "1",
            "npm_config_cache": str(cache / "npm"),
            "npm_config_prefix": str(local),
            "PYTHONUSERBASE": str(local),
            "GOPATH": str(root / ".go"),
            "CARGO_HOME": str(root / ".cargo"),
        }
    )
    return env


def _sandbox_identity_kwargs() -> dict[str, Any]:
    """Run bubblewrap as an unprivileged uid when the API itself runs as root."""
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        return {}
    uid = int(os.environ.get("AGENT_SHELL_UID", "10001"))
    gid = int(os.environ.get("AGENT_SHELL_GID", "10001"))
    if uid == 0 or gid == 0:
        raise RuntimeError("Linux shell sandbox uid/gid must be unprivileged")
    return {"user": uid, "group": gid, "extra_groups": []}


def _make_execution_root_writable_by_sandbox_user(root: Path) -> None:
    """Allow the unprivileged sandbox uid to use the dedicated execution tree."""
    root.chmod(0o777)
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if not path.is_symlink():
                path.chmod(0o777)
        for name in files:
            path = current_path / name
            if path.is_symlink():
                continue
            mode = path.stat(follow_symlinks=False).st_mode
            path.chmod((mode & 0o111) | 0o666)


@dataclass
class LiveProcess:
    process: subprocess.Popen[str]
    stdout_handle: Any
    stderr_handle: Any
    output_threads: tuple[threading.Thread, threading.Thread]


def _stream_output(source: Any, destination: Any) -> None:
    try:
        for line in iter(source.readline, ""):
            destination.write(line)
            destination.flush()
    finally:
        source.close()


class BackgroundProcessManager:
    def __init__(
        self,
        workspace: WorkspaceManager,
        env: dict[str, str],
        processes_root: Path,
        owner_user_id: uuid.UUID | None = None,
        execution_root: Path | None = None,
    ) -> None:
        self.owner_user_id = owner_user_id
        self.workspace = workspace
        self.env = env
        expected_execution_root = workspace.resolve_path("/shell_executions").resolve()
        self.execution_root = (execution_root or expected_execution_root).resolve()
        if self.execution_root != expected_execution_root:
            raise ValueError("Shell execution root must be /shell_executions in this workspace")
        self.execution_root.mkdir(parents=True, exist_ok=True)
        self._prepare_execution_environment()
        if sys.platform.startswith("linux"):
            _make_execution_root_writable_by_sandbox_user(self.execution_root)
        self.processes_dir = processes_root
        self.processes_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._live: dict[str, LiveProcess] = {}

    def _prepare_execution_environment(self) -> dict[str, str]:
        self.execution_env = build_shell_environment(self.execution_root, self.env)
        return self.execution_env

    def resolve_execution_cwd(self, cwd: str = "/") -> Path:
        raw = str(cwd)
        if "\x00" in raw:
            raise ValueError("cwd contains a null byte")
        relative = PurePosixPath(raw.lstrip("/"))
        if any(part == ".." for part in relative.parts):
            raise ValueError("cwd must stay inside /shell_executions")

        candidate = self.execution_root
        for part in relative.parts:
            if part in {"", "."}:
                continue
            candidate = candidate / part
            if candidate.is_symlink():
                raise ValueError("Symbolic links are not allowed in shell cwd")
        candidate = candidate.resolve(strict=False)
        if candidate != self.execution_root and self.execution_root not in candidate.parents:
            raise ValueError("cwd must stay inside /shell_executions")
        if not candidate.is_dir():
            raise NotADirectoryError(raw)
        return candidate

    def execution_relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        if resolved == self.execution_root:
            return "/"
        if self.execution_root not in resolved.parents:
            raise ValueError("Shell path is outside /shell_executions")
        return "/" + resolved.relative_to(self.execution_root).as_posix()

    def start(self, command: str, cwd: str = "/") -> dict[str, Any]:
        process_id = str(uuid.uuid4())
        cwd_path = self.resolve_execution_cwd(cwd)

        record_dir = self.processes_dir / process_id
        record_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = record_dir / "stdout.log"
        stderr_path = record_dir / "stderr.log"
        meta_path = record_dir / "metadata.json"

        stdout_handle = stdout_path.open("a", encoding="utf-8")
        stderr_handle = stderr_path.open("a", encoding="utf-8")
        execution_env = self._prepare_execution_environment()
        try:
            argv = sandboxed_shell_argv(
                command,
                self.execution_root,
                cwd=cwd_path,
                env=execution_env,
            )
            process = subprocess.Popen(
                argv,
                cwd=cwd_path,
                env=execution_env,
                text=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                **_sandbox_identity_kwargs(),
            )
        except Exception:
            stdout_handle.close()
            stderr_handle.close()
            raise
        output_threads = (
            threading.Thread(
                target=_stream_output,
                args=(process.stdout, stdout_handle),
                daemon=True,
            ),
            threading.Thread(
                target=_stream_output,
                args=(process.stderr, stderr_handle),
                daemon=True,
            ),
        )
        for thread in output_threads:
            thread.start()
        metadata = {
            "process_id": process_id,
            "owner_user_id": str(self.owner_user_id) if self.owner_user_id else None,
            "command": command,
            "cwd": self.execution_relative_path(cwd_path),
            "status": "running",
            "pid": process.pid,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "return_code": None,
            "stdout_path": "stdout.log",
            "stderr_path": "stderr.log",
        }
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with self._lock:
            self._live[process_id] = LiveProcess(
                process=process,
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
                output_threads=output_threads,
            )
        return metadata

    def _metadata_path(self, process_id: str) -> Path:
        return self.processes_dir / str(uuid.UUID(process_id)) / "metadata.json"

    def _load_metadata(self, process_id: str) -> dict[str, Any]:
        path = self._metadata_path(process_id)
        if not path.exists():
            raise FileNotFoundError(process_id)
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if self.owner_user_id is not None and metadata.get("owner_user_id") != str(self.owner_user_id):
            raise FileNotFoundError(process_id)
        return metadata

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
            for thread in live.output_threads:
                thread.join(timeout=0.1)
            if any(thread.is_alive() for thread in live.output_threads):
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
        output_path = self._metadata_path(process_id).parent / metadata[path_key]
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
        try:
            os.killpg(live.process.pid, sig)
        except ProcessLookupError:
            pass
        metadata["status"] = "stopped" if not force else "killed"
        metadata["updated_at"] = utc_now()
        metadata["return_code"] = live.process.wait(timeout=10)
        for thread in live.output_threads:
            thread.join(timeout=2)
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
    execution_root: Path,
) -> dict[str, Any]:
    root = execution_root.resolve(strict=True)
    cwd_path = cwd.resolve(strict=True)
    if cwd_path != root and root not in cwd_path.parents:
        raise ValueError("cwd must stay inside /shell_executions")
    current = root
    for part in cwd_path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symbolic links are not allowed in shell cwd")
    if not cwd_path.is_dir():
        raise NotADirectoryError(cwd_path)

    shell_env = build_shell_environment(root, env)
    process = subprocess.Popen(
        sandboxed_shell_argv(command, root, cwd=cwd_path, env=shell_env),
        cwd=cwd_path,
        env=shell_env,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        **_sandbox_identity_kwargs(),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        stderr = f"{stderr}\nCommand timed out after {timeout_seconds} seconds."
    return {
        "command": command,
        "cwd": str(cwd_path),
        "return_code": process.returncode,
        "stdout": stdout[-20_000:],
        "stderr": stderr[-20_000:],
    }
