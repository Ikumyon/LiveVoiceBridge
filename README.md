# LiveVoiceBridge

YouTube Live のコメントを YouTube Data API v3 の `liveChatMessages.streamList` で低遅延取得し、VOICEVOX API に渡して読み上げる PySide6 アプリです。

## ファイル

- `main.py` - アプリ本体
- `ui/` - Qt Designerで編集できるUIファイル群
- `core/stream_list.proto` - YouTube公式streamList用のgRPC定義
- `requirements.txt` - Pythonライブラリ
- `run_linux.sh` - Linux Mint向け起動補助
- `run_windows.ps1` - Windows向け起動補助

## Linux Mint

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip alsa-utils
cd LiveVoiceBridge
./run_linux.sh
```

## Windows

PowerShellで以下を実行します。

```powershell
cd LiveVoiceBridge
.\run_windows.ps1
```

PowerShellの実行ポリシーで止まる場合は、同じフォルダで手動実行してください。

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## 使い方

1. VOICEVOXを起動する。
2. 設定メニュー（...ボタン）からスピーカー（声の種類）を設定する。
3. YouTube Data API v3 のAPIキーを入力する。
4. YouTube Live URL または動画IDを入力する。
5. `接続開始` を押す。

## 注意

- 初回起動時に `core/stream_list.proto` から `stream_list_pb2.py` と `stream_list_pb2_grpc.py` を自動生成します。
- APIキーは `QSettings` に保存されます。共有PCでは注意してください。
- 読み上げ先は現在VOICEVOX API互換の `/audio_query` と `/synthesis` を想定しています。
