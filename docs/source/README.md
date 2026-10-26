# ソースコード案内

[ドキュメント一覧](../README.md)

| 文書 | 内容 |
| --- | --- |
| [内部構造](architecture.md) | 層ごとの責務、起動、スレッド、状態管理、Rust境界、Qwenサービス契約 |
| [開発と配布](development.md) | 環境作成、静的検査、生成コード、共通ビルド、GitHub Release |

本体の入口は [host/bootstrap.py](../../src/livevoicebridge/host/bootstrap.py)、
依存の組み立ては [host/composition.py](../../src/livevoicebridge/host/composition.py) です。
開始・停止・設定適用を追う場合は [SessionService](../../src/livevoicebridge/core/session/service.py)、
読み上げを追う場合は [SpeechPipeline](../../src/livevoicebridge/core/speech/pipeline.py) を確認してください。

## 動作仕様の参照

- [利用と画面](../users/README.md)
- [読み上げ](../users/speech.md)
- [辞書](../users/dictionary.md)
- [設定モデル・保存・移行](../users/configuration.md)
- [Qwen3](../users/qwen3.md)

開発中の内部構造は新方式へ完全移行し、旧実装の互換層は維持しません。
リリース済み設定は保存層で変換とバックアップを維持します。
固定UIはQt Designerの `.ui` に定義します。
本体実行時のOS固有処理はRust/PyO3へ集約します。

通常の実装時の検証は型チェックと静的検査に限定します。
実行を伴う検証は別途明示的な指示がある場合に実施します。
