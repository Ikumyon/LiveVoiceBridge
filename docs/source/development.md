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

環境作成・依存導入は `.github/scripts/environment.py`、UI変換は `.github/scripts/generate_ui.py`、
Rust/Pythonのビルドと配布検査は `.github/scripts/build.py` が担当します。
ビルド側は環境準備・変換の共通関数を呼び、同じ処理を再実装しません。
アプリ起動はビルドツールの責務に含めません。

## ソースから起動

上記のPython・Rust・OSごとのビルド環境に加えて、ソース取得用のGitを用意します。
PythonとRustツールチェーン自体は、あらかじめインストールしてください。
Linuxはデスクトップのグラフィカル環境から起動します。

まずリポジトリを取得し、ルートディレクトリへ移動します。

```text
git clone https://github.com/Ikumyon/LiveVoiceBridge.git
cd LiveVoiceBridge
```

### Windows

通常版CPython 3.14以降を `python` で呼べるPowerShellを使用します。
次の順に、仮想環境・依存の準備、Rust拡張のビルド、UI生成、起動を行います。

```powershell
$env:PYTHONUTF8 = "1"
python .github/scripts/environment.py dev
./venv/Scripts/python.exe .github/scripts/build.py rust
./venv/Scripts/python.exe .github/scripts/generate_ui.py
./venv/Scripts/python.exe -m livevoicebridge
```

### Linux

次の `python3` は、通常版CPython 3.14以降を指す必要があります。

```bash
export PYTHONUTF8=1
python3 .github/scripts/environment.py dev
./venv/bin/python .github/scripts/build.py rust
./venv/bin/python .github/scripts/generate_ui.py
./venv/bin/python -m livevoicebridge
```

### 2回目以降

リポジトリのルートで、Windowsは `./venv/Scripts/python.exe -m livevoicebridge`、
Linuxは `./venv/bin/python -m livevoicebridge` を実行します。仮想環境のactivateは不要です。
ソースの `.py` を直接開いたり、`__main__.py` を単独実行したりせず、`-m livevoicebridge` を使います。

Python依存が変わった場合は、上記の `environment.py dev` を再実行します。
`.ui` を編集・更新した場合は、仮想環境のPythonで `generate_ui.py` を再実行してから起動します。
Rustソースを更新した場合は、仮想環境のPythonで `build.py rust` を再実行します。
直接起動する場合も、生成済みUIと登録済みRust拡張が必要です。型チェックだけでは準備されません。

環境ツールは `dev`・`ui`・`rust`・`package` の依存プロファイルを持ちます。
開発用は本体と開発依存、UI用はPySide6を導入し、依存定義の指紋を `venv/` 内に保存します。
初回・依存定義変更時だけpipを実行し、明示的な更新は `--update-dependencies` で行います。
不完全なvenvは自動削除せず停止します。PythonとRustツールチェーン自体は自動インストールしません。

`.github/scripts/build.py check-native` はRust拡張の未準備を終了コード2で通知します。
Rustソース変更時の再ビルドは明示的に行います。

## 実装時の検証

通常の実装作業で実行する検証は型チェックと静的検査に限定します。
アプリ起動・配布ビルド・音声再生・テスト実行・負荷計測は、別途明示的な指示がある場合だけ行います。

```powershell
python -m mypy --cache-dir .codex-type-check-cache src/livevoicebridge services/qwen3/src .github/scripts
python -m ruff check src services/qwen3/src .github/scripts
python -m ruff format --check src services/qwen3/src .github/scripts
cargo check --locked --manifest-path native/Cargo.toml --all-targets
cargo fmt --manifest-path native/Cargo.toml -- --check
cargo clippy --locked --manifest-path native/Cargo.toml --all-targets -- -D warnings
```

Pythonの生成protobufコードと `ui_*.py` はRuff・mypyの対象から除外しています。
Rustには辞書・解析・DSP等のテストがありますが、`--all-targets` の静的検査では実行しません。
未実施の実機検証や性能測定を検証済みとして扱いません。

## Designerフォームの生成

画面の編集元は `.ui` のみです。本体の `desktop/resources/forms/` と内蔵プラグインのフォームを対象に、
`pyside6-uic` と同じPySide6のコンパイラーで、各 `.ui` と同じディレクトリへ `ui_名前.py` を生成します。
例えば `main_window.ui` は `ui_main_window.py`、Qwenの `settings.ui` は同じフォルダーの `ui_settings.py` です。
生成ファイルは直接編集せず、Git管理にも含めません。

```powershell
./venv/Scripts/python.exe .github/scripts/generate_ui.py
./venv/Scripts/python.exe .github/scripts/generate_ui.py --force
./venv/Scripts/python.exe .github/scripts/generate_ui.py --check
```

通常の生成は入力内容・変換ツールの版・生成スクリプトの変更を指紋で判定し、変更分だけを更新します。
削除済みフォームに対応する、このツールで生成したPythonも削除します。
`--force` とPython配布ビルドでは全フォームを再生成し、変換失敗時は続行しません。
`--check` は生成物の確認だけを行い、ファイルを作成・変更・削除しません。
その他の生成コマンドはコード生成を伴います。生成処理は通常の静的検査には含めません。

