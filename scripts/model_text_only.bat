@echo off
REM ============================================================
REM model_text_only.bat
REM
REM Runs the TEXT-ONLY sycophancy probe - sycophancy_probe.py, no
REM images - across a list of models/datasets defined below, one
REM after another. Does NOT touch vqa_sycophancy_probe.py.
REM
REM Usage, from anywhere:
REM     scripts\model_text_only.bat
REM
REM Requires: .venv already created at the repo root - see README.md -
REM and the target dataset(s) already downloaded to disk.
REM
REM Output layout, per dataset, handled by sycophancy_probe.py itself:
REM   transcripts\<dataset-folder-name>\<model_tag>__NNN.json  - one file per question,
REM     NNN auto-increments per model so re-runs never overwrite earlier transcripts
REM   transcripts\<dataset-folder-name>\RESULTS.txt            - appended after every
REM     run: timestamp, model, aggregate stats, one line per question with its
REM     flip turn - the instant human-readable viewer, no need to open the JSON files
REM ============================================================

setlocal enabledelayedexpansion

REM --- resolve repo root - this file lives in repo\scripts\ ---
set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "PROBE=%REPO_ROOT%\sycophancy_probe.py"

if not exist "%PYTHON%" (
    echo [error] venv python not found at "%PYTHON%"
    echo         Create it first: python -m venv .venv, then pip install openai httpx tenacity datasets
    exit /b 1
)
if not exist "%PROBE%" (
    echo [error] sycophancy_probe.py not found at "%PROBE%"
    exit /b 1
)

REM --- shared run settings, apply to every entry unless overridden per-entry below ---
set "N=5"
set "SEED=42"
set "TEMPERATURE=0.2"
set "DEFAULT_MAX_TOKENS=512"
set "REASONING_MAX_TOKENS=1536"
set "RPM_OVERRIDE="

REM ============================================================
REM MODEL LIST - add a new run by adding the next index, N+1:
REM
REM   set "MODEL[N]=provider-id/model-name"
REM   set "PROVIDER[N]=nvidia"        - or openrouter
REM   set "DATASET_DIR[N]=-"          - dash means use sycophancy_probe.py's own default: data\medmcqa
REM   set "SPLIT[N]=-"                - dash means use sycophancy_probe.py's own default: train
REM
REM --max-tokens is chosen automatically per entry: any model name
REM containing "reasoning" gets REASONING_MAX_TOKENS, everything
REM else gets DEFAULT_MAX_TOKENS. Override by editing that check
REM in the run_one subroutine if a specific model needs a custom value.
REM ============================================================

set "MODEL[0]=qwen/qwen3-next-80b-a3b-instruct"
set "PROVIDER[0]=nvidia"
set "DATASET_DIR[0]=-"
set "SPLIT[0]=-"

set "MODEL[1]=openai/gpt-oss-120b"
set "PROVIDER[1]=nvidia"
set "DATASET_DIR[1]=-"
set "SPLIT[1]=-"

set "MODEL[2]=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
set "PROVIDER[2]=nvidia"
set "DATASET_DIR[2]=-"
set "SPLIT[2]=-"

REM --- template for a future second dataset, uncomment and edit when one exists ---
REM set "MODEL[3]=some/model-name"
REM set "PROVIDER[3]=nvidia"
REM set "DATASET_DIR[3]=data\some_other_dataset"
REM set "SPLIT[3]=train"

REM ============================================================
REM Loop - no need to track a count, stops at the first missing index.
REM ============================================================

set /a IDX=0
:loop_models
if not defined MODEL[%IDX%] goto :after_loop
call :run_one %IDX%
set /a IDX+=1
goto :loop_models
:after_loop

echo.
echo All runs complete. Results land in %REPO_ROOT%\results\^<dataset^>, transcripts in %REPO_ROOT%\transcripts\^<dataset^>
exit /b 0

REM ============================================================
:run_one
setlocal enabledelayedexpansion
set "I=%~1"
set "MODEL=!MODEL[%I%]!"
set "PROVIDER=!PROVIDER[%I%]!"
set "DS=!DATASET_DIR[%I%]!"
set "SPLIT=!SPLIT[%I%]!"

set "MAXTOK=%DEFAULT_MAX_TOKENS%"
echo !MODEL! | findstr /i "reasoning" >nul && set "MAXTOK=%REASONING_MAX_TOKENS%"

set "EXTRA_ARGS="
if not "!DS!"=="-" set "EXTRA_ARGS=!EXTRA_ARGS! --dataset-dir "!DS!""
if not "!SPLIT!"=="-" set "EXTRA_ARGS=!EXTRA_ARGS! --split !SPLIT!"
if not "%RPM_OVERRIDE%"=="" set "EXTRA_ARGS=!EXTRA_ARGS! --rpm %RPM_OVERRIDE%"

echo.
echo ============================================================
echo [%I%] provider=!PROVIDER!  model=!MODEL!  max-tokens=!MAXTOK!
echo ============================================================

"%PYTHON%" "%PROBE%" --provider !PROVIDER! --model "!MODEL!" --n %N% --seed %SEED% --temperature %TEMPERATURE% --max-tokens !MAXTOK! !EXTRA_ARGS!

endlocal
goto :eof
