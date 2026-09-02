"""LiveVoiceBridge source entry point."""

from __future__ import annotations

import sys
from pathlib import Path


def _add_source_package() -> None:
    if getattr(sys, "frozen", False):
        return
    source_dir = Path(__file__).resolve().parent / "src"
    source_path = str(source_dir)
    if source_path not in sys.path:
        sys.path.insert(0, source_path)


def main() -> None:
    _add_source_package()

    from livevoicebridge.bootstrap import main as bootstrap_main

    bootstrap_main()


if __name__ == "__main__":
    main()
