# LiveVoiceBridge 日本語TTS組み込み仕様書

Version: 0.1  
Date: 2026-06-24  
Target: LiveVoiceBridge-main

---

## 1. 目的

LiveVoiceBridgeに、ローカル日本語TTSエンジンとして **sherpa-onnx Supertonic 3 Japanese INT8** を追加する。

既存のVOICEVOX / COEIROINK / 棒読みちゃんに加えて、ネットワークAPIに依存しないローカルTTSを内蔵し、Linux環境でも軽く動作する読み上げ基盤を作る。

最終的な実行方針は次の通り。

```text
メインTTS:
  sherpa-onnx Supertonic 3 Japanese INT8

デバイス優先順:
  NPU → GPU → CPU

```

---

## 2. 対象範囲

### 対象に含める

- `sherpa_supertonic` TTSエンジンの追加
- 既存TTS抽象化 `BaseTTSEngine` への統合
- `factory.py` への登録
- 設定ファイルへの追加
- 設定画面へのエンジン項目追加
- Supertonic 3モデルフォルダ指定
- 話者ID指定
- Linuxでの利用を前提にした依存関係追加
- 将来のNPU/GPU/CPU自動切替に備えた設定項目

### 初期実装では対象外

- OpenVINOによる完全なNPU実行
- モデル自動ダウンロード
- 話者ごとの詳細音質調整UI
- 音声キャッシュの高度化
- ストリーミングTTS

ただし、将来拡張できるように設定項目と構造は用意する。

---

## 3. 現在の構成

現在のLiveVoiceBridgeには、すでにTTS差し替え用の構造がある。

```text
LiveVoiceBridge-main/
├─ main.py
├─ core/
│  ├─ app_config.py
│  ├─ comment_processing.py
│  ├─ settings_dialog.py
│  ├─ workers/
│  │  └─ speech.py
│  ├─ audio/
│  │  └─ playback.py
│  └─ tts/
│     ├─ base.py
│     ├─ factory.py
│     ├─ runtime.py
│     └─ engines/
│        ├─ voicevox.py
│        ├─ coeiroink.py
│        └─ bouyomichan.py
```

既存の読み上げ処理は次の流れ。

```text
YouTubeコメント
  ↓
clean_comment()
  ↓
parse_comment_into_segments()
  ↓
SpeechWorker
  ↓
replace_words()
  ↓
replace_emojis()
  ↓
tts_engine.synthesize_wav()
  ↓
一時WAV保存
  ↓
apply_audio_effects()
  ↓
play_wav()
```

この構成を維持し、新しいTTSエンジンとして `sherpa_supertonic.py` を追加する。

---

## 4. 全体アーキテクチャ

```text
┌──────────────────────────────┐
│ YouTube Live コメント          │
└───────────────┬──────────────┘
                ↓
┌──────────────────────────────┐
│ comment_processing.py         │
│ ・HTML解除                     │
│ ・URL置換                      │
│ ・最大文字数制限                │
│ ・速度/音量/声コマンド解析       │
└───────────────┬──────────────┘
                ↓
┌──────────────────────────────┐
│ SpeechWorker                  │
│ ・読み上げキュー処理            │
│ ・ユーザー辞書置換              │
│ ・絵文字読み変換                │
└───────────────┬──────────────┘
                ↓
┌────────────────────────────────────────┐
│ TTS Engine Factory                      │
│ voicevox / coeiroink / bouyomichan /    │
│ sherpa_supertonic                       │
└───────────────┬────────────────────────┘
                ↓
┌────────────────────────────────────────┐
│ SherpaSupertonicEngine                  │
│ main: sherpa-onnx Supertonic 3 INT8     │
│ fallback: pyopenjtalk                   │
│ lock: ローカルTTSの多重実行制御          │
└───────────────┬────────────────────────┘
                ↓
┌──────────────────────────────┐
│ playback.py                   │
│ ・エコー                       │
│ ・やまびこ                     │
│ ・左右パン                     │
│ ・WAV再生                      │
└──────────────────────────────┘
```

---

## 5. 追加するTTSエンジン

### 5.1 エンジン名

内部名:

```text
sherpa_supertonic
```

UI表示名:

```text
SHERPA_SUPERTONIC
```

または短く表示する場合:

```text
SUPERTONIC 3
```

---

