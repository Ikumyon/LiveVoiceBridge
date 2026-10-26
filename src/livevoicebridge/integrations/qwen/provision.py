"""Cancellable, hash-verified provisioning entirely within portable storage."""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from urllib.parse import unquote, urlparse

import requests

from livevoicebridge import _native
from livevoicebridge.integrations.qwen.assets import MODEL_ID, MODEL_REVISION, RUNTIMES
from livevoicebridge.integrations.qwen.models import validate_model
from livevoicebridge.plugins.builtin.qwen3.contracts import QwenState


class Cancelled(Exception):
    pass


class Provisioner:
    def __init__(self, root: Path, assets: Path, service: Path, cancel: Event, publish: Callable[[QwenState], None]):
        self.root = root.resolve()
        self.assets = assets
        self.service = service
        self.cancel = cancel
        self.publish = publish
        self.platform, self.python_relative = _native.qwen_platform()
        self.process = _native.ManagedProcess()
        for name in ("downloads", "tmp", "cache", "logs", "models", "runtime"):
            self.directory(name)
        self.log = self.root / "logs/setup.log"

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled("準備を中止しました。")

    def directory(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("保存先がQwen管理領域の外を指しています。")
        return path

    def status(self, phase: str, message: str, progress: int | None = None) -> None:
        self.check()
        self.publish(QwenState(phase, message, progress=progress, busy=True))

    @property
    def python(self) -> Path:
        return self.root / "runtime" / self.python_relative

    def environment(self) -> dict[str, str]:
        return {
            "PYTHONUTF8": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": str(self.root / "tmp"),
            "TMP": str(self.root / "tmp"),
            "TMPDIR": str(self.root / "tmp"),
            "PIP_CACHE_DIR": str(self.root / "cache/pip"),
            "HF_HOME": str(self.root / "cache/huggingface"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "TORCH_HOME": str(self.root / "cache/torch"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": str(self.root / "pip.ini"),
            "NUMBA_CACHE_DIR": str(self.root / "cache/numba"),
            "TORCHINDUCTOR_CACHE_DIR": str(self.root / "cache/torchinductor"),
            "MPLCONFIGDIR": str(self.root / "cache/matplotlib"),
            "GRADIO_TEMP_DIR": str(self.root / "tmp/gradio"),
            "GRADIO_ANALYTICS_ENABLED": "False",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }

    def run(self, args: list[str]) -> None:
        self.check()
        if args[:2] == ["-m", "pip"]:
            args = ["-m", "pip", "--isolated", "--cache-dir", str(self.root / "cache/pip"), *args[2:]]
        self.process.start(str(self.python), ["-I", "-B", *args], str(self.root), self.environment(), str(self.log))
        try:
            while self.process.is_running():
                if self.cancel.wait(0.1):
                    raise Cancelled("準備を中止しました。")
            code = self.process.exit_code()
            if code != 0:
                raise RuntimeError(f"準備処理が失敗しました（終了コード {code}）。詳細ログを確認してください。")
        finally:
            self.process.close()

    def download(self, url: str, digest: str, label: str, size: int | None = None) -> Path:
        if len(digest) != 64:
            raise ValueError("取得ファイルのSHA-256が不正です。")
        filename = Path(unquote(urlparse(url).path)).name
        folder = self.directory(f"downloads/{digest}")
        target = folder / filename
        if target.is_file() and self.hash_file(target) == digest:
            return target
        temporary = folder / (filename + ".part")
        with requests.get(url, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            total = size or int(response.headers.get("Content-Length", "0"))
            done = 0
            last = 0.0
            checksum = hashlib.sha256()
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    self.check()
                    output.write(chunk)
                    checksum.update(chunk)
                    done += len(chunk)
                    if time.monotonic() - last >= 0.25:
                        self.status("downloading", label, min(100, done * 100 // total) if total else None)
                        last = time.monotonic()
        if checksum.hexdigest() != digest:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"取得ファイルのハッシュが一致しません: {label}")
        temporary.replace(target)
        return target

    def hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                self.check()
                digest.update(chunk)
        return digest.hexdigest()

    def fingerprint(self) -> str:
        lock_file = self.assets / f"{self.platform}.json"
        checksum = hashlib.sha256(lock_file.read_bytes())
        for path in [self.service / "pyproject.toml", *sorted((self.service / "src").rglob("*.py"))]:
            checksum.update(path.read_bytes())
        checksum.update(json.dumps(RUNTIMES[self.platform], sort_keys=True).encode())
        return checksum.hexdigest()

    def runtime_ready(self) -> bool:
        marker = self.root / "runtime/complete.json"
        if not marker.is_file() or not self.python.is_file():
            return False
        if not self.python.resolve().is_relative_to(self.root):
            raise ValueError("専用Pythonがアプリ管理領域の外を指しています。")
        try:
            return json.loads(marker.read_text(encoding="utf-8")).get("lock") == self.fingerprint()
        except ValueError, OSError:
            return False

    def runtime(self) -> None:
        if self.runtime_ready():
            return
        lock_file = self.assets / f"{self.platform}.json"
        marker = self.root / "runtime/complete.json"
        fingerprint = self.fingerprint()
        self.status("environment", "専用のPython環境を準備しています。")
        marker.unlink(missing_ok=True)
        runtime = RUNTIMES[self.platform]
        archive = self.download(runtime["url"], runtime["sha256"], "専用Pythonを取得しています。")
        destination = self.directory("runtime")
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                self.check()
                tar.extract(member, destination, filter="data")
        packages = json.loads(lock_file.read_text(encoding="utf-8"))
        downloaded: list[tuple[str, Path]] = []
        for entry in packages:
            downloaded.append((entry["name"], self.download(entry["url"], entry["sha256"], entry["name"])))
        self.status("environment", "必要なライブラリを導入しています。")
        bootstrap = [str(path) for name, path in downloaded if name in {"setuptools", "wheel", "packaging"}]
        self.run(["-m", "pip", "install", "--no-index", "--no-deps", *bootstrap])
        self.run(
            [
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                "--no-build-isolation",
                *[str(path) for _, path in downloaded],
            ]
        )
        # Build only from the bundled source package; never an editable install.
        staging = self.root / "tmp/service"
        if staging.exists():
            if not staging.resolve().is_relative_to(self.root):
                raise ValueError("サービスの作業領域が不正です。")
            shutil.rmtree(staging)
        shutil.copytree(self.service, staging, ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info"))
        self.run(["-m", "pip", "install", "--no-index", "--no-deps", "--no-build-isolation", str(staging)])
        self.run(["-m", "pip", "check"])
        marker.write_text(json.dumps({"lock": fingerprint}), encoding="utf-8")

    def fetch_model(self) -> Path:
        self.status("downloading", "モデルのファイル一覧を取得しています。")
        with requests.get(
            f"https://huggingface.co/api/models/{MODEL_ID}/revision/{MODEL_REVISION}",
            params={"blobs": "true"},
            timeout=(10, 30),
        ) as response:
            response.raise_for_status()
            metadata = response.json()
        source = self.directory(f"models/source-{MODEL_REVISION}")
        for entry in metadata["siblings"]:
            self.check()
            name = entry["rfilename"]
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
                raise ValueError("取得モデルのファイル名が不正です。")
            target = source / relative
            self.directory(str(target.parent.relative_to(self.root)))
            url = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{name}"
            lfs = entry.get("lfs")
            if lfs:
                payload = self.download(url, lfs["sha256"], name, lfs["size"])
                if not target.is_file() or self.hash_file(target) != lfs["sha256"]:
                    shutil.copyfile(payload, target)
            else:
                # Git blob IDs authenticate the small configuration/tokenizer files.
                with requests.get(url, timeout=(10, 30)) as response:
                    response.raise_for_status()
                    content = response.content
                header = f"blob {len(content)}\0".encode()
                if hashlib.sha1(header + content).hexdigest() != entry["blobId"]:
                    raise ValueError(f"モデルファイルのハッシュが一致しません: {name}")
                target.write_bytes(content)
        return source

    def prepare(self, source: str) -> Path:
        try:
            # Validate supplied models before downloading the runtime.
            original = Path(source).resolve(strict=True) if source else None
            kind = validate_model(original) if original else "original"
            self.runtime()
            original = original or self.fetch_model()
            kind = validate_model(original)
            if kind == "openvino":
                return original
            checksum = hashlib.sha256(str(original).encode())
            self.status("converting", "変換元のモデルを確認しています。")
            for path in sorted(original.rglob("*")):
                if path.is_file() and not any(
                    part in {"compiled_cache", ".git", ".cache"} for part in path.relative_to(original).parts
                ):
                    checksum.update(str(path.relative_to(original)).encode())
                    checksum.update(self.hash_file(path).encode())
            checksum.update((self.service / "src/lvb_qwen3_service/prepare_tokenizer.py").read_bytes())
            identity = checksum.hexdigest()[:20]
            destination = self.root / "models" / f"converted-{identity}"
            marker = destination / "complete.json"
            if marker.is_file() and validate_model(destination) == "openvino":
                return destination
            work = self.root / "models" / f"converting-{identity}"
            if work.exists():
                self.remove_work(work)
            if kind == "tokenizer":
                self.status("converting", "モデルをアプリ管理領域へコピーしています。")
                self.copy_model(original, work)
            else:
                # Exporters may create auxiliary files: export from a private copy.
                snapshot = self.root / "models" / f"input-{identity}"
                if snapshot.exists():
                    self.remove_work(snapshot)
                self.status("converting", "変換用にモデルをコピーしています。")
                self.copy_model(original, snapshot)
                self.status("converting", "モデルをOpenVINO形式へ変換しています。")
                self.run(
                    [
                        "-m",
                        "optimum.commands.optimum_cli",
                        "export",
                        "openvino",
                        "--model",
                        str(snapshot),
                        "--task",
                        "text-to-audio",
                        "--weight-format",
                        "fp16",
                        "--trust-remote-code",
                        str(work),
                    ]
                )
            self.status("converting", "テキストトークナイザーを生成しています。")
            self.run(["-m", "lvb_qwen3_service.prepare_tokenizer", str(work)])
            if validate_model(work) != "openvino":
                raise ValueError("モデルの変換が完了していません。")
            self.check()
            if destination.exists():
                self.remove_work(destination)
            work.replace(destination)
            (destination / "complete.json").write_text(json.dumps({"source": str(original)}), encoding="utf-8")
            return destination
        finally:
            self.process.close()

    def copy_model(self, source: Path, target: Path) -> None:
        def copy(src, dst):
            self.check()
            # Dereference HF snapshot links, but do not preserve read-only modes.
            with Path(src).open("rb") as reader, Path(dst).open("wb") as writer:
                while chunk := reader.read(1024 * 1024):
                    self.check()
                    writer.write(chunk)
            return dst

        shutil.copytree(
            source,
            target,
            copy_function=copy,
            ignore=shutil.ignore_patterns("compiled_cache", "complete.json", ".git", ".cache"),
        )

    def remove_work(self, path: Path) -> None:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.root / "models") or resolved == self.root / "models":
            raise ValueError("作業領域の削除先が不正です。")
        shutil.rmtree(path)
