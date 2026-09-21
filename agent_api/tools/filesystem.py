from __future__ import annotations

import json
from typing import Any

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
    "filesystem",
    "Expanded workspace filesystem operations beyond the DeepAgents built-ins.",
)
def build_filesystem_tools(context: ToolContext) -> list[Any]:
    from langchain_core.tools import tool

    workspace = context.workspace

    @tool(parse_docstring=True)
    def path_info(path: str = "/") -> str:
        """Return metadata for a workspace path.

        Args:
            path: Path relative to the workspace root.
        """

        return _safe_call(lambda: _render(workspace.stat_path(path)))

    @tool(parse_docstring=True)
    def list_directory(path: str = "/", recursive: bool = False, max_entries: int = 200) -> str:
        """List files and directories in the workspace.

        Args:
            path: Directory path relative to the workspace root.
            recursive: When true, include nested files and directories.
            max_entries: Maximum number of entries to return.
        """

        return _safe_call(lambda: _render(workspace.list_dir(path, recursive=recursive, max_entries=max_entries)))

    @tool(parse_docstring=True)
    def read_text_file(path: str, start_line: int = 1, end_line: int | None = None, max_chars: int = 20000) -> str:
        """Read text from a file in the workspace.

        Args:
            path: File path relative to the workspace root.
            start_line: First line number to include.
            end_line: Last line number to include. Omit to read to the end.
            max_chars: Maximum characters to return.
        """

        return _safe_call(
            lambda: workspace.read_text(path, start_line=start_line, end_line=end_line, max_chars=max_chars)
        )

    @tool(parse_docstring=True)
    def write_text_file(path: str, content: str, overwrite: bool = True) -> str:
        """Write a UTF-8 text file inside the workspace.

        Args:
            path: File path relative to the workspace root.
            content: Text content to write.
            overwrite: Whether an existing file may be replaced.
        """

        return _safe_call(lambda: _render(workspace.write_text(path, content, overwrite=overwrite)))

    @tool(parse_docstring=True)
    def append_text_file(path: str, content: str) -> str:
        """Append text to an existing workspace file or create it if needed.

        Args:
            path: File path relative to the workspace root.
            content: Text content to append.
        """

        return _safe_call(lambda: _render(workspace.append_text(path, content)))

    @tool(parse_docstring=True)
    def make_directory(path: str) -> str:
        """Create a directory inside the workspace.

        Args:
            path: Directory path relative to the workspace root.
        """

        return _safe_call(lambda: _render(workspace.make_directory(path)))

    @tool(parse_docstring=True)
    def delete_path(path: str, recursive: bool = False) -> str:
        """Delete a file or directory in the workspace.

        Args:
            path: Path relative to the workspace root.
            recursive: Required for deleting non-empty directories.
        """

        return _safe_call(lambda: _render(workspace.delete_path(path, recursive=recursive)))

    @tool(parse_docstring=True)
    def copy_path(source: str, destination: str, overwrite: bool = False) -> str:
        """Copy a file or directory to a new workspace path.

        Args:
            source: Existing workspace path.
            destination: New workspace path.
            overwrite: Whether an existing destination may be replaced.
        """

        return _safe_call(lambda: _render(workspace.copy_path(source, destination, overwrite=overwrite)))

    @tool(parse_docstring=True)
    def move_path(source: str, destination: str, overwrite: bool = False) -> str:
        """Move or rename a file or directory in the workspace.

        Args:
            source: Existing workspace path.
            destination: New workspace path.
            overwrite: Whether an existing destination may be replaced.
        """

        return _safe_call(lambda: _render(workspace.move_path(source, destination, overwrite=overwrite)))

    @tool(parse_docstring=True)
    def glob_search(pattern: str, base_path: str = "/", max_results: int = 200) -> str:
        """Find paths matching a glob pattern.

        Args:
            pattern: Glob pattern relative to the chosen base path.
            base_path: Directory path relative to the workspace root.
            max_results: Maximum number of matches to return.
        """

        return _safe_call(lambda: _render(workspace.glob_paths(pattern, base_path=base_path, max_results=max_results)))

    @tool(parse_docstring=True)
    def grep_search(
        pattern: str,
        base_path: str = "/",
        glob_pattern: str = "*",
        case_sensitive: bool = False,
        max_matches: int = 200,
    ) -> str:
        """Search for text across workspace files.

        Args:
            pattern: Text to search for.
            base_path: Directory path relative to the workspace root.
            glob_pattern: File glob filter relative to the base path.
            case_sensitive: Whether matching should preserve case.
            max_matches: Maximum number of line matches to return.
        """

        return _safe_call(
            lambda: _render(
                workspace.search_text(
                    pattern,
                    base_path=base_path,
                    glob_pattern=glob_pattern,
                    case_sensitive=case_sensitive,
                    max_matches=max_matches,
                )
            )
        )

    @tool(parse_docstring=True)
    def read_json_file(path: str) -> str:
        """Read a JSON file and return formatted JSON text.

        Args:
            path: JSON file path relative to the workspace root.
        """

        return _safe_call(lambda: _render(workspace.read_json(path)))

    @tool(parse_docstring=True)
    def write_json_file(path: str, json_text: str, overwrite: bool = True) -> str:
        """Write a JSON file from a raw JSON string.

        Args:
            path: JSON file path relative to the workspace root.
            json_text: Valid JSON document text.
            overwrite: Whether an existing file may be replaced.
        """

        return _safe_call(
            lambda: _render(workspace.write_json(path, json.loads(json_text), overwrite=overwrite))
        )

    return [
        path_info,
        list_directory,
        read_text_file,
        write_text_file,
        append_text_file,
        make_directory,
        delete_path,
        copy_path,
        move_path,
        glob_search,
        grep_search,
        read_json_file,
        write_json_file,
    ]
