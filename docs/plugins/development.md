# TTSプラグインの作成

## マニフェストと登録

公開API版は1です。内蔵と外部で同じ契約を使用します。
IDは英小文字から始まる英小文字・数字・`_`・`-`・`.`、最大64文字です。
内蔵ID `voicevox`・`coeiroink`・`bouyomichan`・`qwen3` は外部から使用できません。

```json
{
  "id": "example_http",
  "name": "HTTP WAV 作成例",
  "version": "1.0.0",
  "api_version": 1,
  "platforms": ["windows", "linux"],
  "kind": "python",
  "entry": "entry.py"
}
```

エントリーはプラグインフォルダー内の相対パスです。
Pythonのエントリーは `register(context)` で、自身のIDのTTS提供者を一度だけ登録します。
同梱の [Python作成例](../../examples/plugins/python_http/entry.py) を参照してください。

型は `livevoicebridge.plugins.contracts`、登録Contextは `livevoicebridge.plugins.api` から取得します。
Qtを必要としない公開契約と、Qt設定画面の契約 `livevoicebridge.plugins.ui` を分離しています。
標準実装 `livevoicebridge.plugins.provider.Provider` はデフォルト設定・型と範囲の検証・通常のライフサイクルを提供します。

提供者は以下を持ちます。

- `id`・`name`・`capabilities`・`fields`
- `defaults() -> EngineConfig`、`validate(config)`、`create(config)`
- `configure(config | None)`、`wait_ready(cancelled)`、`close()`

`EngineConfig` はエンジンID、文字列の話者ID、最大文字数、JSONスカラー値の設定辞書を持ちます。
`configure` は選択中の設定を受け、非選択の場合はNoneを受けます。
`wait_ready` はワーカーから呼ばれ、渡されたEventによる中止に応答してください。
エンジンは準備・話者取得・終了に加え、音声を返す `synthesize` または外部へ委譲する `send` を実装します。

## 音声・設定画面・ホスト機能

`capabilities` で対応するコメント制御、ローカル音声の有無、完了を把握できるかを宣言します。
制御名は `speaker_id`・`speed`・`pitch`・`volume`・`echo`・`yamabiko`・`panning` です。
未対応のコメント制御は本体が通知して省略します。

合成音声は `context.decode_wav(wav, controls, max_bytes)` で本体の音声へ変換します。
WAVはデコード前にも `max_bytes + 65536` 以下に制限し、デコード後の容量も本体が検証します。

設定項目 `SettingField` はキー・表示名・種類・初期値・数値範囲・選択肢を宣言します。
種類は `text`・`secret`・`file`・`directory`・`choice`・`bool`・`integer`・`number` です。
宣言に応じて本体がDesignerのテンプレートを使って行を表示します。
Python形式は `context.settings_page(parent, read_config)` のファクトリーを設定し、追加画面も提供できます。
引数の `read_config()` は、未保存の入力を含む現在のTTS設定を返します。
返すオブジェクトは `widget`、`read(config) -> EngineConfig`、`close()` を持ちます。
固定UIは必ず `.ui` に定義します。

Contextは `root`（コード配置先）、`data`（専用保存先）、`logger`、
`decode_wav`、`save_config(values, generation=None)`、`publish_state(state)`、
`managed_process()`、`on_close(callback)` を提供します。
`save_config` は非同期処理の結果を本体の直列化された設定更新へ渡します。
設定画面をキャンセルしても、既に完了したモデル準備などの保存結果は保持します。
非同期の準備・再起動を持つ提供者は `EngineState(engine_id, phase, message, generation, busy)` を通知します。
`busy` または `error` で読み上げを中断し、`ready` で中断済みのパイプラインを再開します。
設定保存にgenerationを指定すると、世代が変わった古い結果を保存しません。
OS固有の処理・プロセス管理はRust/PyO3を利用し、管理下の書き込みはポータブル配置先内に限定してください。

## 外部実行形式

[マニフェスト例](../../examples/plugins/executable_http/manifest.json) と
[サーバーソース](../../examples/plugins/executable_http/server.py) を参照してください。
サンプルは、Python例と同じ `POST {text, voice} → WAV` の独自HTTPエンドポイントへ接続する作成例で、
特定製品向けの追加TTSではありません。

実行ファイルは各OSで別途作成します。例えばPyInstallerでサーバーソースを単一実行ファイルにし、
Windowsでは `bin/tts_plugin.exe`、Linuxでは `bin/tts_plugin` に配置します。
ソースとマニフェストだけでは起動できません。サンプルのビルド・起動は今回の実装では実施していません。
独自ランタイムを同梱する場合も、実行ファイルのパスはプラグインフォルダー内としてください。
Linux配布物は配布時に実行可能にしておき、本体では権限変更を行いません。

標準入出力はUTF-8のJSON Linesです。標準出力にはプロトコル応答だけを書き、
ログは標準エラーに出力します。要求ごとに応答を一つ返します。

```json
{"version":1,"id":"request-id","method":"speakers","params":{"config":{}}}
{"version":1,"id":"request-id","result":[{"identifier":"default","name":"標準話者","style":"通常"}]}
```

エラー応答は `result` の代わりに `error: {code, message}` を返します。
要求と応答のversion・idを一致させてください。

| メソッド | params | result |
| --- | --- | --- |
| register | api_version, plugin_id, data_directory | id, name, capabilities, fields, speaker_id |
| prepare | config | null |
| speakers | config | 話者の配列 |
| synthesize | text, controls, config, max_bytes | wav_base64 |
| send | text, controls, config | null |
| close | 空オブジェクト | null |

`config` は `engine_id`・`speaker_id`・`max_length`・`settings` を持ちます。
`controls` は各コメント制御の値を持ち、未指定はnullです。
`capabilities.controls` は制御名の配列で、残りの2項目は `local_audio` と `completion_known` の真偽値です。
`fields` はSettingFieldと同じ項目のJSONオブジェクト配列です。

登録用プロセスで能力を取得した後、音声エンジンごとに専用プロセスを起動します。
エンジンごとのプロセスは複数要求を継続して扱い、最初にregisterを受け取ります。
話者取得と読み上げは別のエンジンインスタンスとなるため、別プロセスです。
通常要求は30秒、合成・送信は120秒、終了通知は2秒の期限があります。
1行は最大360 MiBです。通常応答は1 MiB以下、合成応答は要求された音声容量から算出した上限を通信中にも適用します。
音声は要求されたmax_bytesの制限にも従います。
不正応答・期限超過・異常終了は要求を失敗させ、該当プロセスを回収します。
標準エラーは専用保存先の `stderr.log` に記録し、出力量を制限します。
