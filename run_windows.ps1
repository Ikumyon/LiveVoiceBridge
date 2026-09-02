Set-Location $PSScriptRoot
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\venv\Scripts\maturin.exe develop --release --manifest-path rust_native\Cargo.toml
.\venv\Scripts\python.exe main.py
