@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Everything is installed inside this folder. Nothing is added to PATH.
set "PYTHONUTF8=1"
set "UV_UNMANAGED_INSTALL=%~dp0.tools"
set "UV_PYTHON_INSTALL_DIR=%~dp0.tools\python"
set "UV_CACHE_DIR=%~dp0.tools\cache"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV=%~dp0.tools\uv.exe"

if not exist "%UV%" (
    echo [1/2] Downloading the setup tool. First run only, internet required...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/0.13.9/install.ps1 | iex"
)
if not exist "%UV%" goto failed

echo [2/2] Preparing RubriQ. The first run can take a few minutes...
"%UV%" sync --frozen --no-dev
if errorlevel 1 goto failed

"%UV%" run --frozen --no-dev python tools\launcher.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo RubriQ could not start. Check the internet connection and read the messages above.
pause
exit /b 1
