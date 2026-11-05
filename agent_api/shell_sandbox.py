from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _macos_profile(execution_root: Path) -> str:
    def quote(path: str) -> str:
        return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'

    readonly_paths = (
        "/usr",
        "/bin",
        "/sbin",
        "/System",
        "/Library/Developer",
        "/Library/Frameworks",
        "/Applications",
        "/opt/homebrew",
        "/usr/local",
        "/etc",
        "/private/etc",
        "/dev",
    )
    read_rules = "\n".join(
        f"(allow file-read* (subpath {quote(path)}))"
        for path in readonly_paths
        if Path(path).exists()
    )
    return (
        "(version 1)\n"
        "(deny default)\n"
        "(allow process*)\n"
        "(allow network*)\n"
        f"(allow file-read* (subpath {quote(str(execution_root))}))\n"
        f"{read_rules}\n"
        f"(allow file-write* (subpath {quote(str(execution_root))}))\n"
        '(allow file-write* (literal "/dev/null"))\n'
    )


def _container_path(value: str, execution_root: Path) -> str:
    root = str(execution_root)
    if value == root:
        return "/shell_executions"
    if value.startswith(root + os.sep):
        return "/shell_executions/" + value[len(root) + 1 :].replace(os.sep, "/")
    return value


def sandboxed_shell_argv(
    command: str,
    execution_root: Path,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    shell_argv = ["bash", "--noprofile", "--norc", "-c", command]
    if sys.platform.startswith("linux"):
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise RuntimeError("bubblewrap is unavailable; shell execution is disabled.")
        root = execution_root.resolve(strict=True)
        working_dir = (cwd or root).resolve(strict=True)
        if working_dir != root and root not in working_dir.parents:
            raise ValueError("cwd must stay inside /shell_executions")
        relative_cwd = working_dir.relative_to(root).as_posix()
        chdir = "/shell_executions" if relative_cwd == "." else f"/shell_executions/{relative_cwd}"

        argv = [
            bwrap,
            "--die-with-parent",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            "/",
        ]
        for system_path in (
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
            Path("/lib64"),
            Path("/etc"),
            Path("/opt"),
        ):
            if system_path.exists():
                argv.extend(["--dir", str(system_path), "--ro-bind", str(system_path), str(system_path)])
        argv.extend(
            [
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--remount-ro",
                "/proc",
                "--symlink",
                "shell_executions/.tmp",
                "/tmp",
                "--symlink",
                "shell_executions/.run",
                "/run",
                "--dir",
                "/shell_executions",
                "--bind",
                str(root),
                "/shell_executions",
                "--remount-ro",
                "/",
                "--chdir",
                chdir,
                "--clearenv",
            ]
        )
        for key, value in (env or {}).items():
            argv.extend(["--setenv", key, _container_path(str(value), root)])
        return [*argv, "--", *shell_argv]

    if sys.platform == "darwin":
        sandbox_exec = "/usr/bin/sandbox-exec"
        if not Path(sandbox_exec).is_file():
            raise RuntimeError("macOS sandbox-exec is unavailable; shell execution is disabled.")
        return [sandbox_exec, "-p", _macos_profile(execution_root), *shell_argv]

    raise RuntimeError(f"Shell execution is unsupported on {sys.platform}; no filesystem sandbox is available.")
