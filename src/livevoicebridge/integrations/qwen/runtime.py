"""One application-owned Qwen process; no GUI or session thread waits for loading."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from threading import Condition, Event, Thread

import requests

from livevoicebridge import _native
from livevoicebridge.integrations.qwen.models import validate_model
from livevoicebridge.integrations.qwen.provision import Cancelled, Provisioner
from livevoicebridge.plugins.builtin.qwen3.contracts import QwenConfig, QwenState


class QwenManager:
    def __init__(
        self,
        root: Path,
        assets: Path,
        service: Path,
        publish: Callable[[QwenState], None],
        prepared: Callable[[str, str, int], None],
    ):
        self.root = root / "data/qwen"
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.resolve().is_relative_to(root.resolve()):
            raise ValueError("Qwenの保存先がポータブル配置先の外を指しています。")
        self.root = self.root.resolve()
        self.assets = assets
        self.service = service
        self._publish = publish
        self._prepared = prepared
        self._condition = Condition()
        self._state = QwenState()
        self._desired: QwenConfig | None = None
        self._generation = 0
        self._closed = False
        self._preparing = False
        self._cancel = Event()
        self._setup: Thread | None = None
        self._service_stopped = Event()
        self._service_stopped.set()
        self._endpoint = ""
        self._token = ""
        self._worker = Thread(target=self._manage, name="qwen-lifecycle")
        self._worker.start()

    @property
    def state(self) -> QwenState:
        with self._condition:
            return self._state

    def _set(self, state: QwenState, generation: int | None = None) -> None:
        with self._condition:
            if self._closed or (generation is not None and generation != self._generation):
                return
            self._state = QwenState(
                state.phase, state.message, state.model_path, state.progress, state.busy, self._generation
            )
            self._condition.notify_all()
            self._publish(self._state)

    def configure(self, config: QwenConfig | None) -> None:
        with self._condition:
            if self._closed:
                return
            before = (self._desired.model_path, self._desired.device) if self._desired else None
            after = (config.model_path, config.device) if config else None
            self._desired = config
            if before == after:
                if self._state.phase != "prepared" or config is None:
                    return
            if self._preparing:
                self._cancel.set()
            self._generation += 1
            self._endpoint = ""
            if not self._preparing:
                self._set(
                    QwenState("loading", "読み上げの準備中です。", config.model_path)
                    if config and config.model_path
                    else QwenState(
                        "unprepared" if config else "stopped", "モデルを準備してください。" if config else "停止中"
                    )
                )
            self._condition.notify_all()

    def prepare(self, source: str, device: str) -> None:
        with self._condition:
            if self._closed or self._preparing:
                return
            if device not in {"GPU", "CPU"}:
                raise ValueError("実行デバイスが不正です。")
            self._cancel = Event()
            self._service_stopped.clear()
            self._preparing = True
            self._generation += 1
            self._endpoint = ""
            self._set(QwenState("environment", "利用準備を開始しています。", busy=True))
            self._condition.notify_all()
            self._setup = Thread(target=self._prepare, args=(source, device, self._generation), name="qwen-provision")
            self._setup.start()

    def _prepare(self, source: str, device: str, generation: int) -> None:
        result = None
        state = QwenState("cancelled", "準備を中止しました。再試行できます。")
        try:
            while not self._service_stopped.wait(0.1):
                if self._cancel.is_set():
                    raise Cancelled()
            provision = Provisioner(
                self.root, self.assets, self.service, self._cancel, lambda state: self._set(state, generation)
            )
            model = provision.prepare(source)
            provision.check()
            result = str(model)
            state = QwenState("prepared", "環境とモデルを登録しました。", result)
        except Cancelled:
            pass
        except Exception as exc:
            state = QwenState("error", str(exc))
        finally:
            with self._condition:
                self._preparing = False
                if not self._closed and generation == self._generation:
                    self._generation += 1
                    if self._cancel.is_set():
                        state = QwenState("cancelled", "準備を中止しました。再試行できます。")
                    self._set(state)
                    if result is not None and not self._cancel.is_set():
                        self._prepared(result, device, self._generation)
                elif not self._closed:
                    self._generation += 1
                    config = self._desired
                    self._set(
                        QwenState("loading", "読み上げの準備中です。", config.model_path)
                        if config and config.model_path
                        else QwenState(
                            "unprepared" if config else "stopped", "モデルを準備してください。" if config else "停止中"
                        )
                    )
                self._condition.notify_all()

    def cancel_preparation(self) -> None:
        self._cancel.set()

    def restart(self) -> None:
        with self._condition:
            if self._closed or self._preparing:
                return
            if self._desired is None or not self._desired.model_path:
                self._set(QwenState("unprepared", "モデルを準備してください。"))
                return
            self._generation += 1
            self._endpoint = ""
            self._set(QwenState("loading", "読み上げの準備中です。"))
            self._condition.notify_all()

    def _current(self, generation: int) -> bool:
        with self._condition:
            return not self._closed and not self._preparing and generation == self._generation

    def _manage(self) -> None:
        observed = -1
        process = _native.ManagedProcess()
        try:
            while True:
                with self._condition:

                    def changed(previous: int = observed) -> bool:
                        return self._closed or self._generation != previous

                    self._condition.wait_for(changed)
                    if self._closed:
                        return
                    observed = self._generation
                    config = (
                        None
                        if self._preparing or self._state.phase in {"prepared", "cancelled", "error"}
                        else self._desired
                    )
                process.close()
                self._service_stopped.set()
                if config is None or not config.model_path:
                    continue
                try:
                    if validate_model(Path(config.model_path)) != "openvino":
                        raise ValueError("モデルの利用準備が必要です。「手元のモデルを使う」から登録してください。")
                    provision = Provisioner(self.root, self.assets, self.service, Event(), lambda state: None)
                    if not provision.runtime_ready():
                        raise ValueError("専用環境がありません。モデルの利用準備を行ってください。")
                    token = secrets.token_urlsafe(32)
                    state_file = self.root / "tmp" / f"service-{observed}.json"
                    state_file.unlink(missing_ok=True)
                    cache = provision.directory("cache/compiled/" + config.device)
                    self._set(QwenState("loading", "モデルを読み込んでいます。", config.model_path), observed)
                    if not self._current(observed):
                        continue
                    self._service_stopped.clear()
                    process.start(
                        str(provision.python),
                        [
                            "-I",
                            "-B",
                            "-m",
                            "lvb_qwen3_service.server",
                            "--model",
                            config.model_path,
                            "--device",
                            config.device,
                            "--cache-dir",
                            str(cache),
                            "--state-file",
                            str(state_file),
                            "--token",
                            token,
                        ],
                        str(self.root),
                        provision.environment(),
                        str(self.root / "logs/service.log"),
                    )
                    started = time.monotonic()
                    last_phase = "loading"
                    endpoint = ""
                    while self._current(observed):
                        if not process.is_running():
                            raise RuntimeError(f"Qwenサービスが終了しました（終了コード {process.exit_code()}）。")
                        if not endpoint and state_file.is_file():
                            try:
                                port = json.loads(state_file.read_text(encoding="utf-8"))["port"]
                                if type(port) is not int or not 1 <= port <= 65535:
                                    raise ValueError("サービスのポートが不正です。")
                                endpoint = f"http://127.0.0.1:{port}"
                            except json.JSONDecodeError:
                                pass
                        if endpoint and last_phase != "ready":
                            try:
                                with requests.get(
                                    endpoint + "/health", headers={"Authorization": f"Bearer {token}"}, timeout=(1, 1)
                                ) as response:
                                    response.raise_for_status()
                                    health = response.json()
                            except requests.ConnectionError, requests.Timeout:
                                health = {}
                            phase = health.get("phase", last_phase)
                            if phase == "error":
                                raise RuntimeError(health.get("error", "Qwenの読み込みに失敗しました。"))
                            if phase == "ready" and last_phase != "ready":
                                with self._condition:
                                    if not self._current(observed):
                                        break
                                    self._endpoint, self._token = endpoint, token
                                self._set(QwenState("ready", "使用可能", config.model_path), observed)
                            elif phase == "warming" and last_phase != "warming":
                                self._set(QwenState("warming", "ウォームアップ中です。", config.model_path), observed)
                            last_phase = phase
                        if last_phase != "ready" and time.monotonic() - started > 900:
                            raise TimeoutError("Qwenの起動待ちが15分を超えました。ログを確認して再試行してください。")
                        with self._condition:
                            self._condition.wait(timeout=0.25)
                except Exception as exc:
                    self._set(QwenState("error", str(exc)), observed)
                    process.close()
                    self._service_stopped.set()
        finally:
            process.close()
            self._service_stopped.set()

    def wait_ready(self, cancelled: Event) -> str:
        with self._condition:
            generation = self._generation
            while not cancelled.is_set() and not self._closed:
                if generation != self._generation:
                    raise Cancelled("Qwenの構成が変更されました。")
                if self._state.phase == "ready" and self._endpoint:
                    return self._endpoint
                if self._state.phase in {"error", "unprepared", "cancelled", "stopped"}:
                    raise RuntimeError(self._state.message)
                self._condition.wait(timeout=0.1)
        raise Cancelled("読み上げを中止しました。")

    def connection(self) -> tuple[str, dict[str, str]]:
        with self._condition:
            if self._state.phase != "ready" or not self._endpoint:
                raise RuntimeError("Qwenは準備中です。")
            return self._endpoint, {"Authorization": f"Bearer {self._token}"}

    def read_log(self) -> str:
        parts = []
        for name in ("setup.log", "service.log"):
            path = self.root / "logs" / name
            if path.is_file():
                with path.open("rb") as source:
                    source.seek(max(0, path.stat().st_size - 65536))
                    parts.append(name + "\n" + source.read().decode("utf-8", errors="replace"))
        return "\n\n".join(parts) or "ログはまだありません。"

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._generation += 1
            self._cancel.set()
            self._condition.notify_all()
        self._worker.join()
        if self._setup:
            self._setup.join()