### 5.2 追加ファイル

```text
core/tts/engines/sherpa_supertonic.py
```

役割:

- Supertonic 3モデルの読み込み
- 音声合成
- WAV bytesの返却
- 話者リストの返却
- pyopenjtalk fallback
- ローカルモデルの存在確認
- 多重実行制御

---

### 5.3 変更ファイル

```text
core/tts/factory.py
core/tts/runtime.py
core/tts/base.py
core/app_config.py
core/settings_dialog.py
requirements.txt
README.md
usage.md
```

初期実装で最低限必要な変更は次の4つ。

```text
core/tts/engines/sherpa_supertonic.py
core/tts/factory.py
core/app_config.py
requirements.txt
```

---

## 6. 設定仕様

### 6.1 config.json追加項目

`DEFAULT_CONFIG` に次を追加する。

```json
{
  "tts_engine": "sherpa_supertonic",
  "sherpa_supertonic": {
    "url": "local://sherpa-supertonic",
    "path": "models/sherpa-onnx-supertonic-3-ja-int8",
    "speaker_id": 0,
    "sample_rate": 24000,
    "speed": 1.0,
    "num_steps": 8,
    "num_threads": 2,
    "fallback_engine": "pyopenjtalk",
    "enable_fallback": true,
    "device_policy": "auto",
    "device_priority": ["NPU", "GPU", "CPU"],
    "backend": "sherpa_onnx"
  }
}
```

### 6.2 各項目の意味

| 項目 | 型 | 内容 |
|---|---|---|
| `url` | string | 既存UI互換用。ローカルTTSなので `local://sherpa-supertonic` を使う |
| `path` | string | Supertonic 3モデルフォルダ |
| `speaker_id` | int | 話者ID |
| `sample_rate` | int | 出力サンプルレート。基本は24000 |
| `speed` | float | 読み上げ速度 |
| `num_steps` | int | 生成ステップ数。軽さ優先なら8前後 |
| `num_threads` | int | CPU実行時のスレッド数 |
| `fallback_engine` | string | 失敗時の補助TTS |
| `enable_fallback` | bool | fallbackを使うか |
| `device_policy` | string | `auto` / `fixed` |
| `device_priority` | list | 将来のデバイス優先順 |
| `backend` | string | 初期は `sherpa_onnx`。将来 `openvino` を追加可能 |

---

## 7. モデル配置仕様

標準配置:

```text
LiveVoiceBridge-main/
└─ models/
   └─ sherpa-onnx-supertonic-3-ja-int8/
      ├─ duration_predictor.int8.onnx
      ├─ text_encoder.int8.onnx
      ├─ vector_estimator.int8.onnx
      ├─ vocoder.int8.onnx
      ├─ tts.json
      ├─ unicode_indexer.bin
      └─ voice.bin
```

モデルフォルダは設定画面から変更可能にする。

---

## 8. BaseTTSEngine拡張仕様

現在の `BaseTTSEngine` はHTTP API型TTSを前提としている。ローカルTTSを扱うため、次のクラス変数を追加する。

```python
class BaseTTSEngine(ABC):
    DEFAULT_URL = ""
    DISPLAY_NAME = "TTS"
    REQUIRES_URL = True
    IS_LOCAL_ENGINE = False
```

`SherpaSupertonicEngine` では次のようにする。

```python
class SherpaSupertonicEngine(BaseTTSEngine):
    DEFAULT_URL = "local://sherpa-supertonic"
    DISPLAY_NAME = "Supertonic 3"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True
```

これにより `runtime.py` 側でURL必須チェックを回避できる。

---

## 9. SherpaSupertonicEngine仕様

### 9.1 クラス概要

```python
class SherpaSupertonicEngine(BaseTTSEngine):
    def __init__(self, url: str, exe_path: str = ""):
        ...

    def is_running(self) -> bool:
        ...

    def ensure_running(self) -> bool:
        ...

    def synthesize_wav(
        self,
        text: str,
        speed: float = None,
        pitch: float = None,
        volume: float = None,
        speaker_id: int = None,
    ) -> bytes | None:
        ...

    def get_speakers(self) -> list[dict] | None:
        ...
```

---

### 9.2 `is_running()`

ローカルTTSなのでHTTP接続は行わない。

確認内容:

