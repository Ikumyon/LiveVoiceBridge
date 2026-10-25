"""Publish the already-built CI assets without rebuilding them."""

import json
import os
import subprocess
from pathlib import Path

from build import tag_version


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True, encoding="utf-8")


def main() -> None:
    tag = os.environ["RELEASE_TAG"]
    tag_version(tag)
    directory = Path("release-assets")
    assets = [directory / "LiveVoiceBridge-Windows-x64.zip", directory / "LiveVoiceBridge-Linux-x64.tar.gz"]
    if any(not path.is_file() or path.stat().st_size == 0 for path in assets):
        raise ValueError("Both distributions are required before publishing.")
    # List via the API so authentication/network errors cannot be mistaken for a missing release.
    pages = json.loads(gh("api", "repos/{owner}/{repo}/releases", "--paginate", "--slurp"))
    existing = next((release for page in pages for release in page if release["tag_name"] == tag), None)
    if existing is not None and not existing["draft"]:
        raise ValueError("This release is already published; published releases cannot be overwritten.")
    if existing is None:
        gh("release", "create", tag, "--draft", "--verify-tag", "--title", tag, "--generate-notes")
    gh("release", "upload", tag, *(str(path) for path in assets), "--clobber")
    uploaded = json.loads(gh("release", "view", tag, "--json", "assets"))["assets"]
    sizes = {asset["name"]: asset["size"] for asset in uploaded}
    if any(sizes.get(path.name) != path.stat().st_size for path in assets):
        raise ValueError("Release assets are incomplete; the release remains a draft.")
    gh("release", "edit", tag, "--draft=false")


if __name__ == "__main__":
    main()
