# ソースコードと内部構造

[仕様書一覧](../README.md)

## 実装の入口

本体は `src/livevoicebridge/` のPythonパッケージと、`native/` のRust/PyO3拡張で構成します。
GUIはPySide6、外部通信はrequests・gRPC、ローカル再生はRust/rodioです。
Qwen推論は `services/qwen3/` の独立環境で動く子プロセスです。

`python -m livevoicebridge` とGUIエントリーポイントは `host.bootstrap.main` に入ります。
起動時にネイティブのプラットフォーム初期化、QApplication、配置解決、依存の組み立てを行います。
組み立て失敗は起動エラーとして通知します。

## 責務と依存

| 層 | 所有するもの |
| --- | --- |
| `core/chat` | 配信設定・受信イベント・コメントから読み上げ計画への変換 |
| `core/speech` | エンジン設定・能力・発話計画・合成再生パイプライン・PCM予算 |
| `core/dictionary` | 辞書の値型・リポジトリ契約・教育忘却サービス |
| `core/settings` | 設定モデル・既定値・検証・保存と版管理 |
| `core/session` | 開始・停止・設定適用・終了とワーカーの統括 |
| `core/telemetry` | 測定値・エラー・共有履歴 |
| `integrations` | 配信、TTS、保存、音声、ネイティブ、更新確認の具象実装 |
| `desktop` | Qtフォーム、Presenter、表示モデル、描画、操作の受け渡し |
| `host` | 起動、配置、全依存の組み立て |
| `native` | OS処理、プロセス、再生、DSP、解析、SQLite辞書 |
| `services/qwen3` | OpenVINOモデルの変換補助・推論HTTPサービス |
| `tools` / `packaging` | 生成差分、共通ビルド、PyInstaller定義 |

coreはQtやRustの具象型をimportせず、Protocolと不変の値型で連携します。
desktopとintegrationsはcoreへ依存し、互いはimportしません。
両者の接続は `host/composition.py` に集約します。
TTSはpluginsの登録済み提供者から文字列IDで解決します。
内蔵プラグインは本体内の明示的な一覧、外部プラグインはアプリ直下のpluginsから検出します。
公開契約・登録Context・管理クラスを分離し、Qwen固有の画面とライフサイクルは内蔵プラグイン側で扱います。
外部実行形式の通信とプロセス所有はRust/PyO3が担当します。
公開契約は[プラグイン作成ガイド](../plugins/development.md)を参照してください。

## セッションと並行処理

`SessionService` はコマンドキューを1つ持ち、
開始・停止・設定適用などのライフサイクルを `session-control` スレッドで直列化します。
状態は `idle`・`starting`・`running`・`stopping`・`error` です。
実行状態とYouTube接続状態は別に管理します。

開始・停止などでintent番号を更新し、現在の番号と異なる受信・状態通知を無効化します。
音声進捗にはセッション番号と設定revisionを載せ、古い進捗を画面へ戻さないようにします。
Qwenは独自のgeneration、辞書ページ取得は画面側のgenerationを持ちます。

| 処理 | 実行単位 |
| --- | --- |
| 画面・描画 | Qtメインスレッド |
| 配信取得 | YouTubeSourceのスレッド |
| 合成・計画消費 | セッションごとの合成スレッド1本 |
| 順序付き再生 | セッションごとの再生スレッド1本 |
| デバイス・SE再生 | Rust AudioPlayerの専用スレッド |
| 辞書ドラフト操作 | 単一ワーカーのexecutor |
| 話者取得・更新確認 | 補助executor、最大2ワーカー |
| アバター取得 | 専用executor、最大2ワーカー、受付64件 |
| メトリクス収集 | 監視スレッド、約1秒周期 |
| Qwen管理・準備 | ライフサイクル用スレッドと準備用スレッド |

受信イベントは元の表示文を持ち、読み上げ計画の値とは分離します。
DesktopEventsでコメント・ログの保留数を制限し、
進捗・メトリクス通知は最新状態の表示へまとめます。
表示モデルにも保持上限を適用します。

終了要求は新しい受付を止め、世代を更新し、待機コマンドと音声キューを取り消します。
Qwen、取得元、パイプライン、エンジン、音声出力、補助ワーカー、辞書、メトリクスを解放して、
終了完了イベントをQt側へ通知します。
通常の停止ではQwen全体を解放せず、モデルを再利用します。

## PythonとRustの境界

`_native.pyi` がPython側の型契約です。ネイティブ拡張は必須です。
Pythonだけで同じ機能を代替するフォールバックはありません。
内部APIの変更後は拡張を更新する必要があります。

| Rustの入口 | 内容 |
| --- | --- |
| `initialize_platform` / `PlatformPaths` | OS初期化、配置先、保存先、実行ファイルフィルター |
| `ManagedProcess` | 子プロセス起動・所有・終了・終了コード |
| `PluginProcess` / `plugin_platform` | 外部TTSの標準入出力通信・期限・プロセス所有とOS識別 |
| `qwen_platform` | Qwen専用環境のOS識別とPython相対パス |
| `parse_comment` / `split_sentences` | コマンド解析・句点分割 |
| `DictionaryDatabase` / snapshot | DB、編集差分、最長一致、スナップショット |
| `AudioClip` / `AudioPlayer` | PCM16デコード、DSP、再生、SE |
| `RustMetricsCollector` | CPU・RAM・通信・GPU・ソケット数 |