- モデルフォルダが存在する
- 必須ファイルが存在する
- Pythonライブラリ `sherpa_onnx` をimportできる

戻り値:

```text
True  = モデル実行可能
False = モデル未配置、依存不足、読み込み不能
```

---

### 9.3 `ensure_running()`

Supertonic 3は外部プロセスではないため、プロセス起動はしない。

処理:

```text
1. モデルフォルダ確認
2. sherpa_onnx import確認
3. TTSインスタンス初期化
4. 成功したらTrue
5. 失敗したらFalse
```

---

### 9.4 `synthesize_wav()`

入力:

```text
text       読み上げテキスト
speed      速度
pitch      音程。初期実装では無視してよい
volume     音量。生成後のWAV音量調整に使う
speaker_id 話者ID
```

出力:

```text
WAV bytes
```

失敗時:

```text
None
```

ただし `enable_fallback = true` の場合は、Supertonic 3失敗後に `pyopenjtalk` で再合成する。

---

### 9.5 `get_speakers()`

VOICEVOX互換の形式で返す。

```python
[
    {
        "name": "Supertonic 3 Japanese",
        "styles": [
            {"name": "Speaker 0", "id": 0},
            {"name": "Speaker 1", "id": 1},
            {"name": "Speaker 2", "id": 2},
            {"name": "Speaker 3", "id": 3},
            {"name": "Speaker 4", "id": 4},
            {"name": "Speaker 5", "id": 5},
            {"name": "Speaker 6", "id": 6},
            {"name": "Speaker 7", "id": 7},
            {"name": "Speaker 8", "id": 8},
            {"name": "Speaker 9", "id": 9}
        ]
    }
]
```

話者数がモデル設定ファイルから取得できる場合は、固定値ではなくモデルから読む。

---



---

## 11. デバイス選択仕様

### 11.1 初期実装

初期実装では、安定性を優先してCPU実行にする。

```text
backend = sherpa_onnx
provider = cpu
```

### 11.2 将来実装

将来、OpenVINO対応を追加する。

```text
device_priority = ["NPU", "GPU", "CPU"]
```

実行手順:

```text
1. NPUを試す
2. 失敗したらGPUを試す
3. 失敗したらCPUを試す
4. 全部失敗したらpyopenjtalk
```

### 11.3 DeviceSelector追加案

将来追加するファイル:

```text
core/tts/device_selector.py
```

役割:

- OpenVINO利用可能デバイスの確認
- NPU/GPU/CPU優先順の管理
- 失敗したデバイスの一時的な無効化
- ログ出力

---

## 12. 並列処理仕様

現在の `SpeechWorker` は `ThreadPoolExecutor(max_workers=8)` を使っている。

HTTP API型TTSでは許容できるが、ローカルニューラルTTSでは重くなりやすい。

### 12.1 初期対応

`SherpaSupertonicEngine` 内にロックを持つ。

```python
self._lock = threading.Lock()

with self._lock:
    audio = self.tts.generate(text, gen_config)
```

### 12.2 将来対応

設定にTTS並列数を追加する。

```json
{
  "sherpa_supertonic": {
    "max_workers": 1
  }
}
```

または `SpeechWorker` 側でエンジンごとに並列数を切り替える。

```text
VOICEVOX: 8
COEIROINK: 8
BOUYOMICHAN: 1
SHERPA_SUPERTONIC: 1
```

---

## 13. 前処理仕様

### 13.1 現在の順序

```text
replace_words()
  ↓
replace_emojis()
  ↓
synthesize_wav()
```

この順序を維持する。

理由:

- ユーザー辞書が絵文字読みより優先される
- 既存の教育/忘却コマンドと相性が良い
- TTSエンジン側に不要な辞書機能を持たせずに済む

### 13.2 絵文字読み

既存の `emoji.demojize(language="ja")` を使う。

例:

```text
😊 → にこにこ
🔥 → 火
👏 → 拍手
```

ユーザー辞書で上書き可能にする。

```text
🔥 → めらめら
👏 → ぱちぱち
```

---

## 14. UI仕様

### 14.1 エンジン選択

設定画面のTTSエンジン選択に追加する。

```text
VOICEVOX
COEIROINK
BOUYOMICHAN
SHERPA_SUPERTONIC
```

### 14.2 Supertonic選択時の表示

短期実装では既存UIを流用する。

