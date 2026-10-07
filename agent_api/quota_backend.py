from __future__ import annotations

from pathlib import Path
from deepagents.backends import FilesystemBackend
from shared.quota import check_quota


class QuotaFilesystemBackend(FilesystemBackend):
    def write(self, file_path: str, content: str):
        path = self._resolve_path(file_path)
        previous = path.stat().st_size if path.is_file() else 0
        check_quota(self.cwd, len(content.encode('utf-8')), previous)
        return super().write(file_path, content)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False):
        path = self._resolve_path(file_path)
        if path.is_file():
            original = path.read_text(encoding='utf-8')
            count = original.count(old_string) if replace_all else min(original.count(old_string), 1)
            projected = original.replace(old_string, new_string, -1 if replace_all else 1)
            if count:
                check_quota(self.cwd, len(projected.encode('utf-8')), path.stat().st_size)
        return super().edit(file_path, old_string, new_string, replace_all=replace_all)

    def upload_files(self, files: list[tuple[str, bytes]]):
        replaced = 0
        for name, _ in files:
            path = self._resolve_path(name)
            if path.is_file():
                replaced += path.stat().st_size
        check_quota(self.cwd, sum(len(content) for _, content in files), replaced)
        return super().upload_files(files)
