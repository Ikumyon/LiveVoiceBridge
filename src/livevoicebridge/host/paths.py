import sys
from dataclasses import dataclass
from pathlib import Path

from livevoicebridge import _native


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    config: Path
    dictionary: Path
    sounds: Path
    executable_filter: str
    qwen_assets: Path
    qwen_service: Path

    @classmethod
    def resolve(cls) -> AppPaths:
        source = None if getattr(sys, "frozen", False) else str(Path(__file__).resolve().parents[3])
        paths = _native.PlatformPaths(source)
        assets = Path(__file__).resolve().parents[1] / "integrations/qwen/resources"
        return cls(
            Path(paths.root),
            Path(paths.config),
            Path(paths.dictionary),
            Path(paths.sounds),
            paths.executable_filter,
            assets,
            assets / "service" if source is None else Path(source) / "services/qwen3",
        )
