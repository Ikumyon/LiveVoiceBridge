"""Build the Linux input plugin against the Qt version bundled by PySide6."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from environment import ProjectEnvironment, run

FCITX_VERSION = "5.1.16"
FCITX_COMMIT = "115750044f3d0db16ca5859808c7da830fd1ff52"
PLUGIN_NAME = "libfcitx5platforminputcontextplugin.so"


def qt_information(python: str) -> dict[str, str]:
    query = (
        "import json; from PySide6.QtCore import QLibraryInfo, qVersion; "
        "print(json.dumps({'version': qVersion(), "
        "'plugins': QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)}))"
    )
    return json.loads(subprocess.check_output([python, "-B", "-c", query], encoding="utf-8"))


def prepare_fcitx(context: ProjectEnvironment) -> None:
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("Linux distribution builds require an x86_64 host.")
    for tool in ("git", "cmake", "ninja", "patchelf", "readelf", "ldd"):
        if shutil.which(tool, path=context.env["PATH"]) is None:
            raise FileNotFoundError(f"Linux distribution builds require {tool}; see docs/source/development.md.")
    qt = qt_information(context.python)
    version = qt["version"]
    if re.fullmatch(r"6\.[0-9]+\.[0-9]+", version, re.ASCII) is None:
        raise ValueError(f"A released Qt 6 SDK is required, got {version!r}.")
    work = context.root / "build/fcitx5"
    work.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="compile-", dir=work) as temporary:
        directory = Path(temporary)
        sdk = directory / "sdk"
        # The base desktop SDK includes Qt Wayland client and its private headers.
        run(
            [
                context.python,
                "-m",
                "aqt",
                "install-qt",
                "linux",
                "desktop",
                version,
                "linux_gcc_64",
                "--outputdir",
                str(sdk),
            ],
            directory,
            context.env,
        )
        prefix = sdk / version / "gcc_64"
        sdk_version = subprocess.check_output(
            [str(prefix / "bin/qmake"), "-query", "QT_VERSION"],
            encoding="utf-8",
            env=context.env,
        ).strip()
        if sdk_version != version:
            raise ValueError(f"Qt SDK {sdk_version} does not match PySide6 Qt {version}.")
        source = directory / "source"
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                FCITX_VERSION,
                "https://github.com/fcitx/fcitx5-qt.git",
                str(source),
            ],
            directory,
            context.env,
        )
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, encoding="utf-8").strip()
        if commit != FCITX_COMMIT:
            raise ValueError(f"Unexpected fcitx5-qt {FCITX_VERSION} commit: {commit}")
        build = directory / "build"
        run(
            [
                "cmake",
                "-S",
                str(source),
                "-B",
                str(build),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                f"-DCMAKE_PREFIX_PATH={prefix}",
                f"-DQt6_DIR={prefix / 'lib/cmake/Qt6'}",
                "-DQT_FIND_PRIVATE_MODULES=ON",
                "-DENABLE_QT4=OFF",
                "-DENABLE_QT5=OFF",
                "-DENABLE_QT6=ON",
                "-DENABLE_X11=ON",
                "-DENABLE_QT6_WAYLAND_WORKAROUND=ON",
                "-DBUILD_ONLY_PLUGIN=ON",
                "-DBUILD_STATIC_PLUGIN=OFF",
            ],
            directory,
            context.env,
        )
        cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
        for module, location in re.findall(r"^(Qt6\w*_DIR):PATH=(.+)$", cache, re.MULTILINE):
            if not Path(location).resolve().is_relative_to(prefix):
                raise ValueError(f"CMake selected a Qt module outside the matching SDK: {module}={location}")
        run(
            ["cmake", "--build", str(build), "--target", "fcitx5platforminputcontextplugin-qt6", "--parallel"],
            directory,
            context.env,
        )
        plugin = build / "qt6/platforminputcontext" / PLUGIN_NAME
        if not plugin.is_file() or not plugin.stat().st_size:
            raise ValueError("Fcitx build did not produce the input plugin.")
        # Do not carry the SDK's build-time RUNPATH into the venv or distribution.
        run(["patchelf", "--set-rpath", "$ORIGIN/../../lib", str(plugin)], directory, context.env)
        destination = Path(qt["plugins"]) / "platforminputcontexts"
        if not destination.is_relative_to(context.directory):
            raise ValueError(f"Qt plugins must belong to the build environment: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plugin, destination / PLUGIN_NAME)
        licenses = work / "licenses"
        licenses.mkdir(exist_ok=True)
        for name in ("BSD-3-Clause.txt", "LGPL-2.1-or-later.txt"):
            shutil.copy2(source / "LICENSES" / name, licenses / name)
        (licenses / "build.json").write_text(
            json.dumps({"version": FCITX_VERSION, "commit": FCITX_COMMIT, "qt": version}, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Fcitx {FCITX_VERSION} prepared for Qt {version}")


def inspect_fcitx(stage: Path, distribution: Path, python: str) -> None:
    internal = distribution / "_internal"
    plugin = internal / "PySide6/Qt/plugins/platforminputcontexts" / PLUGIN_NAME
    if not plugin.is_file() or not plugin.stat().st_size:
        raise ValueError("Bundled Fcitx input plugin is missing or empty.")
    licenses = internal / "licenses/fcitx5-qt"
    for name in ("BSD-3-Clause.txt", "LGPL-2.1-or-later.txt", "build.json"):
        if (licenses / name).read_bytes() != (stage / "build/fcitx5/licenses" / name).read_bytes():
            raise ValueError(f"Bundled Fcitx license/build information differs: {name}")
    expected = {"version": FCITX_VERSION, "commit": FCITX_COMMIT, "qt": qt_information(python)["version"]}
    if json.loads((licenses / "build.json").read_text(encoding="utf-8")) != expected:
        raise ValueError("Bundled Fcitx build information does not match the selected Qt/source.")
    # Inspect the loader's full dependency closure, using only the distribution and system libraries.
    env = dict(os.environ, LC_ALL="C")
    env.pop("LD_PRELOAD", None)
    env["LD_LIBRARY_PATH"] = os.pathsep.join(str(path) for path in (internal / "PySide6/Qt/lib", internal))
    dependencies = subprocess.check_output(["ldd", str(plugin)], encoding="utf-8", env=env)
    if "not found" in dependencies:
        raise ValueError(f"Unresolved bundled Fcitx dependencies:\n{dependencies}")
    libraries = [plugin]
    for name, resolved in re.findall(r"^\s*(\S+) => (/\S+)", dependencies, re.MULTILINE):
        path = Path(resolved).resolve()
        if name.startswith(("libQt6", "libFcitx5")) and not path.is_relative_to(internal):
            raise ValueError(f"Fcitx dependency resolved outside the distribution: {name} => {path}")
        if path.is_relative_to(internal):
            libraries.append(path)
    for library in libraries:
        dynamic = subprocess.check_output(["readelf", "--dynamic", str(library)], encoding="utf-8", env=env)
        for line in dynamic.splitlines():
            if any(tag in line for tag in ("(RPATH)", "(RUNPATH)", "(NEEDED)")):
                if str(stage / "build/fcitx5") in line:
                    raise ValueError(f"Bundled library still references the build SDK: {library}: {line}")
                if library == plugin and re.search(r"\[(?:[^\]]*:)?/", line):
                    raise ValueError(f"Fcitx plugin has an absolute dependency/search path: {line}")
    print("Bundled Fcitx input plugin, licenses and dependencies verified")
