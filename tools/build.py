"""Shared build steps for Actions and local development checks."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
import venv
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    ("pyproject.toml", "project"),
    ("native/Cargo.toml", "package"),
    ("services/qwen3/pyproject.toml", "project"),
)
TAG_PATTERN = re.compile(r"v([0-9]+)\.([0-9]+)\.([0-9]+)(.*)", re.ASCII)


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8").strip()


def tag_version(tag: str) -> str:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"Invalid release tag {tag!r}. Expected vX.Y.Z followed by an optional arbitrary suffix.")
    version = ".".join(str(int(part)) for part in match.group(1, 2, 3))
    if suffix := match.group(4):
        # Encode any suffix losslessly in a form accepted by both PEP 440 and SemVer.
        version += f"+tag.x{suffix.encode('utf-8').hex()}"
    return version


def build_version() -> str:
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        return "0.0.0"
    tag = ref.removeprefix("refs/tags/")
    version = tag_version(tag)
    if git("rev-parse", f"refs/tags/{tag}^{{commit}}") != git("rev-parse", "HEAD"):
        raise ValueError("Release tag does not point to the checked-out commit.")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Release checkout must be clean.")
    return version


def prepare_source(version: str) -> Path:
    stage = ROOT / "build/ci-source"
    # Refuse reuse instead of accidentally shipping files from an earlier build.
    stage.mkdir(parents=True, exist_ok=False)
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    for relative in filter(None, paths):
        source = ROOT / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Expected a regular source file: {relative}")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # These are generated build inputs, not edits to the repository manifests.
    for relative, section in MANIFESTS:
        path = stage / relative
        text = path.read_text(encoding="utf-8")
        if tomllib.loads(text)[section]["version"] != "0.0.0":
            raise ValueError(f"Expected development placeholder in {relative}")
        text, count = re.subn(r'^version = "0\.0\.0"$', f'version = "{version}"', text, count=1, flags=re.MULTILINE)
        if count != 1 or tomllib.loads(text)[section]["version"] != version:
            raise ValueError(f"Failed to generate version in {relative}")
        path.write_text(text, encoding="utf-8")
    return stage


def inspect_distribution(stage: Path, distribution: Path, version: str, windows: bool) -> None:
    executable = distribution / ("LiveVoiceBridge.exe" if windows else "LiveVoiceBridge")
    if not executable.is_file() or executable.stat().st_size == 0:
        raise ValueError("Application executable is missing or empty.")
    if not windows and not os.access(executable, os.X_OK):
        raise ValueError("Linux executable permission is missing.")
    internal = distribution / "_internal"
    package = internal / "livevoicebridge"
    extension = "*.pyd" if windows else "*.so"
    if not any(path.stat().st_size for path in package.glob(f"_native{extension}")):
        raise ValueError("Rust extension is missing or empty.")
    metadata = list(internal.glob("livevoicebridge-*.dist-info/METADATA"))
    if len(metadata) != 1 or Parser().parsestr(metadata[0].read_text(encoding="utf-8"))["Version"] != version:
        raise ValueError("Bundled application metadata does not match the build version.")
    service = package / "integrations/qwen/resources/service"
    if tomllib.loads((service / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] != version:
        raise ValueError("Bundled Qwen version does not match the build version.")
    for relative, section in MANIFESTS:
        if tomllib.loads((stage / relative).read_text(encoding="utf-8"))[section]["version"] != version:
            raise ValueError(f"Build version mismatch: {relative}")
    for relative in ("src/livevoicebridge/desktop/resources", "src/livevoicebridge/integrations/qwen/resources"):
        source = stage / relative
        destination = internal / Path(relative).relative_to("src")
        for path in source.rglob("*"):
            if path.is_file() and path.suffix not in {".py", ".pyc"}:
                if path.read_bytes() != (destination / path.relative_to(source)).read_bytes():
                    raise ValueError(f"Bundled resource differs: {path}")
    for path in (stage / "services/qwen3/src").rglob("*.py"):
        if path.read_bytes() != (service / "src" / path.relative_to(stage / "services/qwen3/src")).read_bytes():
            raise ValueError(f"Bundled Qwen source differs: {path}")


@dataclass(frozen=True)
class BuildContext:
    root: Path
    python: str
    env: dict[str, str]
    windows: bool


def build_environment(root: Path, environment: Path, *, fresh: bool = False) -> BuildContext:
    if (
        sys.implementation.name != "cpython"
        or sys.version_info < (3, 14)
        or sysconfig.get_config_var("Py_GIL_DISABLED")
    ):
        raise ValueError("Builds require standard CPython 3.14 or newer.")
    windows = sys.platform == "win32"
    scripts = environment / ("Scripts" if windows else "bin")
    python = str(scripts / ("python.exe" if windows else "python"))
    if environment.exists():
        if fresh:
            raise FileExistsError(f"CI requires a fresh environment: {environment}")
        if not Path(python).is_file():
            raise ValueError(f"Incomplete environment; remove or move it before rebuilding: {environment}")
    else:
        venv.EnvBuilder(with_pip=True).create(environment)
    env = dict(os.environ, VIRTUAL_ENV=str(environment), PYO3_PYTHON=python, PYTHONUTF8="1")
    env["PATH"] = str(scripts) + os.pathsep + env["PATH"]
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    check = (
        "import sys, sysconfig; "
        "assert sys.implementation.name == 'cpython' and sys.version_info >= (3, 14) "
        "and not sysconfig.get_config_var('Py_GIL_DISABLED'), 'Standard CPython 3.14+ required'"
    )
    run([python, "-c", check], root, env)
    return BuildContext(root, python, env, windows)


def install_dependencies(context: BuildContext, dependencies: list[str]) -> None:
    run(
        [
            context.python,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            *dependencies,
        ],
        context.root,
        context.env,
    )


def verify_native(context: BuildContext) -> None:
    check = """
