from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


def canonical_uuid(value: str | UUID) -> str:
    return str(UUID(str(value)))


@dataclass(frozen=True)
class UserPaths:
    root: Path
    workspace: Path
    sessions: Path
    memory: Path
    resources: Path
    runs: Path

    @classmethod
    def for_user(cls, user_id: str | UUID) -> 'UserPaths':
        root = Path(os.environ.get('USER_DATA_ROOT', str(Path(os.environ.get('AGENT_DATA_ROOT', '/data')) / 'users'))).resolve() / canonical_uuid(user_id)
        return cls(root, root / 'workspace', root / 'sessions', root / 'memory', root / 'resources', root / 'runs')
