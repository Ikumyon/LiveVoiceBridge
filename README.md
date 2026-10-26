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

[Releases](https://github.com/Ikumyon/LiveVoiceBridge/releases)のAssetsからOS用の配布物を取得し、
フォルダ単位で展開して起動します。`_internal/` も実行ファイルと一緒に配置してください。
設定画面でAPIキーと音声エンジンを設定し、配信URLを入力して開始します。
Qwenを使う場合は[モデルと環境の準備](docs/users/qwen3.md)が必要です。

## ライセンス

[LICENSE](LICENSE)を参照してください。