```text
接続URL:
  local://sherpa-supertonic

実行ファイル:
  models/sherpa-onnx-supertonic-3-ja-int8
```

長期実装では表示名を変える。

```text
モデルフォルダ:
  models/sherpa-onnx-supertonic-3-ja-int8

デバイス優先順位:
  NPU → GPU → CPU

フォールバック:
  pyopenjtalk
```

### 14.3 接続テスト

Supertonic 3では「接続テスト」ではなく「モデル確認」として動作する。

確認内容:

- モデルフォルダ存在
- 必須ファイル存在
- `sherpa_onnx` import成功
- 話者リスト取得成功

成功ログ例:

```text
Supertonic 3モデルを確認しました。
話者リストを更新しました。
```

失敗ログ例:

```text
Supertonic 3モデルが見つかりません。
models/sherpa-onnx-supertonic-3-ja-int8 を確認してください。
```

---

## 15. 依存関係仕様

`requirements.txt` に追加する。

```text
emoji
sherpa-onnx
numpy
soundfile
pyopenjtalk
```

現在 `comment_processing.py` で `emoji` をimportしているため、`emoji` は必須。

将来OpenVINO対応を行う場合の候補:

```text
openvino
onnxruntime-openvino
```

ただし初期実装では入れなくてよい。

---

## 16. ログ仕様

### 16.1 起動時

```text
[Supertonic3] モデル確認中: models/sherpa-onnx-supertonic-3-ja-int8
[Supertonic3] モデル読み込み成功
```

### 16.2 合成時

```text
[Supertonic3] 音声合成開始: speaker=0 speed=1.0
[Supertonic3] 音声合成成功: 24000Hz, xxxx samples
```

### 16.3 fallback時

```text
[Supertonic3] 合成失敗: <error>
[Supertonic3] pyopenjtalk fallbackを実行します
```

### 16.4 完全失敗時

```text
[Supertonic3] pyopenjtalk fallbackも失敗しました
```

---

## 17. エラー処理仕様

| 状態 | 動作 |
|---|---|
| モデルフォルダなし | `is_running()` はFalse |
| 必須ファイル不足 | エラー表示、fallback可能ならpyopenjtalk |
| `sherpa_onnx` 未導入 | エラー表示、fallback可能ならpyopenjtalk |
| 合成例外 | pyopenjtalk fallback |
| pyopenjtalk未導入 | None返却 |
| 空文字 | None返却 |
| 話者ID範囲外 | 0に丸める、または最も近いIDにする |

---

## 18. 実装段階

### Phase 1: CPU版Supertonic 3追加

目的:

```text
LiveVoiceBridge内でSupertonic 3を鳴らす
```

作業:

```text
1. sherpa_supertonic.py追加
2. factory.pyに登録
3. app_config.pyに設定追加
4. requirements.txt更新
5. CPUでテストコメントを読み上げ
```

---

### Phase 2: pyopenjtalk fallback追加

目的:

```text
Supertonic 3失敗時も読み上げが止まらないようにする
```

作業:

```text
1. fallback関数追加
2. WAV bytes変換処理追加
3. ログ追加
4. pyopenjtalk未導入時のエラー処理追加
```

---

### Phase 3: UI調整

目的:

```text
設定画面からSupertonic 3を選びやすくする
```

作業:

```text
1. エンジン選択にSHERPA_SUPERTONIC追加
2. URL欄をローカルTTS向けに調整
3. モデルフォルダ選択ボタン追加
4. 接続テスト表示をモデル確認に変更
```

---

### Phase 4: NPU/GPU/CPU対応

目的:

```text
Intel 255HなどのNPU搭載環境で、NPU → GPU → CPUの順に使う
```

作業:

```text
1. device_selector.py追加
2. OpenVINO利用可能デバイス確認
3. NPU/GPU/CPU try-fallback実装
4. 失敗時にCPUまたはpyopenjtalkへ退避
```

---

## 19. 受け入れ条件

### 必須

- `tts_engine = sherpa_supertonic` でアプリが起動する
- テストコメントがSupertonic 3で読み上げられる
- 既存のVOICEVOX / COEIROINK / 棒読みちゃんが壊れない
- 辞書置換がSupertonic 3にも効く
- 絵文字読みがSupertonic 3にも効く
- Supertonic 3モデルがない場合にエラーで落ちない
- fallback有効時、pyopenjtalkで最低限読み上げられる

