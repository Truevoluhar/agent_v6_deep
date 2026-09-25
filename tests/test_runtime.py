from __future__ import annotations

from pathlib import Path

from agent_api.runtime import _seed_skills
from agent_api.workspace import WorkspaceManager


def test_seed_skills_copies_bundled_skills_into_workspace(tmp_path: Path) -> None:
    source_root = tmp_path / "app-skills"
    source_skill = source_root / "demo-skill"
    source_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill\n---\n",
        encoding="utf-8",
    )

    workspace = WorkspaceManager(tmp_path / "workspace")
    workspace.ensure_layout()

    _seed_skills(workspace, "/.agent/skills", source_root=source_root)

    copied_skill = workspace.resolve_path("/.agent/skills/demo-skill/SKILL.md")
    assert copied_skill.exists()
    assert "demo-skill" in copied_skill.read_text(encoding="utf-8")
