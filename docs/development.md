# 開発ガイド

ソース・PowerShell・設定・文書はUTF-8で扱います。テキストの作成・変更にはapply_patchを使用します。

## 開発環境

正式対象はWindows・Linux、通常版CPython 3.14以降、Rust 1.95以降のstableです。
通常利用者はビルド済み配布フォルダを使用します。以下は開発者向けの手順です。

```powershell
python -m venv venv
./venv/Scripts/Activate.ps1
$env:PYTHONUTF8 = "1"
python -m pip install -e ".[dev]"
```

Linuxでは先にALSA開発用ライブラリを導入します。Ubuntu/Debianは `libasound2-dev pkg-config`、
Fedoraは `alsa-lib-devel pkgconf-pkg-config` が必要です。`pw-play` は使用しません。

正式な配布ビルドはGitHub Actionsで行い、リリース作成・添付・公開は手動で行います。ローカルのbat・ps1は開発中の確認用です。
依存導入・Rustビルド・配布作成・同梱内容の検査は `tools/build.py` に集約し、Actionsとローカルで同じ処理を使います。

WindowsでRust拡張だけを更新する場合は、リポジトリ直下の `build_rust.bat` を実行します。
`tools/build_rust.ps1` は共通ツールの `rust` コマンドを呼ぶ入口です。共通ツールが `venv` を準備し、
MaturinとCargo依存を最新版へ更新してから、`maturin develop --release --locked` で
`native/Cargo.toml` をビルドして `src/livevoicebridge/` へ拡張を配置します。
Pythonアプリの配布ビルドは実行しません。

`venv` がない場合はPATH上の `python` から作成します。Pythonを明示する場合は、次のように指定します。

```powershell
./build_rust.bat -Python "C:\Python314\python.exe"
```

既存の `venv` は再利用します。Python 3.14未満・free-threaded版・不完全な環境の場合は停止するため、
利用者が削除または退避してから作り直してください。Python、Rust stable、Windows用のMSVCビルド環境は
事前に導入してください。スクリプトによるOS設定・実行ポリシーの永続変更は行いません。

LinuxでRust拡張を更新する場合も、`python tools/build.py rust` で同じ処理を使います。
型チェックだけでは既存の `_native.pyd` / `_native.so` は更新されません。新旧APIの互換処理はありません。

## 責務と依存

coreは機能の型・契約・処理を所有し、Qt・Rustの具象型をimportしません。
desktopとintegrationsはcoreに依存し、互いをimportしません。hostで依存を組み立てます。
OS固有の分岐とAPIはRustへ集約し、Qtの共通API、HTTP/gRPC、JSON保存はPythonで扱います。
固定UIはDesignerの.uiに定義します。詳細は [現行設計](architecture.md) を参照してください。

辞書はRust/PyO3のSQLiteリポジトリを正式実装とし、SQLiteはRust拡張に同梱します。
DB本体、差分ドラフト、ジャーナルは配置先内の `data/` に保持します。SQLの一時領域はメモリに限定します。
同じ辞書DBは1つのアプリプロセスが所有し、別プロセスによる編集中ドラフトの破棄を排他ロックで防ぎます。
Pythonはグループ情報と画面用の最大2,048件のキャッシュだけを保持し、全単語のリストを作りません。
照合用の不変ハンドルは発話開始時に取得し、教育・忘却や設定保存後の後続発話から新しい版を使用します。
Rustの辞書回帰テストはインメモリDBと `native/fixtures/dictionary/` の読み取り専用データを使用します。
テスト実行は別途明示的な指示がある場合に限ります。

## 実装時の静的検証

```powershell
python -m mypy --cache-dir .codex-type-check-cache src/livevoicebridge services/qwen3/src tools
python -m ruff check src services/qwen3/src tools
python -m ruff format --check src services/qwen3/src tools
cargo check --locked --manifest-path native/Cargo.toml --all-targets
cargo fmt --manifest-path native/Cargo.toml -- --check
cargo clippy --locked --manifest-path native/Cargo.toml --all-targets -- -D warnings
```

実装時のローカル検証は静的検査に限定します。Actionsでは、その成功後に両OSの配布ビルドと同梱内容の確認も行います。
ローカルのアプリ起動・配布ビルド・音声再生・テスト実行・負荷計測は、別途指示があるまで実行しません。
Pythonの `tests/` は現在ありません。Rust辞書の既存テストとfixtureは保持し、実行は明示的な指示がある場合に限ります。
未実施の実機検証と計測値を、検証済みとして報告しません。

protobuf変更時は `python tools/generate_protocol.py` が出す差分を確認し、apply_patchで適用します。
生成物はintegrations/youtube/generatedにコミットし、起動時のコード生成は行いません。

## 配布定義

正式配布はActionsで作成します。次は明示的にローカルでビルド確認をする場合のコマンドです。

```powershell
./build_rust.bat
./build_python.bat
```

