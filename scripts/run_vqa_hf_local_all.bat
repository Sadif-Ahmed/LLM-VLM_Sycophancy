@echo off
REM ============================================================
REM run_vqa_hf_local_all.bat
REM
REM Runs vqa_sycophancy_probe_hf_local.py across all 4 evidence
REM conditions (image, grounded, none, blind) x all 3 prompt-set
REM variants (default, neighbor_nurse_doctor, generic) - 12 runs
REM total, for one --model on this machine's own GPU. Unlike the
REM NIM run_vqa_*.bat scripts, this is NOT meant to be launched
REM alongside anything else that also wants the GPU (there's only
REM one model/device to share), so this just runs everything
REM sequentially.
REM
REM Usage, from anywhere:
REM     scripts\run_vqa_hf_local_all.bat --model MODEL [options]
REM
REM Requires: .venv already created at the repo root (with torch +
REM transformers installed - see scripts\setup_env.bat), target
REM dataset already downloaded to disk, pres_yes.png/pres_no.png
REM present at repo_root\prescriptions\ (only needed for the image/
REM grounded conditions, but always resolved here since 2 of the 4
REM conditions use them).
REM ============================================================

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT_PY=%REPO_ROOT%\vqa_sycophancy_probe_hf_local.py"
set "PROOF_YES=%REPO_ROOT%\prescriptions\pres_yes.png"
set "PROOF_NO=%REPO_ROOT%\prescriptions\pres_no.png"

set "MODEL="
set "N=20"
set "DATASET_DIR=%REPO_ROOT%\data\vqa_rad_yesno"
set "SPLIT=train"
set "SEED=42"
set "PUSHBACK_TURNS=10"
set "DEVICE=auto"
set "TRUST_REMOTE_CODE="
set "LOAD_IN_4BIT="
set "RUNNER="
set "DRY_RUN=0"

:parse_args
if "%~1"=="" goto :after_parse
if /i "%~1"=="--model" (set "MODEL=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--n" (set "N=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--dataset-dir" (set "DATASET_DIR=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--split" (set "SPLIT=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--seed" (set "SEED=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--pushback-turns" (set "PUSHBACK_TURNS=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--device" (set "DEVICE=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--trust-remote-code" (set "TRUST_REMOTE_CODE=--trust-remote-code" & shift & goto :parse_args)
if /i "%~1"=="--load-in-4bit" (set "LOAD_IN_4BIT=--load-in-4bit" & shift & goto :parse_args)
if /i "%~1"=="--runner" (set "RUNNER=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--dry-run" (set "DRY_RUN=1" & shift & goto :parse_args)
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
echo Unknown arg: %~1
goto :usage

:after_parse
if "%MODEL%"=="" goto :usage

if not exist "%PYTHON%" (
    echo [error] venv python not found at "%PYTHON%"
    echo         Create it first: scripts\setup_env.bat
    exit /b 1
)
if not exist "%SCRIPT_PY%" (
    echo [error] vqa_sycophancy_probe_hf_local.py not found at "%SCRIPT_PY%"
    exit /b 1
)

set "RUNNER_ARGS="
if not "%RUNNER%"=="" set "RUNNER_ARGS=--runner %RUNNER%"

set /a RUN_COUNT=0
set /a FAIL_COUNT=0

for %%E in (image grounded none blind) do (
    set "NEEDS_PROOF=0"
    if "%%E"=="image" set "NEEDS_PROOF=1"
    if "%%E"=="grounded" set "NEEDS_PROOF=1"

    for %%P in (default neighbor_nurse_doctor generic) do (
        set /a RUN_COUNT+=1
        if "!NEEDS_PROOF!"=="1" (
            echo === "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS! ===
            if "!DRY_RUN!"=="0" (
                "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS!
                if errorlevel 1 (
                    set /a FAIL_COUNT+=1
                    echo !!! FAILED: evidence=%%E prompt-set=%%P !!!
                )
            )
        ) else (
            echo === "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS! ===
            if "!DRY_RUN!"=="0" (
                "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS!
                if errorlevel 1 (
                    set /a FAIL_COUNT+=1
                    echo !!! FAILED: evidence=%%E prompt-set=%%P !!!
                )
            )
        )
    )
)

echo.
echo === Done: !RUN_COUNT! runs attempted, !FAIL_COUNT! failed ===
if !FAIL_COUNT! gtr 0 exit /b 1
exit /b 0

:usage
echo Usage: %~nx0 --model MODEL [options]
echo.
echo   --model MODEL           required. HF Hub model id to load locally
echo   --n N                   questions per run (default: 20)
echo   --dataset-dir DIR       default: %REPO_ROOT%\data\vqa_rad_yesno
echo   --split train^|test      default: train
echo   --seed SEED             default: 42
echo   --pushback-turns 1-10   escalation depth (default: 10)
echo   --device auto^|cuda^|cpu default: auto
echo   --trust-remote-code     pass through to from_pretrained (needed for some Hub models)
echo   --load-in-4bit          load via bitsandbytes NF4 quantization
echo   --runner NAME           override auto-detected username@hostname
echo   --dry-run               print commands without running them
exit /b 1
