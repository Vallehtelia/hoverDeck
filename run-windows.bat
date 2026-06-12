@echo off
rem ============================================================
rem  HoverDeck - Windows dev launcher
rem  Runs the current source (incl. code edited in WSL) on Windows,
rem  where frameless / always-on-top / tray / hotkeys work for real.
rem  No rebuild needed: edit in WSL, then re-run this file.
rem
rem  First run creates a Windows venv under %LOCALAPPDATA%\HoverDeck
rem  (kept OUT of the repo so it never clashes with the Linux .venv).
rem  Requires Python 3.11+ installed on Windows (https://python.org).
rem ============================================================
setlocal
title HoverDeck (Windows)

set "REPO=%~dp0"
set "VENV=%LOCALAPPDATA%\HoverDeck\winvenv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo [HoverDeck] First run: creating Windows venv at "%VENV%"
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv "%VENV%"
    ) else (
        py -3 -m venv "%VENV%"
    )
    if not exist "%PY%" (
        echo.
        echo [HoverDeck] ERROR: could not create the venv.
        echo            Install Python 3.11+ from https://python.org and re-run.
        pause
        exit /b 1
    )
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r "%REPO%requirements-windows.txt"
)

rem Self-heal: if a required package is missing (e.g. one added in an update),
rem (re)install the requirements into the existing venv.
"%PY%" -c "import psutil, PyQt6, cryptography" 1>nul 2>nul
if errorlevel 1 (
    echo [HoverDeck] Installing/updating dependencies...
    "%PY%" -m pip install -r "%REPO%requirements-windows.txt"
)

rem pushd maps the (possibly \\wsl.localhost\...) path to a temp drive so
rem main.py runs with the repo root on sys.path -> "import hoverdeck" works.
pushd "%REPO%"
echo [HoverDeck] Launching. Quit from the deck: right-click -^> Quit HoverDeck
"%PY%" main.py
popd
