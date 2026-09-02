"""Application bootstrap with no eager GUI or engine imports."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def project_root() -> Path:
    """Return the source checkout root or the frozen executable directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def restart_with_project_venv() -> None:
    """Use the checkout's Windows virtual environment for source execution."""
    if getattr(sys, "frozen", False) or platform.system() != "Windows":
        return

    venv_python = project_root() / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists() or Path(sys.executable).resolve() == venv_python.resolve():
        return

    entry_point = project_root() / "main.py"
    os.execve(
        str(venv_python),
        [str(venv_python), str(entry_point), *sys.argv[1:]],
        os.environ.copy(),
    )


def main() -> None:
    restart_with_project_venv()

    from livevoicebridge.application.runtime import run_application

    run_application()
