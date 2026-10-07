from __future__ import annotations

import pytest
from pathlib import Path

from agent_api.processes import BackgroundProcessManager, run_shell_command
from agent_api.workspace import WorkspaceManager


def test_shell_execution_is_disabled(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="disabled"):
        run_shell_command("echo hello", tmp_path, {"PATH": "/usr/bin:/bin"}, 5)

    workspace = WorkspaceManager(tmp_path)
    workspace.ensure_layout()
    manager = BackgroundProcessManager(
        workspace=workspace,
        env={"PATH": "/usr/bin:/bin"},
        processes_root=tmp_path / "runs" / "processes",
    )
    with pytest.raises(PermissionError, match="disabled"):
        manager.start("echo hello")
