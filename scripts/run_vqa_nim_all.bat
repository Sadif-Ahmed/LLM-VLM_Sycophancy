@echo off
REM ============================================================
REM run_vqa_nim_all.bat
REM
REM Runs all 4 evidence conditions (image, grounded, none, blind)
REM x all 3 prompt-set variants (default, neighbor_nurse_doctor,
REM generic) against a NIM/OpenRouter --model - 12 runs total,
REM sequentially, same shape as run_vqa_hf_local_all.bat but for
REM the API-based unified script (vqa_sycophancy_probe.py --evidence)
REM instead of the local-GPU one. Since these hit an API rather than
REM sharing one GPU, you can still launch this alongside another
REM instance against a different model - just halve --rpm on each.
REM
REM Usage, from anywhere:
REM     scripts\run_vqa_nim_all.bat --model MODEL [options]
REM
REM Requires: .venv already created at the repo root, target
REM dataset already downloaded to disk, pres_yes.png/pres_no.png
REM present at repo_root\prescriptions\ (only needed for the
REM image/grounded conditions, but always resolved here since 2
REM of the 4 conditions use them).
REM ============================================================

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT_PY=%REPO_ROOT%\vqa_sycophancy_probe.py"
set "PROOF_YES=%REPO_ROOT%\prescriptions\pres_yes.png"
set "PROOF_NO=%REPO_ROOT%\prescriptions\pres_no.png"

set "MODEL="
set "N=20"
set "DATASET_DIR=%REPO_ROOT%\data\vqa_rad_yesno"
set "PROVIDER=nvidia"
set "SPLIT=train"
set "SEED=42"
set "PUSHBACK_TURNS=10"
set "RPM="
set "DRY_RUN=0"

:parse_args
if "%~1"=="" goto :after_parse
if /i "%~1"=="--model" (set "MODEL=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--n" (set "N=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--dataset-dir" (set "DATASET_DIR=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--provider" (set "PROVIDER=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--split" (set "SPLIT=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--seed" (set "SEED=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--pushback-turns" (set "PUSHBACK_TURNS=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--rpm" (set "RPM=%~2" & shift & shift & goto :parse_args)
if /i "%~1"=="--dry-run" (set "DRY_RUN=1" & shift & goto :parse_args)
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
echo Unknown arg: %~1
goto :usage

:after_parse
if "%MODEL%"=="" goto :usage

if not exist "%PYTHON%" (
    echo [error] venv python not found at "%PYTHON%"
    echo         Create it first: python -m venv .venv, then pip install openai httpx tenacity datasets pillow
    exit /b 1
)
if not exist "%SCRIPT_PY%" (
    echo [error] vqa_sycophancy_probe.py not found at "%SCRIPT_PY%"
    exit /b 1
)

set "RPM_ARGS="
if not "%RPM%"=="" set "RPM_ARGS=--rpm %RPM%"

set /a RUN_COUNT=0
set /a FAIL_COUNT=0

for %%E in (image grounded none blind) do (
    set "NEEDS_PROOF=0"
    if "%%E"=="image" set "NEEDS_PROOF=1"
    if "%%E"=="grounded" set "NEEDS_PROOF=1"

    for %%P in (default neighbor_nurse_doctor generic) do (
        set /a RUN_COUNT+=1
        if "!NEEDS_PROOF!"=="1" (
            echo === "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --provider %PROVIDER% --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" !RPM_ARGS! ===
            if "!DRY_RUN!"=="0" (
                "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --provider %PROVIDER% --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" !RPM_ARGS!
                if errorlevel 1 (
                    set /a FAIL_COUNT+=1
                    echo !!! FAILED: evidence=%%E prompt-set=%%P !!!
                )
            )
        ) else (
            echo === "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --provider %PROVIDER% --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% !RPM_ARGS! ===
            if "!DRY_RUN!"=="0" (
                "%PYTHON%" "%SCRIPT_PY%" --model "%MODEL%" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --provider %PROVIDER% --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% !RPM_ARGS!
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
echo   --model MODEL           required. Vision-capable model name (or comma-separated fallback list)
echo   --n N                   questions per run (default: 20)
echo   --dataset-dir DIR       default: %REPO_ROOT%\data\vqa_rad_yesno
echo   --provider nvidia^|openrouter   default: nvidia
echo   --split train^|test      default: train
echo   --seed SEED             default: 42
echo   --pushback-turns 1-10   escalation depth (default: 10)
echo   --rpm N                 override provider's default requests/min (halve this when running two of these at once against the same API key)
echo   --dry-run               print commands without running them
exit /b 1
