@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_rust.ps1" %*
set "build_exit_code=%errorlevel%"
echo.
if not "%build_exit_code%"=="0" echo Rust build failed with exit code %build_exit_code%.
pause
exit /b %build_exit_code%
