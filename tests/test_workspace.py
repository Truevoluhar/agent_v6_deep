from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from agent_api.workspace import WorkspaceManager


def test_workspace_manager_blocks_escape(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure_layout()
    with pytest.raises(ValueError):
        workspace.resolve_path("../outside.txt")


def test_workspace_manager_file_operations(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure_layout()

    workspace.write_text("/analysis/report.txt", "line1\nline2\n")
    assert workspace.read_text("/analysis/report.txt") == "line1\nline2"

    workspace.append_text("/analysis/report.txt", "line3\n")
    assert "line3" in workspace.read_text("/analysis/report.txt")

    workspace.write_json("/analysis/data.json", {"ok": True})
    assert workspace.read_json("/analysis/data.json") == {"ok": True}

    files = workspace.list_dir("/analysis")
    assert {entry["name"] for entry in files} == {"data.json", "report.txt"}

    matches = workspace.search_text("line2", base_path="/analysis", glob_pattern="*.txt")
    assert matches[0]["line_number"] == 2

    copied = workspace.copy_path("/analysis/report.txt", "/exports/report-copy.txt")
    assert copied["path"] == "/exports/report-copy.txt"

    moved = workspace.move_path("/exports/report-copy.txt", "/exports/final.txt")
    assert moved["path"] == "/exports/final.txt"

    deleted = workspace.delete_path("/exports/final.txt")
    assert deleted["deleted"]["path"] == "/exports/final.txt"


def test_workspace_manager_recursive_directory_delete(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure_layout()

    workspace.write_text("/analysis/nested/deeper/report.txt", "hello\n")

    with pytest.raises(OSError):
        workspace.delete_path("/analysis/nested")

    deleted = workspace.delete_path("/analysis/nested", recursive=True)
    assert deleted["deleted"]["path"] == "/analysis/nested"
    assert not workspace.resolve_path("/analysis/nested").exists()


def test_workspace_manager_archives_directory_tree(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path)
    workspace.ensure_layout()
    workspace.write_text("/projects/sample/nested/report.txt", "archive me")
    workspace.make_directory("/projects/sample/empty")

    filename, content = workspace.directory_zip("/projects/sample")

    assert filename == "sample.zip"
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert set(archive.namelist()) == {
            "sample/",
            "sample/empty/",
            "sample/nested/",
            "sample/nested/report.txt",
        }
        assert archive.read("sample/nested/report.txt") == b"archive me"


def test_copy_rejects_nested_symlink(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path / 'workspace')
    workspace.ensure_layout()
    source = workspace.resolve_path('/projects/source')
    source.mkdir()
    (source / 'outside').symlink_to(tmp_path)
    try:
        workspace.copy_path('/projects/source', '/projects/copied')
    except ValueError as exc:
        assert 'Symbolic links' in str(exc)
    else:
        raise AssertionError('Nested symlink was copied')