OS固有の処理は `native/src/platform/` に分けます。
Windowsの子プロセスはJob Object、Linuxはプロセスグループなどで管理します。
外部で起動済みのエンジンは所有しません。
HTTPまたはTCPで疎通を確認できればそのまま使用し、確認できなければ指定実行ファイルを起動して最大20秒準備を待ちます。
所有したプロセスはエンジン解放時に閉じます。

PythonはQt共通API、HTTP/gRPC、JSON、ファイル処理を担当できます。
本体実行時のOS分岐・ctypes・外部再生コマンドは追加しません。
開発ツールのOS分岐は本体実行時の境界とは別です。

## 辞書と音声の所有

辞書の正式実装はRust側SQLiteです。bundled SQLiteを拡張へ組み込みます。
DB内ドラフトを差分確定し、影響単語だけを不変radix treeへ反映します。
発話のスナップショットは古いルートの共有参照を保持し、更新と照合を分離します。
DB全件をPythonのリストへ渡しません。

PCMは `Arc<Vec<i16>>` を持つRustの不変AudioClipです。
PythonのAudioDataはそのハンドルを包み、PCM予算を管理します。
WAVの受信はPythonのメモリ上で行い、RustでデコードとDSPを実施します。
SEはRustがファイルから直接デコードします。
容量とエラー時の扱いは[読み上げ仕様](../users/speech.md)を参照してください。

## Qtの構成

固定の画面構造・ウィジェット・レイアウトは `desktop/resources/forms/*.ui` に定義します。
`desktop/forms.py` がフォームを読み込み、カスタムウィジェットを結び付けます。
Pythonで追加するUIはコメント行、辞書行、読み上げブロック、検出GPUなど、
実行時に個数や構造が変わる部分に限定します。

Viewはフォームと編集ドラフト、Presenterは操作とサービスの接続を担当します。
辞書のDBアクセス・話者取得・モデルロードをQt描画処理で実行しません。
監視の60点履歴はcoreに1つだけ持ち、監視画面とPiPで共有します。

## Qwenサービス契約

アプリ全体でQwenManagerを1つ所有し、専用環境・モデル・サービスを管理します。
モデルパスとデバイスがロードの識別子で、管理世代の変化で古い準備結果・応答を捨てます。
サービスは `127.0.0.1` の動的ポートで待ち受け、起動ごとのBearer tokenで認証します。
独立起動した他用途のサービスへ接続する設定はありません。

| 要求 | 応答 |
| --- | --- |
| `GET /health` | サービス識別子、ready、phase、error、model、device |
| `GET /voices` | 話者IDと名前の配列 |
| `POST /synthesize` | text・voice_id・volumeからPCM16 WAV |

全要求はAuthorizationヘッダーを検証し、不一致は403です。
不明な経路は404、準備未完了は503、不正入力は400、
同時合成中は429、合成失敗は500です。
合成入力は本文32,768バイト以下、テキスト1～2,000文字、
話者ID 0～8、有限の音量0～2です。同時合成は1件です。
ロード後にウォームアップしてからreadyを公開します。

取得元モデルは固定IDとrevision
`85e237c12c027371202489a0ec509ded67b5e4b5` を使用します。
専用CPythonと主要依存はURL・SHA-256を固定し、
OS別JSONとサービスのpyprojectで管理します。
OpenVINO一式は2026年10月22日のnightly版、
Optimum Intelはコミット `c46fb912366bc9d25b8395621d885a457369228d` です。
Qwen専用環境は本体の依存更新から分離し、通常版OpenVINOへの自動置換はしません。
qwen-tts 0.1.1に合わせたTransformers 4.57.3、
NNCF・Torchに合わせたNumPyとsetuptoolsの制約を維持します。
詳細な配布URL・バージョン・ハッシュはOS別JSONを正とします。

## 実装参照

- [組み立て](../../src/livevoicebridge/host/composition.py)、[起動](../../src/livevoicebridge/host/bootstrap.py)
- [セッション](../../src/livevoicebridge/core/session/service.py)、[画面イベント](../../src/livevoicebridge/desktop/events.py)
- [ネイティブ型](../../src/livevoicebridge/_native.pyi)、[ネイティブ入口](../../native/src/lib.rs)
- [Qwen管理](../../src/livevoicebridge/integrations/qwen/runtime.py)、[サービス](../../services/qwen3/src/lvb_qwen3_service/server.py)
- [固定取得元](../../src/livevoicebridge/integrations/qwen/assets.py)、[Windows依存](../../src/livevoicebridge/integrations/qwen/resources/windows.json)、[Linux依存](../../src/livevoicebridge/integrations/qwen/resources/linux.json)