### 推奨

- 複数コメント連続時にクラッシュしない
- Supertonic 3実行中に停止ボタンを押しても安全に止まる
- 話者IDを設定画面から変更できる
- Linuxで実行できる

---

## 20. 最小実装イメージ

```text
core/tts/engines/sherpa_supertonic.py
```

```python
from __future__ import annotations

import io
import wave
import threading
from pathlib import Path

import numpy as np

from core.tts.base import BaseTTSEngine


class SherpaSupertonicEngine(BaseTTSEngine):
    DEFAULT_URL = "local://sherpa-supertonic"
    DISPLAY_NAME = "Supertonic 3"
    REQUIRES_URL = False
    IS_LOCAL_ENGINE = True

    REQUIRED_FILES = [
        "duration_predictor.int8.onnx",
        "text_encoder.int8.onnx",
        "vector_estimator.int8.onnx",
        "vocoder.int8.onnx",
        "tts.json",
        "unicode_indexer.bin",
        "voice.bin",
    ]

    def __init__(self, url: str, exe_path: str = ""):
        super().__init__(url or self.DEFAULT_URL, exe_path)
        self.model_dir = Path(exe_path or "models/sherpa-onnx-supertonic-3-ja-int8")
        self._tts = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._check_model_files()

    def ensure_running(self) -> bool:
        if not self._check_model_files():
            return False
        return self._load_tts()

    def _check_model_files(self) -> bool:
        return self.model_dir.exists() and all(
            (self.model_dir / name).exists() for name in self.REQUIRED_FILES
        )

    def _load_tts(self) -> bool:
        if self._tts is not None:
            return True
        try:
            import sherpa_onnx
            # 実際のsherpa_onnx初期化コードをここに実装する
            self._tts = "loaded"
            return True
        except Exception:
            self._tts = None
            return False

    def synthesize_wav(self, text: str, speed=None, pitch=None, volume=None, speaker_id=None) -> bytes | None:
        if not text.strip():
            return None
        try:
            if not self.ensure_running():
                raise RuntimeError("Supertonic 3 is not ready")
            with self._lock:
                # 実際のSupertonic 3合成処理をここに実装する
                pass
        except Exception:
            return self._fallback_pyopenjtalk(text)

    def _fallback_pyopenjtalk(self, text: str) -> bytes | None:
        try:
            import pyopenjtalk
            samples, sr = pyopenjtalk.tts(text)
            samples = np.asarray(samples)
            if samples.dtype != np.int16:
                samples = np.clip(samples, -32768, 32767).astype(np.int16)
            return self._pcm_to_wav_bytes(samples, sr)
        except Exception:
            return None

    def _pcm_to_wav_bytes(self, samples: np.ndarray, sr: int) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(samples.tobytes())
        return buf.getvalue()

    def get_speakers(self) -> list[dict] | None:
        return [{
            "name": "Supertonic 3 Japanese",
            "styles": [{"name": f"Speaker {i}", "id": i} for i in range(10)]
        }]
```

---

## 21. 実装上の注意

- `exe_path` を一時的にモデルフォルダとして使う場合、UI上の表示名と実態がずれる。
- 将来的には `path` を「実行ファイル」ではなく「モデルフォルダ」として扱えるようにする。
- ローカルニューラルTTSは多重実行で重くなりやすいため、エンジン内ロックを必須にする。
- `pitch` はSupertonic 3側で直接対応しない可能性があるため、初期実装では無視してよい。
- `volume` はWAV生成後に振幅調整する方式でもよい。
- `emoji` は既にコードで使われているため、requirementsに必ず追加する。

---

## 22. 結論

LiveVoiceBridgeの現在の設計は、TTSエンジン差し替えに向いている。

そのため、Supertonic 3は外部アプリとしてではなく、次のように内部エンジンとして追加する。

```text
core/tts/engines/sherpa_supertonic.py
```

最初はCPUで安定動作させ、次にpyopenjtalk fallback、最後にOpenVINOによるNPU/GPU/CPU切替へ進める。

推奨ロードマップ:

```text
Phase 1: Supertonic 3 CPU版
Phase 2: pyopenjtalk fallback
Phase 3: 設定画面対応
Phase 4: NPU → GPU → CPU対応
```
