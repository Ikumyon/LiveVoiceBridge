# Development checks

PowerShell、シェル、Pythonソース、設定ファイルはUTF-8として扱います。

## Setup

Windows:

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
maturin develop --release --manifest-path rust_native\Cargo.toml
```

Linux:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install pytest pytest-qt ruff mypy maturin PySide6 requests emoji
maturin develop --release --manifest-path rust_native/Cargo.toml
```

Linuxでアプリ本体を実行する際の推論バックエンド依存関係は、使用するTTSエンジンに合わせて別途導入します。上記は段階0の品質チェックに必要な最小構成です。

## Verification

```powershell
python -m compileall -q main.py core src tests
ruff check main.py src tests
ruff format --check main.py src tests
mypy main.py src/livevoicebridge tests
pytest
cargo fmt --manifest-path rust_native/Cargo.toml -- --check
cargo clippy --manifest-path rust_native/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path rust_native/Cargo.toml
```

段階0では既存コードをキャラクタリゼーション対象としているため、Pythonのlintと型検査は新しいテストから開始します。以降のリワークで移行済みモジュールを検査対象へ順次追加します。
