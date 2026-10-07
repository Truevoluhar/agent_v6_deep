from __future__ import annotations

import os
from pathlib import Path


def quota_bytes() -> int:
    return int(os.environ.get('WORKSPACE_QUOTA_BYTES', str(1024 * 1024 * 1024)))


def used_bytes(root: Path) -> int:
    total = 0
    if root.exists():
        for path in root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    return total


def check_quota(root: Path, new_bytes: int, replaced_bytes: int = 0) -> None:
    if used_bytes(root) - replaced_bytes + new_bytes > quota_bytes():
        raise ValueError('Workspace quota exceeded')
