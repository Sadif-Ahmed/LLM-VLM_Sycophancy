@echo off
REM ============================================================
REM reset_hf_auth.bat
REM
REM Fixes "403 gated repo / not in the authorized list" on this
REM machine by pointing the probe scripts at the RIGHT token.
REM
REM What it does:
REM   1. Writes the given token to repo_root\hf_token.txt (no newline).
REM   2. Removes any stale HF_TOKEN env var (user scope + this shell) -
REM      resolve_hf_token() prefers HF_TOKEN over the file, so a leftover
REM      env var from an account without access silently wins otherwise.
REM   3. Clears the cached huggingface-cli login token.
REM   4. Verifies: whoami + a gated-file download for one model.
REM
REM Token source, in order: 1st arg, else existing repo_root\hf_token.txt,
REM else an interactive prompt.
REM
REM Usage, from anywhere:
REM     scripts\reset_hf_auth.bat [hf_xxxxxxxxxxxxx] [model_id]
REM     scripts\reset_hf_auth.bat            (reuse hf_token.txt / prompt)
REM model_id defaults to openbmb/MiniCPM-V-2_6.
REM ============================================================

setlocal
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "TOKEN=%~1"
set "MODEL=%~2"
if "%MODEL%"=="" set "MODEL=openbmb/MiniCPM-V-2_6"

if "%TOKEN%"=="" if exist "%REPO_ROOT%\hf_token.txt" (
    for /f "usebackq delims=" %%T in ("%REPO_ROOT%\hf_token.txt") do set "TOKEN=%%T"
    echo [ok] read token from hf_token.txt
)
if "%TOKEN%"=="" set /p "TOKEN=Paste HF token (hf_...): "
if "%TOKEN%"=="" echo [abort] no token given & exit /b 1
echo %TOKEN%| findstr /b /c:"hf_" >nul || (echo [abort] token must start with 'hf_' & exit /b 1)

REM --- 1. write token file, no trailing newline ---
<nul set /p "=%TOKEN%" > "%REPO_ROOT%\hf_token.txt"
echo [ok] wrote %REPO_ROOT%\hf_token.txt

REM --- 2. drop stale HF_TOKEN (future shells + this one) ---
set "INHERITED_HF_TOKEN=%HF_TOKEN%"
reg delete "HKCU\Environment" /F /V HF_TOKEN >nul 2>&1 && echo [ok] removed persistent HF_TOKEN env var
set "HF_TOKEN="

REM --- 3. clear cached huggingface-cli login ---
del /q "%USERPROFILE%\.cache\huggingface\token" >nul 2>&1 && echo [ok] cleared ~/.cache/huggingface/token
if defined HF_HOME del /q "%HF_HOME%\token" >nul 2>&1

REM --- 4. verify ---
echo.
echo Verifying against %MODEL% ...
"%PYTHON%" -c "import sys; from huggingface_hub import HfApi; t=open(r'%REPO_ROOT%\hf_token.txt').read().strip(); a=HfApi(token=t); print('token account:', a.whoami()['name']); a.hf_hub_download(r'%MODEL%','config.json'); print('gated access: OK')" || (echo [fail] still no access - request it at https://huggingface.co/%MODEL% with the SAME account printed above & exit /b 1)

echo.
if defined INHERITED_HF_TOKEN (
    echo ============================================================
    echo [WARNING] The shell you launched this from STILL has a live
    echo HF_TOKEN set - the sweep will keep using it ^(and 403^) because
    echo resolve_hf_token^(^) checks HF_TOKEN before hf_token.txt.
    echo A bat cannot clear its parent shell. Do ONE of:
    echo   PowerShell:  Remove-Item Env:HF_TOKEN
    echo   cmd.exe   :  set "HF_TOKEN="
    echo   or just open a brand-new terminal.
    echo Then: echo %%HF_TOKEN%%   must print blank before you re-run.
    echo ============================================================
) else (
    echo [done] hf_token.txt is now the only token source. Re-run the sweep.
)
endlocal
