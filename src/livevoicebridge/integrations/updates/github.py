import requests


class GitHubUpdateProvider:
    def __init__(self, version: str):
        self._version = version

    def latest(self) -> str | None:
        response = requests.get("https://api.github.com/repos/Ikumyon/LiveVoiceBridge/releases/latest", timeout=(2, 5))
        response.raise_for_status()
        version = str(response.json()["tag_name"])

        def numbers(value: str) -> tuple[int, ...]:
            return tuple(int(part) for part in value.lstrip("v").split("."))

        return version if numbers(version) > numbers(self._version) else None
