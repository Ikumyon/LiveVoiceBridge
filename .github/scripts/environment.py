"""Prepare project-local Python environments and their dependency profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import sysconfig
import tomllib
import venv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ("dev", "ui", "rust", "package")


@dataclass(frozen=True)
class ProjectEnvironment:
    root: Path
    directory: Path
    python: str
    env: dict[str, str]
    windows: bool


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def prepare_environment(
    root: Path, directory: Path | None = None, *, fresh: bool = False, create: bool = True
) -> ProjectEnvironment:
    if sys.platform not in {"win32", "linux"}:
        raise ValueError("Only Windows and Linux environments are supported.")
    root = root.resolve()
    directory = (directory if directory is not None else root / "venv").resolve()
    windows = sys.platform == "win32"
    scripts = directory / ("Scripts" if windows else "bin")
    python = scripts / ("python.exe" if windows else "python")
    if directory.exists():
        if fresh:
            raise FileExistsError(f"A fresh environment is required: {directory}")
        if not python.is_file() or not (directory / "pyvenv.cfg").is_file():
            raise ValueError(f"Incomplete environment; remove or move it before retrying: {directory}")
    else:
        if not create:
            raise FileNotFoundError(f"Prepare the project environment first: {directory}")
        if (
            sys.implementation.name != "cpython"
            or sys.version_info < (3, 14)
            or sysconfig.get_config_var("Py_GIL_DISABLED")
        ):
            raise ValueError("Environment creation requires standard CPython 3.14 or newer.")
        venv.EnvBuilder(with_pip=True).create(directory)
    env = dict(os.environ, VIRTUAL_ENV=str(directory), PYO3_PYTHON=str(python), PYTHONUTF8="1")
    env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    check = (
        "import sys, sysconfig, pip; from pathlib import Path; "
        "assert sys.implementation.name == 'cpython' and sys.version_info >= (3, 14) "
        "and not sysconfig.get_config_var('Py_GIL_DISABLED'), 'Standard CPython 3.14+ required'; "
        "assert sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve(), "
        "'Incomplete or mismatched virtual environment; move or remove it before retrying'"
    )
    run([str(python), "-c", check, str(directory)], root, env)
    return ProjectEnvironment(root, directory, str(python), env, windows)


def dependencies_for(root: Path, profile: str) -> list[str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if profile == "ui":
        return [next(value for value in project["dependencies"] if re.match(r"(?i)^PySide6\b", value))]
    if profile == "rust":
        return [next(value for value in project["optional-dependencies"]["dev"] if re.match(r"(?i)^maturin\b", value))]
    if profile in {"dev", "package"}:
        return project["dependencies"] + project["optional-dependencies"][profile]
    raise ValueError(f"Unknown dependency profile: {profile}")


def ensure_dependencies(context: ProjectEnvironment, profile: str, *, update: bool = False) -> None:
    dependencies = dependencies_for(context.root, profile)
    definition = json.dumps(dependencies, ensure_ascii=False, sort_keys=True).encode("utf-8")
    fingerprint = hashlib.sha256(definition + (context.directory / "pyvenv.cfg").read_bytes()).hexdigest()
    marker = context.directory / ".livevoicebridge-dependencies.json"
    states: dict[str, str] = {}
    if marker.exists():
        try:
            document = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(document, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in document.items()
            ):
                states = document
        except ValueError:
            pass
    if not update and states.get(profile) == fingerprint:
        print(f"Dependencies unchanged: {profile}")
        return
    run(
        [context.python, "-m", "pip", "install", "--upgrade", "--upgrade-strategy", "eager", *dependencies],
        context.root,
        context.env,
    )
    states[profile] = fingerprint
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")
    temporary.replace(marker)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--update-dependencies", action="store_true")
    args = parser.parse_args()
    context = prepare_environment(ROOT)
    ensure_dependencies(context, args.profile, update=args.update_dependencies)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
