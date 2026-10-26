import re

import requests


class GitHubUpdateProvider:
    def __init__(self, version: str):
        self._version = version

    def latest(self) -> str | None:
        response = requests.get("https://api.github.com/repos/Ikumyon/LiveVoiceBridge/releases/latest", timeout=(2, 5))
        response.raise_for_status()
        version = str(response.json()["tag_name"])

        def numbers(value: str) -> tuple[int, ...]:
            match = re.match(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)", value, re.ASCII)
            if match is None:
                raise ValueError(f"Version must start with X.Y.Z or vX.Y.Z: {value!r}")
            return tuple(int(part) for part in match.group(1, 2, 3))

        return version if numbers(version) > numbers(self._version) else None
