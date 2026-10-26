# 開発と配布

[仕様書一覧](../README.md)

## 開発環境

正式対象はWindows・Linuxです。通常版CPython 3.14以降、Rust stable 1.95以降を使用します。
free-threaded版Pythonはビルドツールが拒否します。
WindowsではMSVCのビルド環境が必要です。
LinuxではALSA開発用ライブラリとpkg-configが必要です。
Ubuntu/Debianのパッケージ名は `libasound2-dev pkg-config` です。

ソース・PowerShell・設定・文書はUTF-8で扱い、
テキストファイルの作成・変更・削除は `apply_patch` で差分を示して行います。
開発中の内部APIは新方式へ移行し、旧import・旧APIの互換層や並行実装は残しません。
リリース済み設定の変換・バックアップは互換性を維持します。

環境作成と開発依存の導入例です。これらは依存導入・拡張ビルドを伴う手順です。

```powershell
python -m venv venv
./venv/Scripts/Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install -e ".[dev]"
```

Linuxでは `source venv/bin/activate` を使用します。
ソース起動の入口は `python -m livevoicebridge` です。
型チェックだけではRust拡張は更新されません。

## 実装時の検証

通常の実装作業で実行する検証は型チェックと静的検査に限定します。
アプリ起動・配布ビルド・音声再生・テスト実行・負荷計測は、別途明示的な指示がある場合だけ行います。

```powershell
python -m mypy --cache-dir .codex-type-check-cache src/livevoicebridge services/qwen3/src tools
python -m ruff check src services/qwen3/src tools
python -m ruff format --check src services/qwen3/src tools
cargo check --locked --manifest-path native/Cargo.toml --all-targets
cargo fmt --manifest-path native/Cargo.toml -- --check
cargo clippy --locked --manifest-path native/Cargo.toml --all-targets -- -D warnings
```

Pythonの生成protobufコードはRuff・mypyの対象から除外しています。
Rustには辞書・解析・DSP等のテストがありますが、`--all-targets` の静的検査では実行しません。
未実施の実機検証や性能測定を検証済みとして扱いません。

## protobufの更新

YouTubeのprotoと生成済みPythonは `integrations/youtube/generated/` に配置します。
`python tools/generate_protocol.py` は一時領域で生成してパッチを標準出力へ出します。
差分を確認し、`apply_patch` で適用します。
アプリ起動時のコード生成やsys.pathの書き換えはありません。
生成コードに合わせ、grpcioとprotobufには最低版を設定しています。

## ローカルビルドの契約

依存導入・Rust拡張・Python配布・同梱検査の共通実装は `tools/build.py` です。
以下はビルドを明示的に実施する場合の入口です。

| 目的 | Windowsの入口 | 共通コマンド |
| --- | --- | --- |
| Rust拡張を更新 | `build_rust.bat` | `python tools/build.py rust` |
| 配布フォルダを作成 | `build_python.bat` | `python tools/build.py python` |
| CI用ソースから両工程を実施 | Actions | `python tools/build.py ci` |

batは対応する `tools/*.ps1` を呼び、ps1が共通Pythonツールへ渡します。
batは終了時に一時停止し、ps1の直接実行は一時停止しません。
WindowsでPythonを選ぶ例は `./build_rust.bat -Python "C:\Python314\python.exe"` です。

ローカルはリポジトリの `venv/` を作成または再利用します。
不完全なvenvや非対応Pythonは自動削除せず停止します。
利用者が削除・退避してから作り直します。OS設定・実行ポリシーを永続変更する処理はありません。

`rust` はMaturinを更新し、Cargo依存を更新してから
`maturin develop --release --locked` を実行し、ソース配下へ拡張を配置します。
`python` は本体・PyInstaller依存を更新し、配置済み拡張を検査してから配布を作ります。
後者はRustをビルドしません。拡張がない・別のツリーにある・パッケージ版が不一致なら停止します。

本体・開発・配布用依存は原則固定せず、ビルド時に間接依存も更新します。
Cargo.lockは解決結果として保持し、更新後の同一工程を `--locked` で実行します。
例外は生成コードが要求する最低版と、分離されたQwen専用環境の固定依存です。

## 配布物

