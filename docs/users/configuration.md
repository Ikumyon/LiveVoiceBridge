# 設定と保存

[仕様書一覧](../README.md)

## ポータブル配置

配布起動では実行ファイルの親、ソース起動ではリポジトリ直下を配置先とします。
作業ディレクトリやユーザーのAppDataには切り替えません。
アプリ管理下の書き込みは配置先内に限定し、レジストリ書き込み、権限変更、常駐サービス登録は行いません。

```text
LiveVoiceBridge/
├── LiveVoiceBridge.exe または LiveVoiceBridge
├── _internal/
└── data/
    ├── config.json
    ├── dictionary.db
    ├── sounds/
    └── qwen/
        ├── runtime/
        ├── downloads/
        ├── models/
        ├── cache/
        ├── tmp/
        └── logs/
```

Qwen領域は準備時に作成します。設定保存中には `config.json.tmp`、
SQLite更新中にはDBと同じ場所にジャーナルなどを使用します。SQLの一時領域はメモリです。
合成音声、コメント一覧、通常の画面ログ、アバターは永続保存しません。
Qwenの詳細ログは `data/qwen/logs/` に保存します。

アプリ終了後、配置フォルダをまとめてバックアップ・移動できます。
外部TTS実行ファイルや参照型のQwenモデルは同梱されないため、移動先でも参照可能なパスが必要です。
APIキーも設定JSONへ平文で保存します。

## 設定ファイルの読み書き

`data/config.json` はUTF-8のJSONです。初回は既定値で作成します。
通常は設定画面から編集します。手動編集する場合はアプリを終了してから行ってください。
保存は検証後に同じディレクトリの一時ファイルへ書き、原子的な置換で確定します。

現在の `schema_version` は3です。トップレベルは次の構造です。

| キー | 内容 |
| --- | --- |
| `schema_version` | 整数3 |
| `streaming` | YouTube接続・読み上げ対象 |
| `speech` | 使用エンジン、全エンジン設定、読み上げ順序、キュー上限 |
| `presentation` | コメント表示、PiP、メトリクス表示 |
| `dictionary` | 編集グループ |
| `application` | 更新確認、IME、プラグインの有効状態 |
| `resources` | 保持上限 |

各オブジェクトはモデル定義の型に従います。
不明なキーや型違い、未対応スキーマを黙って既定値へ戻す処理はありません。
整数欄では真偽値や小数を受け付けず、浮動小数欄は整数・小数を受け付けます。
一部の省略可能項目にはモデルの既定値を使用します。正確な省略可否は末尾のモデル・デコード実装を参照してください。

## 配信・読み上げ

| パス | 初期値 | 意味・制約 |
| --- | --- | --- |
| `streaming.youtube_api_key` | 空文字 | YouTube APIキー |
| `streaming.youtube_source` | 空文字 | 配信URLまたは動画ID |
| `streaming.skip_history` | true | 最初の応答を読み上げ対象外にする |
| `streaming.read_paid_events` | true | 有料扱いの対象イベントを読む |
| `speech.active_engine` | voicevox | 内蔵または外部TTSの文字列ID |
| `speech.queue_limit` | 100 | 1～10,000 |
| `speech.read_blocks` | 本文1個 | 1個以上のブロック配列 |
| `dictionary.active_group` | デフォルト | 編集画面の選択グループ |

`speech.engines` はエンジンIDが重複しない設定配列です。
各要素は `engine_id`、文字列の `speaker_id`、`max_length`、`settings` を持ちます。
プラグインを削除・無効化しても設定を保持し、再導入時に引き継ぎます。
ブロックはたとえば `{"kind": "message", "value": ""}` で表し、
種類には `author`・`message`・`text` を使用します。
固定テキストは `value` を連結します。

### エンジン設定

| 項目 | VOICEVOX | COEIROINK | 棒読みちゃん | Qwen3 |
| --- | --- | --- | --- | --- |
| `engine_id` | voicevox | coeiroink | bouyomichan | qwen3 |
| `url` | http://127.0.0.1:50021 | http://127.0.0.1:50032 | 127.0.0.1:50001 | 項目なし |
| `executable_path` | 空文字 | 空文字 | 空文字 | 項目なし |
| `speaker_id` | "1" | "1" | "0" | "0" |
| `max_length` | 50 | 50 | 50 | 50 |
| `speed` | 1.0 | 1.0 | -1 | 項目なし |
| `pitch` | 0.0 | 0.0 | -1 | 項目なし |
| `volume` | 1.0 | 1.0 | -1 | 1.0 |
| `intonation` | 1.0 | 1.0 | 項目なし | 項目なし |
| `pause_length` | 1.0 | 1.0 | 項目なし | 項目なし |
| `pre_phoneme_length` | 0.1 | 0.1 | 項目なし | 項目なし |
| `post_phoneme_length` | 0.1 | 0.1 | 項目なし | 項目なし |
| `model_path` | 項目なし | 項目なし | 項目なし | 空文字 |
| `device` | 項目なし | 項目なし | 項目なし | GPU |

