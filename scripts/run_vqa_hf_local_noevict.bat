@echo off
REM ============================================================
REM run_vqa_hf_local_noevict.bat
REM
REM Runs vqa_sycophancy_probe_hf_local_no_evict.py across its 2
REM supported evidence conditions (image, none) x all 3 prompt-set
REM variants (default, neighbor_nurse_doctor, generic) - 6 runs
REM per model, on this machine's own GPU.
REM
REM With no --model, loops the 9 locally-runnable VLMs from
REM LOCAL_VLM_CONVERSATIONAL_RANKING.md (see MODEL_LIST below) -
REM 60 runs total, sequentially. Pass --model MODEL to run just
REM that one model instead (6 runs).
REM
REM SOTA-FAITHFUL. The no-eviction variant never strips old images to
REM text, matching how standard multi-turn VLM dialogue works - every
REM image stays in context. So "image" here = the real scan (turn 0)
REM and the fake prescription (turn 1) both live for the rest of the
REM conversation, which is the methodologically correct "image"
REM condition. "grounded"/"blind" are dropped because they are ablations
REM of eviction and have no faithful counterpart. Output goes to
REM *_noevict variant folders so it never mixes with the NIM-comparable
REM (evicting) runs from run_vqa_hf_local_all.bat of the same name.
REM See EXPERIMENT_SUMMARY.md ("Eviction and the `dual` variant").
REM
REM Shares one GPU/model, so it is NOT meant to be launched alongside
REM anything else that also wants the GPU - runs everything
REM sequentially.
REM
REM Usage, from anywhere:
REM     scripts\run_vqa_hf_local_noevict.bat [--model MODEL] [options]
REM
REM Requires: .venv already created at the repo root (with torch +
REM transformers installed - see scripts\setup_env.bat), target
REM dataset already downloaded to disk, pres_yes.png/pres_no.png
REM present at repo_root\prescriptions\ (only needed for the "image"
REM condition, but always resolved here).
REM ============================================================

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "SCRIPT_PY=%REPO_ROOT%\vqa_sycophancy_probe_hf_local_no_evict.py"
set "PROOF_YES=%REPO_ROOT%\prescriptions\pres_yes.png"
set "PROOF_NO=%REPO_ROOT%\prescriptions\pres_no.png"

REM --- 9 locally-runnable VLMs from LOCAL_VLM_CONVERSATIONAL_RANKING.md,
REM     ascending by est. VRAM. Excludes Llama-3.2-11B-Vision (keep on NIM)
REM     and NVLM-D-72B (too big for local). Used only when --model is not
REM     passed. Several of the 7-8B entries need --load-in-4bit on an 8GB
REM     card, and Molmo / InternVL3 need
REM     --trust-remote-code - pass those flags on the command line. ---
REM     Phi-3.5-vision dropped: its Hub modeling code (rope_type='su') is
REM     incompatible with transformers 5.x (installed: 5.15). Run it in a
REM     venv pinned to transformers==4.48.3 if ever needed.
set "MODEL_LIST=Qwen/Qwen2.5-VL-3B-Instruct google/medgemma-4b-it llava-hf/llava-1.5-7b-hf Qwen/Qwen2.5-VL-7B-Instruct Qwen/Qwen3-VL-8B-Instruct FreedomIntelligence/HuatuoGPT-Vision-7B openbmb/MiniCPM-V-4_6 allenai/Molmo-7B-D-0924 OpenGVLab/InternVL3-8B"

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

if not exist "%PYTHON%" (
    echo [error] venv python not found at "%PYTHON%"
    echo         Create it first: scripts\setup_env.bat
    exit /b 1
)
if not exist "%SCRIPT_PY%" (
    echo [error] vqa_sycophancy_probe_hf_local_no_evict.py not found at "%SCRIPT_PY%"
    exit /b 1
)

set "MODELS=%MODEL%"
if "%MODELS%"=="" set "MODELS=%MODEL_LIST%"

set "RUNNER_ARGS="
if not "%RUNNER%"=="" set "RUNNER_ARGS=--runner %RUNNER%"

set /a RUN_COUNT=0
set /a FAIL_COUNT=0

for %%M in (%MODELS%) do (
    echo.
    echo ################## MODEL: %%M ##################

    for %%E in (image none) do (
        set "NEEDS_PROOF=0"
        if "%%E"=="image" set "NEEDS_PROOF=1"

        for %%P in (default neighbor_nurse_doctor generic) do (
            set /a RUN_COUNT+=1
            if "!NEEDS_PROOF!"=="1" (
                echo === "%PYTHON%" "%SCRIPT_PY%" --model "%%M" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS! ===
                if "!DRY_RUN!"=="0" (
                    "%PYTHON%" "%SCRIPT_PY%" --model "%%M" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% --proof-yes-image "%PROOF_YES%" --proof-no-image "%PROOF_NO%" %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS!
                    if errorlevel 1 (
                        set /a FAIL_COUNT+=1
                        echo !!! FAILED: model=%%M evidence=%%E prompt-set=%%P !!!
                    )
                )
            ) else (
                echo === "%PYTHON%" "%SCRIPT_PY%" --model "%%M" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS! ===
                if "!DRY_RUN!"=="0" (
                    "%PYTHON%" "%SCRIPT_PY%" --model "%%M" --evidence %%E --n %N% --dataset-dir "%DATASET_DIR%" --split %SPLIT% --seed %SEED% --prompt-set %%P --pushback-turns %PUSHBACK_TURNS% --device %DEVICE% %TRUST_REMOTE_CODE% %LOAD_IN_4BIT% !RUNNER_ARGS!
                    if errorlevel 1 (
                        set /a FAIL_COUNT+=1
                        echo !!! FAILED: model=%%M evidence=%%E prompt-set=%%P !!!
                    )
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
echo Usage: %~nx0 [--model MODEL] [options]
echo.
echo   --model MODEL           HF Hub model id to load locally. If omitted, loops the 10
echo                           locally-runnable VLMs from LOCAL_VLM_CONVERSATIONAL_RANKING.md
echo   --n N                   questions per run (default: 20)
echo   --dataset-dir DIR       default: %REPO_ROOT%\data\vqa_rad_yesno
echo   --split train^|test      default: train
echo   --seed SEED             default: 42
echo   --pushback-turns 1-10   escalation depth (default: 10)
echo   --device auto^|cuda^|cpu default: auto
echo   --trust-remote-code     pass through to from_pretrained (needed for Molmo, InternVL3)
echo   --load-in-4bit          load via bitsandbytes NF4 quantization (needed for most 7-8B models on an 8GB card)
echo   --runner NAME           override auto-detected username@hostname
echo   --dry-run               print commands without running them
exit /b 1
