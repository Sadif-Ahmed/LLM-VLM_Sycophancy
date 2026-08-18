@echo off
REM ============================================================
REM setup_venv.bat
REM
REM Creates .venv at the repo root if it doesn't exist yet, then
REM installs requirements.txt into it. Idempotent - safe to re-run
REM any time deps change.
REM
REM Usage, from anywhere:
REM     scripts\setup_venv.bat
REM ============================================================

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Creating venv at %REPO_ROOT%\.venv
    python -m venv "%REPO_ROOT%\.venv"
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -m pip install -r "%REPO_ROOT%\requirements.txt"
