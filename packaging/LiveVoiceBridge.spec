# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
if sys.platform == "win32":
    # Resolve system DLLs from Windows, not unrelated development tools on PATH.
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(
        str(path) for path in (
            Path(sys.executable).parent,
            Path(sys.base_prefix),
            windows / "System32",
            windows,
        )
    )

a = Analysis(
    [str(root / "src/livevoicebridge/__main__.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=copy_metadata("livevoicebridge") + collect_data_files("livevoicebridge") + collect_data_files("pykakasi") + [
        (str(root / "services/qwen3/pyproject.toml"), "livevoicebridge/integrations/qwen/resources/service"),
        (str(root / "services/qwen3/src/lvb_qwen3_service"),
         "livevoicebridge/integrations/qwen/resources/service/src/lvb_qwen3_service"),
    ],
    hiddenimports=collect_submodules("grpc") + collect_submodules("google.protobuf")
    + collect_submodules("livevoicebridge.plugins.builtin")
    + ["livevoicebridge._native", "livevoicebridge.integrations.youtube.generated.stream_list_pb2_grpc"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="LiveVoiceBridge", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=True, console=False,
    icon=str(root / "src/livevoicebridge/desktop/resources/icons/icon.ico"),
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=True, name="LiveVoiceBridge",
)
