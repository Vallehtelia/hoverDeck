@echo off
rem ============================================================
rem  HoverDeck - build the standalone Windows executable.
rem  Produces dist\HoverDeck.exe via PyInstaller (build.py).
rem  Run run-windows.bat at least once first (creates the venv).
rem ============================================================
setlocal
title HoverDeck build

set "REPO=%~dp0"
set "VENV=%LOCALAPPDATA%\HoverDeck\winvenv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo [HoverDeck] No venv yet. Run run-windows.bat once first.
    pause
    exit /b 1
)

"%PY%" -m pip install "pyinstaller>=6.0"

pushd "%REPO%"
"%PY%" build.py
popd

echo.
echo [HoverDeck] If it succeeded, the exe is at: %REPO%dist\HoverDeck.exe
echo            (Tip: if PyInstaller chokes on the \\wsl.localhost path,
echo             copy the repo to a local Windows folder and build there.)
pause
