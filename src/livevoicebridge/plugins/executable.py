"""Wire adapter for an executable TTS provider."""

import base64
import json
from dataclasses import asdict
from threading import Lock
from uuid import uuid4

from livevoicebridge import _native
from livevoicebridge.plugins.api import PluginContext
from livevoicebridge.plugins.contracts import EngineCapabilities, EngineConfig, SettingField, Speaker, SpeechControls
from livevoicebridge.plugins.provider import Provider


class Rpc:
    def __init__(self, context: PluginContext, executable: str, args: list[str]):
        self._process = _native.PluginProcess()
        log = context.data / "stderr.log"
        if not log.resolve().is_relative_to(context.data.resolve()):
            raise ValueError("ログ保存先がプラグイン保存領域の外を指しています。")
        self._process.start(executable, args, str(context.root), str(log))
        self._lock = Lock()
        self._closed = False
        self._context = context

    def call(self, method: str, params: dict, timeout: float = 30) -> object:
        with self._lock:
            if self._closed:
                raise RuntimeError("外部プラグインは終了しています。")
            identifier = uuid4().hex
            response_limit = 1024 * 1024
            if method == "synthesize":
                response_limit = ((params["max_bytes"] + 65536 + 2) // 3) * 4 + 8192
            try:
                reply = json.loads(
                    self._process.exchange(
                        json.dumps(
                            {
                                "version": 1,
                                "id": identifier,
                                "method": method,
                                "params": params,
                            },
                            ensure_ascii=False,
                            allow_nan=False,
                        ),
                        timeout,
                        response_limit,
                    )
                )
                if (
                    not isinstance(reply, dict)
                    or type(reply.get("version")) is not int
                    or reply["version"] != 1
                    or reply.get("id") != identifier
                    or (("result" in reply) == ("error" in reply))
                ):
                    raise ValueError("外部プラグインの応答形式・版・要求IDが不正です。")
                if "error" in reply:
                    error = reply["error"]
                    if (
                        not isinstance(error, dict)
                        or not isinstance(error.get("message"), str)
                        or not isinstance(error.get("code"), str)
                    ):
                        raise ValueError("外部プラグインのエラー形式が不正です。")
                    raise RuntimeError(error["message"])
                return reply["result"]
            except Exception:
                self._closed = True
                self._process.close()
                raise

    def close(self) -> None:
        if not self._closed:
            try:
                self.call("close", {}, 2)
            except Exception:
                self._context.logger.exception("外部プラグインの終了通知に失敗しました。")
            finally:
                self._closed = True
                self._process.close()


class ExecutableEngine:
    def __init__(self, rpc: Rpc, config: EngineConfig, context: PluginContext, capabilities: EngineCapabilities):
        self._rpc, self._config, self._context = rpc, config, context
        self.capabilities = capabilities

    def ensure_ready(self) -> None:
        self._rpc.call("prepare", {"config": asdict(self._config)})

    def speakers(self) -> tuple[Speaker, ...]:
        result = self._rpc.call("speakers", {"config": asdict(self._config)})
        if not isinstance(result, list):
            raise ValueError("話者一覧が配列ではありません。")
        speakers = []
        for item in result:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("identifier"), str)
                or not item["identifier"]
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("style", "通常"), str)
            ):
                raise ValueError("話者情報が不正です。")
            speakers.append(Speaker(item["identifier"], item["name"], item.get("style", "通常")))
        return tuple(speakers)

    def synthesize(self, text: str, controls: SpeechControls, config: EngineConfig, max_bytes: int):
        result = self._rpc.call(
            "synthesize",
            {
                "text": text,
                "controls": asdict(controls),
                "config": asdict(config),
                "max_bytes": max_bytes,
            },
            120,
        )
        if not isinstance(result, dict) or not isinstance(result.get("wav_base64"), str):
            raise ValueError("合成音声の応答形式が不正です。")
        encoded = result["wav_base64"]
        if len(encoded) > ((max_bytes + 65536 + 2) // 3) * 4:
            raise ValueError("合成音声が容量上限を超えました。")
        return self._context.decode_wav(base64.b64decode(encoded, validate=True), controls, max_bytes)

    def send(self, text: str, controls: SpeechControls, config: EngineConfig) -> None:
        self._rpc.call("send", {"text": text, "controls": asdict(controls), "config": asdict(config)}, 120)

    def close(self) -> None:
        self._rpc.close()


def executable_provider(context: PluginContext, executable: str, args: list[str]) -> Provider:
    def connect() -> Rpc:
        return Rpc(context, executable, args)

    rpc = connect()
    try:
        description = rpc.call(
            "register", {"api_version": 1, "plugin_id": context.id, "data_directory": str(context.data)}
        )
    finally:
        rpc.close()
    if not isinstance(description, dict) or description.get("id") != context.id:
        raise ValueError("外部プラグインの登録情報が不正です。")
    capability = description["capabilities"]
    if (
        not isinstance(capability, dict)
        or type(capability.get("local_audio")) is not bool
        or type(capability.get("completion_known")) is not bool
        or not isinstance(capability.get("controls"), list)
        or not all(isinstance(item, str) for item in capability["controls"])
    ):
        raise ValueError("TTSの対応機能が不正です。")
    capabilities = EngineCapabilities(
        frozenset(capability["controls"]), capability["local_audio"], capability["completion_known"]
    )
    fields = tuple(
        SettingField(**{**item, "choices": tuple(item.get("choices", ()))}) for item in description.get("fields", [])
    )

    def create(config: EngineConfig) -> ExecutableEngine:
        connection = connect()
        try:
            connection.call(
                "register", {"api_version": 1, "plugin_id": context.id, "data_directory": str(context.data)}
            )
            return ExecutableEngine(connection, config, context, capabilities)
        except Exception:
            connection.close()
            raise

    return Provider(
        context.id, str(description["name"]), capabilities, fields, create, str(description.get("speaker_id", "0"))
    )
