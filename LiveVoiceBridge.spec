# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('assets', 'assets'),
        ('core/stream_list.proto', 'core'),
        ('core/stream_list_pb2.py', 'core'),
        ('core/stream_list_pb2_grpc.py', 'core'),
    ] + collect_data_files('pykakasi'),
    hiddenimports=[
        'sherpa_onnx',
        'supertonic',
        'onnxruntime',
        'openvino',
        'soundfile',
        'numpy',
        'pyopenjtalk',
        'pykakasi',
        'emoji',
        'google',
        'google.protobuf',
        'google.protobuf.internal',
    ] + collect_submodules('google.protobuf') + collect_submodules('grpc'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LiveVoiceBridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