from pathlib import Path
from importlib.metadata import version
import tomllib
try:
    from livevoicebridge import _native
    artifact = Path(_native.__file__).resolve()
    if artifact.parent != Path('src/livevoicebridge').resolve():
        raise ImportError('Rust extension belongs to another source tree')
    expected = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    if version('livevoicebridge') != expected:
        raise ImportError('Installed package metadata does not match the source version')
except (ImportError, OSError) as exc:
    raise SystemExit('Run the rust build first: ' + str(exc)) from exc
print('Rust extension: ' + str(artifact))
"""
    run([context.python, "-c", check], context.root, context.env)


def build_rust(context: BuildContext) -> None:
    install_dependencies(context, ["maturin"])
    run(["cargo", "update", "--manifest-path", "native/Cargo.toml"], context.root, context.env)
    run([context.python, "-m", "maturin", "develop", "--release", "--locked"], context.root, context.env)
    verify_native(context)


def build_python(context: BuildContext) -> Path:
    project = tomllib.loads((context.root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    install_dependencies(context, project["dependencies"] + project["optional-dependencies"]["package"])
    verify_native(context)
    run(
        [context.python, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/LiveVoiceBridge.spec"],
        context.root,
        context.env,
    )
    distribution = context.root / "dist/LiveVoiceBridge"
    inspect_distribution(context.root, distribution, project["version"], context.windows)
    print(f"Distribution verified: {distribution}")
    return distribution


def archive_distribution(distribution: Path, windows: bool) -> None:
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    if windows:
        with zipfile.ZipFile(output / "LiveVoiceBridge-Windows-x64.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in distribution.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(distribution.parent))
    else:
        with tarfile.open(output / "LiveVoiceBridge-Linux-x64.tar.gz", "w:gz") as archive:
            archive.add(distribution, arcname="LiveVoiceBridge")
    print(f"Distribution archived: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("ci", "rust", "python"))
    args = parser.parse_args()
    if sys.platform not in {"win32", "linux"}:
        raise ValueError("Only Windows and Linux builds are supported.")
    if args.target == "ci":
        stage = prepare_source(build_version())
        context = build_environment(stage, ROOT / "build/ci-venv", fresh=True)
        build_rust(context)
        distribution = build_python(context)
        if os.environ.get("GITHUB_REF", "").startswith("refs/tags/"):
            archive_distribution(distribution, context.windows)
    else:
        context = build_environment(ROOT, ROOT / "venv")
        if args.target == "rust":
            build_rust(context)
        else:
            build_python(context)


if __name__ == "__main__":
    main()
