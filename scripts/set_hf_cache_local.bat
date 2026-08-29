@echo off
REM ============================================================
REM set_hf_cache_local.bat
REM
REM 1. Deletes the existing Hugging Face model cache on the C drive
REM    (%USERPROFILE%\.cache\huggingface\hub and \xet).
REM 2. Repoints HF_HOME to <repo>\data\huggingface so every future
REM    model/dataset download lands inside the repo's data\ folder
REM    (already .gitignore'd, so the multi-GB blobs never get staged).
REM
REM DESTRUCTIVE: step 1 removes downloaded model weights. They will
REM re-download on next use. Asks for confirmation first.
REM
REM Usage, from anywhere:
REM     scripts\set_hf_cache_local.bat
REM
REM Note: setx only affects NEW shells. This script also sets HF_HOME
REM for the current window so you can use it immediately; other
REM already-open terminals need to be reopened.
REM ============================================================

setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "HF_TARGET=%REPO_ROOT%\data\huggingface"
set "C_CACHE=%USERPROFILE%\.cache\huggingface"

echo.
echo Current HF_HOME (user)   : %HF_HOME%
echo C-drive cache to delete  : %C_CACHE%\hub
echo                            %C_CACHE%\xet
echo New HF_HOME              : %HF_TARGET%
echo.

if exist "%C_CACHE%\hub" (
    powershell -NoProfile -Command "$b=(Get-ChildItem -LiteralPath '%C_CACHE%' -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum; if($b){'{0:N2} GB in {1}' -f ($b/1GB), '%C_CACHE%'}else{'(empty)'}"
) else (
    echo No cache found at %C_CACHE% - nothing to delete, will still repoint HF_HOME.
)
echo.

choice /c YN /n /m "Proceed with delete + repoint? [Y/N] "
if errorlevel 2 (
    echo Aborted. Nothing changed.
    exit /b 1
)

echo.
if exist "%C_CACHE%\hub" (
    echo Removing "%C_CACHE%\hub" ...
    rmdir /s /q "%C_CACHE%\hub"
)
if exist "%C_CACHE%\xet" (
    echo Removing "%C_CACHE%\xet" ...
    rmdir /s /q "%C_CACHE%\xet"
)

if not exist "%HF_TARGET%" mkdir "%HF_TARGET%"

setx HF_HOME "%HF_TARGET%" >nul
if errorlevel 1 (
    echo [error] setx HF_HOME failed
    exit /b 1
)
endlocal & set "HF_HOME=%HF_TARGET%"

echo.
echo Done.
echo   HF_HOME persisted for your user account   : %HF_HOME%
echo   Also set for THIS window.
echo   Reopen other terminals to pick up the change.
echo.
echo If you also have an old cache elsewhere (e.g. E:\huggingface from a
echo previous HF_HOME), delete that folder manually - this script only
echo touches the C-drive default.
exit /b 0