PyInstallerは `packaging/LiveVoiceBridge.spec` を使い、
`dist/LiveVoiceBridge/` に実行ファイルと `_internal/` を作ります。
フォーム・アイコン・protobuf・Rust拡張・パッケージメタデータと、
QwenのOS別JSON・サービスソース・pyprojectを同梱します。
Qwen専用Python・推論依存・モデルは配布ビルド時に取得しません。

単一EXE形式による外部一時展開は使用しません。
WindowsのDLL解析時PATHはPythonとWindowsのディレクトリへ限定します。
同梱検査は必須ファイル・バージョン・サービスソースの一致などを確認します。

PyInstallerは `--clean --noconfirm` で出力先を更新します。
利用者データをビルド出力先に置かないでください。
本体管理データの保存仕様は[設定と保存](../users/configuration.md)を参照してください。

## バージョン

正式バージョンの管理元はGitタグです。
本体・Rust・Qwenサービスの宣言値は開発用の `0.0.0` を保持します。
Release用にはクリーンなcheckoutと、HEADに一致する `vX.Y.Z` 形式のタグが必要です。
後ろに任意の接尾辞を付けられ、数値部分の先頭ゼロはパッケージ版から除去します。

Python・Rust共通の版表現にするため、接尾辞をUTF-8の16進表記へ変換し、
`+tag.x` の後ろに付けます。
例: `v0.9.0RC` → `0.9.0+tag.x5243`。
Gitタグ名そのものは変えません。設定スキーマ版とも独立です。

`ci` はGit管理下ファイルから `build/ci-source/` を新規作成し、
その中の3つのマニフェストだけに版を反映します。
元ソースの変更・自動コミットはしません。
venvも `build/ci-venv/` に新規作成し、Rust→Python→検査の順で実行します。
既存のCI用ソースや環境は再利用しません。

本体の表示版は同梱パッケージメタデータを参照し、利用環境にGitは不要です。
起動時の更新確認はGitHub Releasesのlatestを参照し、数値のX.Y.Zだけを比較します。
同じ数値版の接尾辞には順序を付けません。

## GitHub ActionsとRelease

`.github/workflows/build.yml` のトリガーはPR、mainへのpush、Releaseのpublishedです。
タグのpushだけやRelease下書き保存では配布ワークフローを開始しません。
Release公開は正式版・プレリリースとも対象です。

静的検査は再利用ワークフロー `quality.yml` がWindowsとLinuxで実施します。
それに成功するとWindows x64・Ubuntu 22.04上のLinux x64で配布ビルドと同梱検査を行います。
PR・main更新では圧縮と成果物保存を行いません。
このCIにアプリ起動・音声再生・テスト実行・負荷計測は含めません。

正式配布の流れは次のとおりです。

1. GitHub Releasesで対象コミットとタグを指定し、タイトル・本文を入力して公開します。
2. Actionsが静的検査と両OSのビルド・検査を実施します。
3. Release用の配布ファイルを圧縮してActionsの成果物に保存します。
4. 両OSが成功した後、添付ジョブが公開済みReleaseのAssetsへ両ファイルを自動添付します。

| OS | Assetsのファイル名 |
| --- | --- |
| Windows x64 | `LiveVoiceBridge-Windows-x64.zip` |
| Linux x64 | `LiveVoiceBridge-Linux-x64.tar.gz` |

どちらも展開後の最上位フォルダは `LiveVoiceBridge/` です。ファイル名には版を含めません。
公開直後はビルド待ちになり、完了後にAssetsが揃います。
利用者への案内はReleaseのAssetsを使用します。

ビルド側はcontents読み取り権限で動き、添付ジョブだけがactions読み取り・contents書き込みを持ちます。
添付は既存ファイルを上書きせず、Releaseの公開状態・タイトル・本文も変更しません。
失敗時は開発者が失敗ジョブを確認・再実行します。
すでに同名Assetsがある場合は上書きしないため再添付は失敗します。
配布内容の修正は新しい番号のタグ・Releaseで行います。

## 実装参照

- [プロジェクト設定](../../pyproject.toml)、[Rust依存](../../native/Cargo.toml)
- [共通ビルド](../../tools/build.py)、[PyInstaller定義](../../packaging/LiveVoiceBridge.spec)
- [生成差分](../../tools/generate_protocol.py)
- [ビルドワークフロー](../../.github/workflows/build.yml)、[静的検査](../../.github/workflows/quality.yml)
