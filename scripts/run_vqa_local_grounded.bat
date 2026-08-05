@echo off
REM ============================================================
REM run_vqa_local_grounded.bat
REM
REM Windows port of run_vqa_local_grounded.sh. Runs
REM vqa_sycophancy_probe_local_grounded.py (in-process transformers
REM inference, no API/provider/rate-limit) across all 3 prompt-set
REM variants - the local-inference equivalent of run_vqa_grounded.bat.
REM Kept as its own script rather than folded into run_vqa_local.bat,
REM matching how the grounded probe itself is kept separate from the
REM image/none-unified script.
REM
REM Usage, from anywhere:
REM     scripts\run_vqa_local_grounded.bat [options]
REM
REM Requires: .venv already created at the repo root (with torch +
REM transformers installed), target dataset already downloaded to
REM disk, pres_yes.png/pres_no.png present at the repo root.
REM ============================================================

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT_PY=%REPO_ROOT%\vqa_sycophancy_probe_local_grounded.py"
set "PROOF_YES=%REPO_ROOT%\pres_yes.png"
set "PROOF_NO=%REPO_ROOT%\pres_no.png"

set "MODEL=HuggingFaceTB/SmolVLM-256M-Instruct"
set "N=20"
set "DATASET_DIR=%REPO_ROOT%\data\vqa_rad_yesno"
set "SPLIT=train"
set "SEED=42"
set "PUSHBACK_TURNS=10"
set "DRY_RUN=0"

:parse_args
if "%~1"=="" goto :after_parse
if /i "%~1"=="--model" (set "MODEL=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--n" (set "N=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--dataset-dir" (set "DATASET_DIR=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--split" (set "SPLIT=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--seed" (set "SEED=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--pushback-turns" (set "PUSHBACK_TURNS=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--dry-run" (set "DRY_RUN=1" & shift & goto :parse_args)
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
echo Unknown arg: %~1
goto :usage

:after_parse

if not exist "%PYTHON%" (
    echo [error] venv python not found at "%PYTHON%"
    echo         Create it first: python -m venv .venv, then pip install torch transformers pillow datasets
    exit /b 1
)
if not exist "%SCRIPT_PY%" (
    echo [error] vqa_sycophancy_probe_local_grounded.py not found at "%SCRIPT_PY%"
    exit /b 1
)

set /a RUN_COUNT=0
set /a FAIL_COUNT=0

for %%P in (default neighbor_nurse_doctor generic) do (
    set /a RUN_COUNT+=1
    echo === "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" ===
    if "!DRY_RUN!"=="0" (
        "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%"
        if errorlevel 1 (
            set /a FAIL_COUNT+=1
            echo !!! FAILED: prompt-set=%%P !!!
        )
    )
)

echo.
echo === Done: !RUN_COUNT! runs attempted, !FAIL_COUNT! failed ===
if !FAIL_COUNT! gtr 0 exit /b 1
exit /b 0

:usage
echo Usage: %~nx0 [options]
echo.
echo   --model MODEL           HF Hub model id to load locally (default: HuggingFaceTB/SmolVLM-256M-Instruct)
echo   --n N                   questions per run (default: 20)
echo   --dataset-dir DIR       default: %REPO_ROOT%\data\vqa_rad_yesno
echo   --split train^|test      default: train
echo   --seed SEED             default: 42
echo   --pushback-turns 1-10   escalation depth (default: 10)
echo   --dry-run               print commands without running them
exit /b 1
