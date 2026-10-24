# 開発ガイド

ソース・PowerShell・設定・文書はUTF-8で扱います。テキストの作成・変更にはapply_patchを使用します。

## 開発環境

正式対象はWindows・Linux、Python 3.11以降、Rust stableです。
通常利用者はビルド済み配布フォルダを使用します。以下は開発者向けの手順です。

```powershell
py -m venv venv
./venv/Scripts/Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install -e ".[dev]"
```

Linuxでは先にALSA開発用ライブラリを導入します。Ubuntu/Debianは `libasound2-dev pkg-config`、
Fedoraは `alsa-lib-devel pkgconf-pkg-config` が必要です。`pw-play` は使用しません。

Rustの公開APIを変更した後は、明示的にビルドする段階で `maturin develop --release` を実行します。
型チェックだけでは既存の `_native.pyd` / `_native.so` は更新されません。新旧APIの互換処理はありません。

## 責務と依存

coreは機能の型・契約・処理を所有し、Qt・Rustの具象型をimportしません。
desktopとintegrationsはcoreに依存し、互いをimportしません。hostで依存を組み立てます。
OS固有の分岐とAPIはRustへ集約し、Qtの共通API、HTTP/gRPC、JSON保存はPythonで扱います。
固定UIはDesignerの.uiに定義します。

## 実装時の静的検証

```powershell
python -m mypy --cache-dir .codex-type-check-cache src/livevoicebridge tests services/qwen3/src
python -m ruff check src tests services/qwen3/src tools
python -m ruff format --check src tests services/qwen3/src tools
cargo check --locked --manifest-path native/Cargo.toml --all-targets
cargo fmt --manifest-path native/Cargo.toml -- --check
cargo clippy --locked --manifest-path native/Cargo.toml --all-targets -- -D warnings
```

CIもWindows/Linuxの静的検証に統一しています。
アプリ起動・配布ビルド・音声再生・テスト実行・負荷計測は、別途指示があるまで実行しません。
回帰テストはtestsに用意し、明示的なテスト実行時の一時データは `.test-runs/pytest` に限定します。
未実施の実機検証と計測値を、検証済みとして報告しません。

protobuf変更時は `python tools/generate_protocol.py` が出す差分を確認し、apply_patchで適用します。
生成物はintegrations/youtube/generatedにコミットし、起動時のコード生成は行いません。

## 配布定義

明示的に配布ビルドを実施する段階で使用するコマンドです。

```powershell
python -m pip install -e ".[package]"
pyinstaller --clean packaging/LiveVoiceBridge.spec
```

`dist/LiveVoiceBridge/` をフォルダ単位で配布します。EXEと `_internal/` にフォーム・アイコン・
protobuf・Rust拡張を同梱し、単一EXEの外部一時展開は行いません。
DLL解析時のPATHはPythonとWindowsのディレクトリに限定し、開発ツール付属DLLの混入を防ぎます。

設定・辞書・効果音は配置先内のdataへ保存します。ソース起動ではリポジトリ直下を配置先とします。
AppData、OS一時フォルダ、レジストリを設定保存先には使用しません。
Qwen3の推論環境とモデルは独立したサービスとして別途用意します。
