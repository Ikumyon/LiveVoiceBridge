# LiveVoiceBridge

YouTube Liveのチャットを取得し、VOICEVOX・COEIROINK・棒読みちゃん・Qwen3-TTSで読み上げる、
Windows・Linux向けのデスクトップアプリです。

コメント内の音声制御、効果音、読み替え辞書、PiPコメント表示、システム監視に対応します。
設定・辞書・Qwen専用環境はアプリ配置先内で管理します。

## ドキュメント

| 読む人 | 入口 |
| --- | --- |
| 一般利用者 | [導入と使い方](docs/users/README.md) |
| プラグイン利用者 | [TTSプラグイン](docs/plugins/README.md) |
| ソースコードを読む人・開発者 | [ソースコード案内](docs/source/README.md) |

詳しい機能仕様は[ドキュメント一覧](docs/README.md)から確認できます。
内蔵TTSと外部TTSは共通のプラグイン方式で扱います。外部プラグインはアプリ直下のpluginsへの配置・削除で導入・削除できます。

## 利用を始める

### ビルド済みで起動

1. [Releases](https://github.com/Ikumyon/LiveVoiceBridge/releases)のAssetsから、Windowsは `LiveVoiceBridge-Windows-x64.zip`、Linuxは `LiveVoiceBridge-Linux-x64.tar.gz` を取得します。
2. 書き込み可能な場所へフォルダ単位で展開します。`_internal/` は実行ファイルと一緒に残してください。
3. Windowsは `LiveVoiceBridge.exe`、Linuxは `LiveVoiceBridge` を起動します。PythonやRustのインストールは不要です。
4. 設定画面でAPIキーと音声エンジンを設定し、配信URLを入力して開始します。

詳しくは[導入と使い方](docs/users/README.md)を参照してください。
Qwenを使う場合は[モデルと環境の準備](docs/users/qwen3.md)も必要です。

### ソースから起動

1. 通常版CPython 3.14以降、Rust stable 1.95以降と、OSごとのビルド環境を用意します。
2. リポジトリを取得し、ルートディレクトリで仮想環境・依存を準備します。
3. Rust拡張をビルドし、Designerの `.ui` をPythonへ変換します。
4. 仮想環境のPythonで `python -m livevoicebridge` を実行します。

Windows・Linuxそれぞれのコマンドは[ソースから起動する手順](docs/source/development.md#ソースから起動)を参照してください。

## ライセンス

[LICENSE](LICENSE)を参照してください。
