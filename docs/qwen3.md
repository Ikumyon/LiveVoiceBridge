# Qwen3-TTS 0.6B CustomVoice

コメント読み上げ用に、OpenVINOの専用プロセスへHTTP接続します。モデルは起動時に一度読み込み、ウォームアップ完了後に待ち受けます。
アプリ本体のPython環境にはOpenVINO GenAIやPyTorchをインストールしません。

この実装はQwen3-TTS対応を含む公式nightly版OpenVINO GenAI（2026.5.0.0.dev20261022）と、Optimum Intelの固定コミットを使います。通常版2026.4の構成では動作しません。

## 環境構築

WindowsのPython 3.12を使用します。以下はプロジェクトのルートで実行してください。

```powershell
py -3.12 -m venv services/qwen3/.venv
& .\services\qwen3\.venv\Scripts\python.exe -m pip install -e services/qwen3 --extra-index-url https://storage.openvinotoolkit.org/simple/wheels/nightly
```

モデル変換にはOptimum IntelとPyTorch等も必要です。以下で変換用依存関係を導入します。
[OpenVINOの公式手順](https://openvinotoolkit.github.io/openvino.genai/docs/samples/python/speech_generation/)に沿ったモデル変換コマンドを使用します。

```powershell
& .\services\qwen3\.venv\Scripts\python.exe -m pip install -e "services/qwen3[export]" --extra-index-url https://storage.openvinotoolkit.org/simple/wheels/nightly --extra-index-url https://download.pytorch.org/whl/cpu
& .\services\qwen3\.venv\Scripts\optimum-cli.exe export openvino --model Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --task text-to-audio --weight-format fp16 --trust-remote-code models/qwen3-tts-0.6b-customvoice-ov
& .\services\qwen3\.venv\Scripts\python.exe -m lvb_qwen3_service.prepare_tokenizer models/qwen3-tts-0.6b-customvoice-ov
```

`--trust-remote-code` はモデルリポジトリ内のPythonコード実行を許可する指定です。
変換用のPyTorch等はサービス実行には不要です。変換済みモデルは配布物に同梱しません。
固定したOptimum Intel版はテキストトークナイザーのIRを出力しないため、`prepare_tokenizer.py` で生成し、日本語を含む入力のトークン列が元のトークナイザーと一致することを検証します。

## 起動とアプリ設定

```powershell
& .\services\qwen3\.venv\Scripts\python.exe -m lvb_qwen3_service.server --model models/qwen3-tts-0.6b-customvoice-ov --device GPU
Invoke-RestMethod http://127.0.0.1:50040/health
```

`Ready` が出るまで待ちます。初回のGPUコンパイルには時間がかかる場合があります。
`health` の `device` が `GPU`、`ready` が `true` になったことを確認してください。
GPUが使えない場合は起動エラーになります。CPUへの自動切り替えは行いません。
比較測定する場合だけ明示的に `--device CPU` で起動します。NPU実行は提供しません。

アプリの設定で `QWEN3` を選び、接続URLを `http://127.0.0.1:50040` に設定します。
「接続確認」で話者一覧を取得し、標準の日本語話者 `ono_anna` を選びます。
サービスは手動起動・手動終了方式です。アプリ停止後もモデルは常駐し、サービス側のCtrl+Cで終了します。

話者IDは本サービス固有です。`0=ono_anna`、`1=vivian`、`2=serena`、`3=uncle_fu`、`4=dylan`、`5=eric`、`6=ryan`、`7=aiden`、`8=sohee` です。すべて日本語を指定して生成します。

## 対応範囲と測定

- 文単位のWAV生成です。音声の途中から再生するストリーミングには未対応です。
- アプリ側の辞書・絵文字変換・文分割・再生中の後続合成・音声エフェクトを使います。
- 音量は0〜2倍に対応します。速度・音程・抑揚・間隔の変更は未対応です。未対応のコメント制御は通知して省略し、その文の読み上げを継続します。
- 0.6B CustomVoiceには自然文による話し方の指示を送りません。
- 1リクエストは2000文字までです。最大文字数はまず50文字に設定してください。
- 同時合成は1件です。サービス処理中の別リクエストは429を返します。アプリは合成を直列に送ります。
- サービスのログに生成音声の秒数と合成所要秒数を記録します。所要秒数÷音声秒数が1未満なら、その文では再生より速く合成できています。
- 16GB環境での常用可否は実測が必要です。コメントの連投による読み上げ待ちは、合成が速くても再生時間に応じて増加します。

設定はアプリ配置先の `data/config.json`（schema_version 3）を使用します。モデルは配置先内の `models/` に置き、サービスにはそのパスを指定します。エンジンごとに固有の項目を保持し、旧設定の自動移行は行いません。

## 実機測定（2026年10月23日）

Core Ultra 7 255H / Arc 140T / Windows 11 / RAM 16GB、FP16モデル、上記のnightly版で測定しました。
起動時のウォームアップ後、アプリのQwen3アダプターからHTTPで各文を送り、WAV受信完了までを測っています。

| 入力 | 合成・受信時間 | 生成音声の長さ | 所要時間÷音声長 |
| --- | ---: | ---: | ---: |
| こんにちは。 | 19.197秒 | 2.960秒 | 6.485 |
| コメントありがとうございます。 | 21.885秒 | 4.720秒 | 4.637 |
| 今日はいい天気ですね。配信を楽しんでください。 | 22.133秒 | 4.640秒 | 4.770 |

GPUで生成できることは確認しましたが、この構成では再生より合成が遅く、コメントを続けて読む用途に十分な速度は出ていません。
モデルは生成ごとに音声長が変わるため、これらは各1回の測定値です。音声ストリーミングを追加しても、合成全体の速度不足が解消するとは限りません。
「コメントありがとうございます。」の試聴用WAVは開発環境の `models/qwen3-comment-sample.wav` に保存しています。