上表の `engine_id`・`speaker_id`・`max_length` 以外は `settings` 内に保存します。
設定検証では最大文字数は `-1` または正の整数、話者IDは空でない文字列です。
内蔵TTSはプラグイン側で話者IDを整数へ変換して検証します。
Qwenは話者ID 0～8、音量0～2、デバイス `GPU` または `CPU` です。
棒読みちゃんの速度・音程・音量は整数の-1～32,767です。
VOICEVOX・COEIROINKの音量は0～4、速度は0.1～4、音程は-0.15～0.15です。
音声パラメータは有限値が必要です。追加TTSの項目と入力範囲は各プラグインが宣言します。

## 表示・アプリ設定

| パス（presentation配下） | 初期値 |
| --- | --- |
| `comment_popout` | false |
| `comment_opacity` / `header_opacity` / `border_opacity` | 各0.8 |
| `background_color` / `border_color` | #1e1e1e / #3c3c3c |
| `window_x` / `window_y` | null / null |
| `window_width` / `window_height` | 360 / 500 |
| `popup_metrics.placement` | top |
| `popup_metrics.vertical_ratio` / `horizontal_ratio` | 各0.35 |
| `popup_metrics.display_modes` | 空オブジェクト |

不透明度は0～1、配置は `top`・`bottom`・`left`・`right`、
分割比率は0.1～0.9です。
指定のない項目は非表示です。表示モードはメトリクスIDをキーに、`hidden`・`text`・`both` を指定します。
IDは `cpu`・`ram`・`network`・`youtube_connections` と、検出したGPU等のIDです。

`application.check_updates` はtrue、
`application.use_ime` はfalseが初期値です。
`application.plugin_enabled` は `[["ID", true]]` 形式の配列で、未指定の内蔵は有効、外部は無効です。
変更は保存後の再起動で反映します。
`use_ime` は保存モデルにありますが、現行コードではIME動作へ適用していません。

## リソース上限

| resources配下 | 初期値 | 範囲 | 刻み |
| --- | --- | --- | --- |
| `comment_count` | 1,000件 | 100～10,000件 | 100件 |
| `log_lines` | 2,000行 | 100～20,000行 | 100行 |
| `audio_mib` | 32MiB | 4～256MiB | 4MiB |
| `avatar_mib` | 8MiB | 1～64MiB | 1MiB |

設定画面のOKで適用します。
上限を下げると古い表示・キャッシュを解放します。
音声は新規合成を待機させ、受け付け済みの音声を再生して減らします。
詳細は[読み上げ](speech.md)を参照してください。

## スキーマ1・2からの移行

スキーマ1を読み込んだ場合は、変換と検証を行い、
変換前のバイト列を `config.json.schema1.bak` に保存してから3で保存します。
同名バックアップがすでにあり内容が違う場合は、上書きせず移行を中止します。

変換では不足しているリソース・キュー上限・エンジン設定を補い、
廃止エンジン `supertonic`・`supertonic_lightweight` を除去します。
廃止エンジンを選択していた場合はVOICEVOXへ変更します。
VOICEVOX系の任意音声値がnullなら既定値へ戻し、
棒読みちゃんの整数相当の小数値を整数へ変換します。
Qwenの旧手動接続URLなど、現在のエンジンが持たないフィールドは引き継ぎません。

スキーマ2は `config.json.schema2.bak` に元データを保存して3へ変換します。
スキーマ1は従来の1→2変換を経由して3へ変換します。
エンジン種別をIDへ、話者を文字列へ移し、固有項目をsettingsにまとめます。
旧辞書ファイルや旧データ配置は自動移動しません。
リリース済み設定の互換処理は保存層で維持し、内部APIの旧方式は維持しません。

## 実装参照

- [設定モデル](../../src/livevoicebridge/core/settings/models.py)、[既定値](../../src/livevoicebridge/core/settings/defaults.py)
- [音声モデル](../../src/livevoicebridge/core/speech/models.py)、[設定検証](../../src/livevoicebridge/core/settings/service.py)
- [JSON保存](../../src/livevoicebridge/integrations/storage/config.py)、[変換](../../src/livevoicebridge/integrations/storage/migrations.py)
- [配置解決](../../src/livevoicebridge/host/paths.py)、[ネイティブ配置](../../native/src/runtime.rs)
