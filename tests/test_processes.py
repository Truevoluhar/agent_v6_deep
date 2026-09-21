from __future__ import annotations

import time
from pathlib import Path

from agent_api.processes import BackgroundProcessManager, run_shell_command
from agent_api.workspace import WorkspaceManager


def test_run_shell_command(tmp_path: Path) -> None:
    payload = run_shell_command(
        command="printf 'hello world'",
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout_seconds=5,
    )
    assert payload["return_code"] == 0
    assert payload["stdout"] == "hello world"


def test_background_process_lifecycle(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure_layout()
    manager = BackgroundProcessManager(
        workspace=workspace,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        processes_root=tmp_path / "runs" / "processes",
    )

    process = manager.start("printf 'background ok\\n'", cwd="/")
    process_id = process["process_id"]

    status = manager.get(process_id)
    for _ in range(10):
        if status["status"] != "running":
            break
        time.sleep(0.05)
        status = manager.get(process_id)

    output = manager.read_output(process_id)
    assert status["status"] in {"completed", "failed"}
    assert "background ok" in output["content"]
