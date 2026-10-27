"""Shared build steps for Actions and local development checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

from environment import ProjectEnvironment, ensure_dependencies, prepare_environment, run
from generate_ui import form_sources, generate, generated_module

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = (
    ("pyproject.toml", "project"),
    ("native/Cargo.toml", "package"),
    ("services/qwen3/pyproject.toml", "project"),
)
TAG_PATTERN = re.compile(r"v([0-9]+)\.([0-9]+)\.([0-9]+)(.*)", re.ASCII)


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


def inspect_distribution(stage: Path, distribution: Path, version: str, windows: bool, python: str) -> None:
    executable = distribution / ("LiveVoiceBridge.exe" if windows else "LiveVoiceBridge")
    if not executable.is_file() or executable.stat().st_size == 0:
        raise ValueError("Application executable is missing or empty.")
    if not windows and not os.access(executable, os.X_OK):
        raise ValueError("Linux executable permission is missing.")
    internal = distribution / "_internal"
    archive_check = (
        "import json, sys; from PyInstaller.archive.readers import CArchiveReader; "
        "print(json.dumps(list(CArchiveReader(sys.argv[1]).open_embedded_archive('PYZ.pyz').toc)))"
    )
    modules = json.loads(subprocess.check_output([python, "-c", archive_check, str(executable)], encoding="utf-8"))
    for source in form_sources(stage):
        module = generated_module(stage, source)
        if module not in modules:
            raise ValueError(f"Generated form module is missing from the executable: {module}")
    if any(name.startswith("PySide6.QtUiTools") for name in modules):
        raise ValueError("QtUiTools must not be bundled.")
    for path in distribution.rglob("*"):
        if path.is_file() and (path.suffix.lower() == ".ui" or "uitools" in path.name.lower()):
            raise ValueError(f"Development UI resource must not be bundled: {path}")
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
    for relative in (
        "src/livevoicebridge/desktop/resources",
        "src/livevoicebridge/integrations/qwen/resources",
        "src/livevoicebridge/plugins/builtin",
    ):
        source = stage / relative
        destination = internal / Path(relative).relative_to("src")
        for path in source.rglob("*"):
            if path.is_file() and path.suffix not in {".py", ".pyc", ".ui"}:
                if path.read_bytes() != (destination / path.relative_to(source)).read_bytes():
                    raise ValueError(f"Bundled resource differs: {path}")
    for path in (stage / "services/qwen3/src").rglob("*.py"):
        if path.read_bytes() != (service / "src" / path.relative_to(stage / "services/qwen3/src")).read_bytes():
            raise ValueError(f"Bundled Qwen source differs: {path}")


def verify_native(context: ProjectEnvironment) -> None:
    check = """
from pathlib import Path
from importlib.metadata import version
import sys
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
    print('Run the rust build first: ' + str(exc), file=sys.stderr)
    raise SystemExit(2) from exc
print('Rust extension: ' + str(artifact))
"""
    run([context.python, "-c", check], context.root, context.env)


def build_rust(context: ProjectEnvironment) -> None:
    if shutil.which("cargo", path=context.env["PATH"]) is None:
        raise FileNotFoundError("Rust/Cargo is required. Install the Rust toolchain before building the extension.")
    ensure_dependencies(context, "rust", update=True)
    run(["cargo", "update", "--manifest-path", "native/Cargo.toml"], context.root, context.env)
    run([context.python, "-m", "maturin", "develop", "--release", "--locked"], context.root, context.env)
    verify_native(context)


def build_python(context: ProjectEnvironment) -> Path:
    project = tomllib.loads((context.root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    ensure_dependencies(context, "package", update=True)
    verify_native(context)
    generate(context.root, context.python, force=True)
    run(
        [context.python, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/LiveVoiceBridge.spec"],
        context.root,
        context.env,
    )
    distribution = context.root / "dist/LiveVoiceBridge"
    inspect_distribution(context.root, distribution, project["version"], context.windows, context.python)
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
    parser.add_argument("target", choices=("ci", "rust", "python", "check-native"))
    args = parser.parse_args()
    if sys.platform not in {"win32", "linux"}:
        raise ValueError("Only Windows and Linux builds are supported.")
    if args.target == "ci":
        stage = prepare_source(build_version())
        context = prepare_environment(stage, ROOT / "build/ci-venv", fresh=True)
        build_rust(context)
        distribution = build_python(context)
        if os.environ.get("GITHUB_REF", "").startswith("refs/tags/"):
            archive_distribution(distribution, context.windows)
    else:
        context = prepare_environment(ROOT, create=args.target != "check-native")
        if args.target == "check-native":
            verify_native(context)
        elif args.target == "rust":
            build_rust(context)
        else:
            build_python(context)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except subprocess.TimeoutExpired as exc:
        print(f"Designer compiler command timed out after {exc.timeout}s: {exc.cmd}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
