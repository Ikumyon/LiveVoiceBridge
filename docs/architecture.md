# 現行設計

## 責務と依存方向

Python本体は `src/livevoicebridge/` に置きます。

- `core/`: session・chat・speech・dictionary・settings・telemetryの型、契約、処理。
- `integrations/`: HTTP/gRPC、保存、所有プロセス、Rustへの接続。
- `desktop/`: Qt画面、表示モデル、編集コンポーネント、Presenter、Designer資材。
- `host/`: 起動、ポータブル配置先の解決、具象実装の組み立て。

desktopとintegrationsはcoreに依存し、互いをimportしません。coreはQt・Rustの具象実装・hostをimportしません。
両者を接続するのはhostのcompositionです。OS固有APIはRustのplatformへ集約します。

## 設定画面と描画

`desktop/settings/view.py` は画面と編集コンポーネントを組み立て、OKで型付き設定を集約します。
エンジン、話者メニュー、読み上げブロック、表示・メトリクス、保持数・容量設定はそれぞれのコンポーネントが所有します。
辞書画面は `desktop/dictionary/` が所有します。コンポーネントは親画面全体への参照を持ちません。

設定の非同期保存、話者取得、Qwen状態の反映はSettingsPresenter、辞書の非同期編集はDictionaryPresenterが担当します。
キャンセル時は編集ドラフトを破棄し、PiPプレビューを保存済み設定へ戻します。
Qwen準備完了により保存されたモデル情報は、既存の世代管理と保存基準に従って反映します。

固定UIは `desktop/resources/forms/*.ui` に定義します。
コメント、辞書、読み上げブロック、話者、検出済みメトリクスなどの可変UIだけをPythonで生成します。
テーマ色付きSVGの描画と丸形画像処理は `desktop/rendering/` に集約し、コメントの画像キャッシュとスタイルはcommentsに置きます。

## Qwenの資材と実行環境

- 依存JSON: `integrations/qwen/resources/windows.json` と `linux.json`。
- サービスの開発ソース: `services/qwen3/`。
- 配布時のサービス同梱先: `integrations/qwen/resources/service/`。
- 資材とサービスの参照先: hostのAppPathsで解決。
- 専用Python、モデル、ログ、ダウンロード等: ポータブル配置先内の `data/qwen/`。

準備済み環境の識別は依存JSON、サービス内容、ランタイム識別情報から計算します。
GUI資材のパスには依存しません。モデル・依存の固定値は準備処理の正式な入力として保持します。

## 設定互換性と辞書

リリース済み設定ファイルの互換性は維持します。
`integrations/storage/migrations.py` がスキーマ1から2への変換を担当し、
configが変換後の検証、変換前バックアップ、原子的保存を担当します。
廃止エンジンの置換・欠落値の補完を維持し、不正な変換や内容の異なる既存バックアップでは保存を中止します。
内部コードの旧方式への互換importや併存実装は用意しません。

Rust辞書はdatabase、draft、snapshot、bindings、import、trieに分けます。
databaseが接続と正式データ、draftが編集差分と確定・破棄、snapshotが不変の照合状態、
bindingsがPyO3公開APIを所有します。既存のSQLite形式、排他制御、優先順位、公開APIを維持します。
既存の辞書テストは `native/src/dictionary/tests.rs`、fixtureは `native/fixtures/dictionary/` に置きます。

## 開発・検証・履歴

開発コマンドは [開発ガイド](development.md) に記載します。
PythonはRuff・整形チェック・mypy、Rustはfmt・check・clippyで静的検証します。
アプリ起動・テスト実行・配布ビルド・音声再生・性能測定は明示的な指示がある場合に限ります。
静的検査の成功は実行動作の検証を意味しません。

バージョンはインストール済みパッケージメタデータを使用します。
利用者データ、仮想環境、生成物、キャッシュはコード整理の移動・削除対象に含めません。

過去の記録は [初期再設計](history/rearchitecture-plan.md)、
[初期実装記録](history/rearchitecture-implementation.md)、
[OS処理とリソース管理](history/native-resource-refactor.md) に保存しています。
