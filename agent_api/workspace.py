from __future__ import annotations

import fnmatch
import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

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
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def resolve_path(self, raw_path: str) -> Path:
        normalized = PurePosixPath("/" + raw_path.lstrip("/"))
        candidate = (self.root / normalized.relative_to("/")).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError(f"Path escapes workspace: {raw_path}")
        return candidate

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
        path.write_text(content, encoding="utf-8")
        return self.stat_path(raw_path)

    def append_text(self, raw_path: str, content: str) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return self.stat_path(raw_path)

    def make_directory(self, raw_path: str) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
        path.mkdir(parents=True, exist_ok=True)
        return self.stat_path(raw_path)

    def delete_path(self, raw_path: str, recursive: bool = False) -> dict[str, Any]:
        path = self.resolve_path(raw_path)
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
            if not child.is_file():
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