開発時・配布版とも各画面が対応する生成モジュールを直接importします。
生成された `create_form()` と共通の `setup_form()` がルートの生成・再利用を担当し、
独自ウィジェットは `.ui` のpromoted widget定義から構築します。
実行時のXML読み込み、QtUiTools、QUiLoader、旧方式へのフォールバックはありません。
生成物がない状態でアプリを直接起動するとimportエラーになります。先に生成してください。

## protobufの更新

YouTubeのprotoと生成済みPythonは `integrations/youtube/generated/` に配置します。
protobufを更新した際は生成コードの差分を確認し、`apply_patch` で適用します。
アプリ起動時のコード生成やsys.pathの書き換えはありません。
生成コードに合わせ、grpcioとprotobufには最低版を設定しています。

## ローカルビルドの契約

環境作成・依存導入の共通実装は `.github/scripts/environment.py` です。
Rust拡張・Python配布・同梱検査の共通実装は `.github/scripts/build.py` です。
以下はビルドを明示的に実施する場合の入口です。

| 目的 | 共通コマンド |
| --- | --- |
| Rust拡張を更新 | `python .github/scripts/build.py rust` |
| Rust拡張の登録を確認 | `python .github/scripts/build.py check-native` |
| 配布フォルダを作成 | `python .github/scripts/build.py python` |
| CI用ソースから両工程を実施 | `python .github/scripts/build.py ci` |

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
フォームごとの生成Python・アイコン・protobuf・Rust拡張・パッケージメタデータと、
QwenのOS別JSON・サービスソース・pyprojectを同梱します。
`.ui`・QtUiTools・開発用変換ツールは配布物へ同梱しません。
生成PythonはPyInstallerの通常モジュールとして格納し、平文ファイルとしての配置は不要です。
UI変換は対象Python環境のPySide6 Essentialsに含まれる `uic` 本体を直接実行します。
ツールの場所の取得・バージョン取得・各フォームの変換には、それぞれ60秒の制限を設け、
停止した場合は対象コマンドを示してビルドを失敗させます。
Qwen専用Python・推論依存・モデルは配布ビルド時に取得しません。

単一EXE形式による外部一時展開は使用しません。
WindowsのDLL解析時PATHはPythonとWindowsのディレクトリへ限定します。
同梱検査は必須ファイル・バージョン・サービスソースの一致に加え、
実行ファイル内の全生成フォームモジュールの収録と、`.ui`・QtUiToolsの不在を確認します。

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

### Linux配布版のFcitx入力プラグイン

Linux x64の配布ビルドは、CI・ローカルとも共通ビルド処理で `fcitx5-qt` を生成します。
ソースからの開発起動では自動導入しません。
ローカルで配布ビルドする場合も、次の開発用依存が必要です（Debian/Ubuntu）。

```bash
sudo apt-get install -y \
  build-essential cmake ninja-build extra-cmake-modules pkg-config git binutils patchelf \
  libasound2-dev libx11-dev libxcb1-dev libxkbcommon-dev libxkbcommon-x11-dev \
  libgl-dev libegl1-mesa-dev libwayland-dev
```

Pythonの配布用依存にはLinux限定で `aqtinstall` を含めます。
依存更新後のPySide6から実際のQtバージョンを取得し、同じ版のQt desktop SDKを取得します。
SDKに含まれるQt Wayland clientとprivate headersも使用します。
SDK・ソース・コンパイル用ファイルは `build/fcitx5/` 配下の一時ディレクトリで扱い、
毎回ビルドして処理終了時に削除します。初回以外もSDKのダウンロードが必要です。
同じ版のSDKが取得できない場合や、CMakeがSDK外のQtを選択した場合は失敗します。

`fcitx5-qt` は5.1.16、コミット `115750044f3d0db16ca5859808c7da830fd1ff52` に固定します。
Qt 6・X11・Wayland対応の動的プラグインのみをRelease構成で生成します。
Qtの内部APIを使用するため、PySide6のQtが更新された場合も同じ版のSDKで再ビルドします。
SDKのQtライブラリ本体は配布せず、PySide6が同梱するQtを使用します。

生成物をビルド用venvの `platforminputcontexts/` に配置し、PyInstallerの標準フックで収集します。
配布先は `_internal/PySide6/Qt/plugins/platforminputcontexts/libfcitx5platforminputcontextplugin.so`、
ライセンスとソースコミット・Qtバージョンの記録は `_internal/licenses/fcitx5-qt/` です。
同梱検査はプラグインとライセンスの存在、版の一致、`ldd` による依存解決、
Qt依存が配布物内を参照すること、`readelf` によるSDKへの絶対パス残存を確認します。
アプリ起動や日本語入力の検証は行いません。

実行環境にはOS側でFcitx本体とMozcなどの日本語入力エンジンが必要です。
本体は `QT_IM_MODULE` などを上書きせず、利用環境のFcitx・IBus・Waylandの選択に従います。

### ワークフローと公開

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
5. GitHub APIで両Assetsのアップロード完了と、添付元ファイルとのサイズ一致を確認します。

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
- [共通ビルド](../../.github/scripts/build.py)、[PyInstaller定義](../../packaging/LiveVoiceBridge.spec)
- [環境準備](../../.github/scripts/environment.py)、[UI生成](../../.github/scripts/generate_ui.py)
- [ビルドワークフロー](../../.github/workflows/build.yml)、[静的検査](../../.github/workflows/quality.yml)
