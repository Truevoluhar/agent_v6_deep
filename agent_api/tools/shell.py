from __future__ import annotations

import json
from typing import Any

from agent_api.processes import run_shell_command
from agent_api.tools.context import ToolContext
from agent_api.tools.registry import register_toolkit


def _render(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _safe_call(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return _render({"error": str(exc), "error_type": type(exc).__name__})


@register_toolkit(
    "shell",
    "Foreground and background shell execution with persistent process logs.",
)
def build_shell_tools(context: ToolContext) -> list[Any]:
    from langchain_core.tools import tool

    workspace = context.workspace
    process_manager = context.process_manager

    @tool(parse_docstring=True)
    def run_shell(command: str, cwd: str = "/", timeout_seconds: int | None = None) -> str:
        """Run a shell command in the workspace and wait for completion.

        Args:
            command: Shell command to execute with bash -lc.
            cwd: Working directory relative to the workspace root.
            timeout_seconds: Optional override for the shell timeout.
        """

        def _run() -> str:
            cwd_path = workspace.resolve_path(cwd)
            payload = run_shell_command(
                command=command,
                cwd=cwd_path,
                env=context.shell_env,
                timeout_seconds=timeout_seconds or context.config.agent.shell_timeout_seconds,
            )
            payload["cwd"] = workspace.relative_path(cwd_path)
            return _render(payload)

        return _safe_call(_run)

    @tool(parse_docstring=True)
    def start_background_process(command: str, cwd: str = "/") -> str:
        """Start a long-running shell command and return a process id.

        Args:
            command: Shell command to execute with bash -lc.
            cwd: Working directory relative to the workspace root.
        """

        return _safe_call(lambda: _render(process_manager.start(command=command, cwd=cwd)))

    @tool(parse_docstring=True)
    def list_background_processes() -> str:
        """List known background processes and their current status."""

        return _safe_call(lambda: _render(process_manager.list_processes()))

    @tool(parse_docstring=True)
    def get_background_process(process_id: str) -> str:
        """Get metadata for a background process.

        Args:
            process_id: Process id returned by start_background_process.
        """

        return _safe_call(lambda: _render(process_manager.get(process_id)))

    @tool(parse_docstring=True)
    def read_background_output(process_id: str, stream: str = "stdout", tail_lines: int = 200) -> str:
        """Read recent output from a background process log.

        Args:
            process_id: Process id returned by start_background_process.
            stream: Either stdout or stderr.
            tail_lines: Number of trailing log lines to return.
        """

        return _safe_call(lambda: _render(process_manager.read_output(process_id, stream=stream, tail_lines=tail_lines)))

    @tool(parse_docstring=True)
    def stop_background_process(process_id: str, force: bool = False) -> str:
        """Stop a background process.

        Args:
            process_id: Process id returned by start_background_process.
            force: When true, send SIGKILL instead of SIGTERM.
        """

        return _safe_call(lambda: _render(process_manager.stop(process_id, force=force)))

    return [
        run_shell,
        start_background_process,
        list_background_processes,
        get_background_process,
        read_background_output,
        stop_background_process,
    ]
