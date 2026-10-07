from __future__ import annotations

import fnmatch
import io
import os
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from shared.quota import check_quota

@dataclass(frozen=True)
class WorkspaceEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified_at: float | None = None
    exists: bool | None = None


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for relative in (
            "uploads",
            "projects",
            "analysis",
            "diagrams",
            "exports",
            ".agent",
            ".agent/home",
            ".agent/runs",
            ".agent/threads",
            ".agent/processes",
        ):
            self.resolve_path(relative).mkdir(parents=True, exist_ok=True)

    def resolve_path(self, raw_path: str) -> Path:
        normalized = PurePosixPath("/" + raw_path.lstrip("/"))
        relative = normalized.relative_to("/")
        candidate = self.root / relative
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Symbolic links are not allowed")
        candidate = candidate.resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError(f"Path escapes workspace: {raw_path}")
        return candidate

    def open_file(self, raw_path: str, flags: int, mode: int = 0o666) -> int:
        """Open a file relative to the root without following any symlink component."""
        path = self.resolve_path(raw_path)
        if path == self.root:
            raise ValueError("Expected file path")
        parts = path.relative_to(self.root).parts
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = next_fd
            return os.open(parts[-1], flags | os.O_NOFOLLOW, mode, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)

    def relative_path(self, path: Path) -> str:
        if path == self.root:
            return "/"
        return "/" + path.relative_to(self.root).as_posix()

    def list_dir(self, raw_path: str = "/", recursive: bool = False, max_entries: int = 200) -> list[dict[str, Any]]:
        target = self.resolve_path(raw_path)
        if not target.exists():
            raise FileNotFoundError(raw_path)
        if not target.is_dir():
            raise NotADirectoryError(raw_path)

        entries: list[dict[str, Any]] = []
        iterator = target.rglob("*") if recursive else target.iterdir()
        for index, child in enumerate(sorted(iterator, key=lambda item: item.as_posix().lower())):
            if index >= max_entries:
                break
            if child.is_symlink():
                continue
            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "path": self.relative_path(child),
                    "is_dir": child.is_dir(),
                    "size": None if child.is_dir() else stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
        return entries

    def read_text(
        self,
        raw_path: str,
        start_line: int = 1,
        end_line: int | None = None,
        max_chars: int = 20_000,
    ) -> str:
        path = self.resolve_path(raw_path)
        if not path.exists():
            raise FileNotFoundError(raw_path)
        if path.is_dir():
            raise IsADirectoryError(raw_path)

        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        start = max(start_line - 1, 0)
        stop = len(lines) if end_line is None else max(end_line, start_line)
        rendered = "\n".join(lines[start:stop])
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars] + "\n...[truncated]"
        return rendered

    def write_text(self, raw_path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.is_dir():
            raise IsADirectoryError(raw_path)
        if path.exists() and not overwrite:
            raise FileExistsError(raw_path)
        check_quota(self.root, len(content.encode("utf-8")), path.stat().st_size if path.is_file() else 0)
        path.write_text(content, encoding="utf-8")
        return self.stat_path(raw_path)

    def append_text(self, raw_path: str, content: str) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        check_quota(self.root, (path.stat().st_size if path.is_file() else 0) + len(content.encode("utf-8")), path.stat().st_size if path.is_file() else 0)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return self.stat_path(raw_path)

    def make_directory(self, raw_path: str) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        path.mkdir(parents=True, exist_ok=True)
        return self.stat_path(raw_path)

    def directory_zip(self, raw_path: str) -> tuple[str, bytes]:
        target = self.resolve_path(raw_path)
        if not target.exists():
            raise FileNotFoundError(raw_path)
        if not target.is_dir():
            raise NotADirectoryError(raw_path)

        archive_root = target.name or "workspace"
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{archive_root}/", "")
            for child in sorted(target.rglob("*"), key=lambda item: item.as_posix().lower()):
                if child.is_symlink():
                    continue
                try:
                    resolved_child = self.resolve_path(self.relative_path(child))
                except ValueError:
                    continue

                archive_path = (PurePosixPath(archive_root) / child.relative_to(target)).as_posix()
                if child.is_dir():
                    archive.writestr(f"{archive_path.rstrip('/')}/", "")
                elif child.is_file():
                    archive.write(resolved_child, archive_path)

        return f"{archive_root}.zip", archive_buffer.getvalue()

    def delete_path(self, raw_path: str, recursive: bool = False) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        if path == self.root or path == self.root / ".agent" or (self.root / ".agent") in path.parents:
            raise ValueError("Protected workspace path")
        if not path.exists():
            raise FileNotFoundError(raw_path)
        info = self.stat_path(raw_path)
        if path.is_dir():
            if not recursive:
                path.rmdir()
            else:
                shutil.rmtree(path)
        else:
            path.unlink()
        return {"deleted": info}

    def copy_path(self, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src = self.resolve_path(source)
        dst = self.resolve_path(destination)
        if not src.exists():
            raise FileNotFoundError(source)
        if dst.exists() and not overwrite:
            raise FileExistsError(destination)
        if src.is_dir() and any(item.is_symlink() for item in src.rglob("*")):
            raise ValueError("Symbolic links are not allowed")
        source_size = sum(item.stat().st_size for item in src.rglob("*") if item.is_file()) if src.is_dir() else src.stat().st_size
        replaced = sum(item.stat().st_size for item in dst.rglob("*") if item.is_file() and not item.is_symlink()) if dst.is_dir() else (dst.stat().st_size if dst.is_file() else 0)
        check_quota(self.root, source_size, replaced)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return self.stat_path(destination)

    def move_path(self, source: str, destination: str, overwrite: bool = False) -> dict[str, Any]:
        src = self.resolve_path(source)
        dst = self.resolve_path(destination)
        if not src.exists():
            raise FileNotFoundError(source)
        if dst.exists():
            if not overwrite:
                raise FileExistsError(destination)
            if dst.is_dir():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return self.stat_path(destination)

    def glob_paths(self, pattern: str, base_path: str = "/", max_results: int = 200) -> list[str]:
        base = self.resolve_path(base_path)
        if not base.exists():
            raise FileNotFoundError(base_path)
        matches: list[str] = []
        for child in base.rglob("*"):
            if child.is_symlink():
                continue
            relative = child.relative_to(base).as_posix()
            if fnmatch.fnmatch(relative, pattern):
                matches.append(self.relative_path(child))
                if len(matches) >= max_results:
                    break
        return matches

    def search_text(
        self,
        pattern: str,
        base_path: str = "/",
        glob_pattern: str = "*",
        case_sensitive: bool = False,
        max_matches: int = 200,
    ) -> list[dict[str, Any]]:
        base = self.resolve_path(base_path)
        if not base.exists():
            raise FileNotFoundError(base_path)
        needle = pattern if case_sensitive else pattern.lower()
        matches: list[dict[str, Any]] = []
        for child in base.rglob("*"):
            if child.is_symlink() or not child.is_file():
                continue
            relative = child.relative_to(base).as_posix()
            if not fnmatch.fnmatch(relative, glob_pattern):
                continue
            try:
                text = child.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(
                        {
                            "path": self.relative_path(child),
                            "line_number": line_number,
                            "line": line,
                        }
                    )
                    if len(matches) >= max_matches:
                        return matches
        return matches

    def read_json(self, raw_path: str) -> Any:
        path = self.resolve_path(raw_path)
        if not path.exists():
            raise FileNotFoundError(raw_path)
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, raw_path: str, payload: Any, overwrite: bool = True) -> dict[str, Any]:
        text = json.dumps(payload, indent=2, sort_keys=True)
        return self.write_text(raw_path, text + "\n", overwrite=overwrite)

    def stat_path(self, raw_path: str) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        if not path.exists():
            raise FileNotFoundError(raw_path)
        stat = path.stat()
        return {
            "name": path.name or "/",
            "path": self.relative_path(path),
            "is_dir": path.is_dir(),
            "size": None if path.is_dir() else stat.st_size,
            "modified_at": stat.st_mtime,
            "exists": True,
        }
