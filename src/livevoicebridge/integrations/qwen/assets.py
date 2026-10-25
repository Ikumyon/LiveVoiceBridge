"""Pinned Qwen runtime and model identities."""

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
MODEL_REVISION = "85e237c12c027371202489a0ec509ded67b5e4b5"
RUNTIMES = {
    "windows": {
        "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261021/"
        "cpython-3.14.9%2B20261021-x86_64-pc-windows-msvc-install_only_stripped.tar.gz",
        "sha256": "57cc230da61d897e8e593511c9dac781491675a036cb727b7de5cb7a62ceebea",
    },
    "linux": {
        "url": "https://github.com/astral-sh/python-build-standalone/releases/download/20261021/"
        "cpython-3.14.9%2B20261021-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz",
        "sha256": "561e91c1cadf30e84aec94d1917384ae3267e5f3e6e135e51fd1578bb19f4064",
    },
}