Rustを変更していなければ `build_python.bat` だけを実行します。
本体・開発・配布用の依存は、特別な理由がない限り版を固定せず、ビルド時に間接依存も含めて最新版へ更新します。
Rustも `cargo update` を先に実行します。`Cargo.lock` は解決結果の記録として保持し、その後の `--locked` は
同じビルド工程内で解決結果が変わらないようにするために使用します。
依存側の互換条件はパッケージマネージャーに任せ、更新でAPI変更があればコードを新方式へ修正します。
`tools/build_python.ps1` は共通ツールの `python` コマンドを呼ぶ入口です。共通ツールが `venv` の作成と
本体・配布用Python依存の導入を行い、配置済みのRust拡張を使って `packaging/LiveVoiceBridge.spec` をPyInstallerに渡します。
同梱内容とバージョンもActionsと同じ処理で確認します。Rustのビルドや自動更新は行いません。
拡張がない場合や読み込めない場合は、Rust用batの実行を案内して停止します。
既存の `dist/LiveVoiceBridge/` はPyInstallerが確認なしで更新するため、配布先で生成した利用者データは
ビルド出力先に保存しないでください。両方のbatは終了時に一時停止し、ps1を直接実行する場合は停止しません。

Linuxでも `python tools/build.py python` で配布作成と検査を行います。Rust拡張は先に `rust` コマンドで配置してください。

`dist/LiveVoiceBridge/` をフォルダ単位で配布します。EXEと `_internal/` にフォーム・アイコン・
protobuf・Rust拡張を同梱し、単一EXEの外部一時展開は行いません。
DLL解析時のPATHはPythonとWindowsのディレクトリに限定し、開発ツール付属DLLの混入を防ぎます。

設定・辞書・効果音は配置先内のdataへ保存します。ソース起動ではリポジトリ直下を配置先とします。
AppData、OS一時フォルダ、レジストリを設定保存先には使用しません。
Qwen3用のJSONは `integrations/qwen/resources/` に置き、サービスのソース・`pyproject.toml` は配布時に同階層の `service/` へ同梱します。
開発時のサービスソースは `services/qwen3/` を使用します。
専用Python環境・OpenVINO依存・モデルは配布ビルド時には取得せず、アプリ内のQwen3セットアップが準備します。
例外として、YouTube生成コードが要求するgRPC・protobufの最低バージョンと、Qwen専用環境の固定依存は維持します。
Qwenの固定理由は `docs/qwen3.md` に記載しています。
Rust依存更新後は、配布作成の前に `build_rust.bat` で拡張を更新してください。

## 設定の互換性

リリース済み設定は自動変換とバックアップで互換性を維持します。変換は `integrations/storage/migrations.py`、
読み書き・バックアップ・原子的保存は `config.py` が担当します。内部コードの旧importや互換ラッパーは残しません。

## バージョンとActionsでの配布

正式バージョンの管理元はGitタグだけです。本体・Rust・Qwenの宣言は開発用の固定値 `0.0.0` とし、
リリース時に手作業で番号を書き換えません。設定の `schema_version` は独立して管理します。

PRとmain更新時は、Windows x64・Linux x64の静的検査・配布ビルド・同梱内容の確認を行い、成功・失敗をActionsで確認します。
配布物の圧縮と成果物の保存は行いません。リリースタグ時だけ、リリースへの添付用に圧縮・保存します。
このビルド確認ではアプリ起動・音声再生・テスト実行を行いません。
Linux配布はUbuntu 22.04でビルドし、ALSAなどのOS側ライブラリは利用環境に必要です。

正式配布物の作成は、公開するコミットへ次のようにタグを付けてpushします。これだけではリリースは作成・公開されません。

```powershell
git tag -a v0.99.3 -m "Release v0.99.3"
git push origin v0.99.3
```

タグは `vX.Y.Z` の後ろに任意の接尾辞を付けられます。`v0.9.0RC`、`v0.9.0preview`、`v0.9.0試作版` などを使用でき、
接尾辞の種類・大文字小文字・番号の有無は制限しません。数値部分の先頭ゼロはパッケージ用に除去します。
Python・Rustのバージョン制約に合わせ、接尾辞はUTF-8の16進表記へ変換して `+tag.x` の後ろへ付けます。
たとえば `v0.9.0RC` のパッケージバージョンは、本体・Rust・Qwen共通で `0.9.0+tag.x5243` です。
Gitタグ名は変更しません。更新確認は数値部分 `X.Y.Z` を比較し、同じ番号の接尾辞間には順序を付けません。
Actionsは元のタグ名とコミットを照合し、
`python tools/build.py ci` が `build/ci-source/` に生成したビルド用ソースだけにタグの番号を反映します。
この `ci` コマンドは共通のRust・Pythonビルド工程を順に呼び、タグ時だけ圧縮します。元のソースの変更や自動コミットは行いません。
ビルド用ソースとvenvは毎回新規に用意します。手動で同じCIコマンドを再実行する場合は、新しい作業コピーを使用してください。
本体は同梱パッケージメタデータから番号を取得するため、利用環境にGitは不要です。

両OSのビルドと同梱内容・番号の確認が成功したら、Actionsの成果物から両OSの圧縮ファイルを取得します。
GitHub Releaseを手動で作成し、ビルドに使用した既存タグを選び、その圧縮ファイルを添付して手動で公開します。
Actionsから取得する際の外側のダウンロード用ZIPではなく、その中の配布用ZIP・tar.gzを添付してください。
Actionsはリリースの作成・変更・添付・公開を行わず、リポジトリへの書き込み権限も使用しません。
ファイル名は `LiveVoiceBridge-Windows-x64.zip` と `LiveVoiceBridge-Linux-x64.tar.gz` で、番号を含めません。
どちらも展開すると `LiveVoiceBridge/` フォルダになります。Qwenの専用実行環境・モデルは含めません。
一部のビルドが失敗した場合はActionsの失敗ジョブを再実行し、両OSが成功してから手動で公開してください。
公開済みリリースは上書きせず、修正は新しい番号のタグで公開します。
