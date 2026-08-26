@echo off
REM ============================================================
REM setup_env.bat
REM
REM One-shot environment setup for a fresh copy of this repo on a
REM new device. Creates .venv and installs EVERYTHING the repo
REM might need in one go: torch + torchvision (auto-picks CUDA or
REM CPU build depending on whether an NVIDIA GPU is detected) plus
REM every package listed in requirements.txt (API pipeline, local
REM inference, and legacy/reference scripts alike). torchvision is
REM needed even for image-only work - some model processors (e.g.
REM Qwen2.5-VL's) import it unconditionally for their video-input path.
REM
REM Usage, from anywhere:
REM     scripts\setup_env.bat
REM
REM Requires: Python 3.10+ available as "python" on PATH.
REM ============================================================

setlocal enabledelayedexpansion

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "VENV_DIR=%REPO_ROOT%\.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage

where python >nul 2>&1
if errorlevel 1 (
    echo [error] "python" not found on PATH. Install Python 3.10+ first.
    exit /b 1
)

if not exist "%PYTHON%" (
    echo [setup] Creating virtual environment at "%VENV_DIR%" ...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        REM Some machines only have a stripped-down/"embeddable" Python
        REM install with no venv module and no pip at all (not a broken
        REM install - it's built that way on purpose). Bootstrap pip, then
        REM fall back to the third-party virtualenv package, which doesn't
        REM depend on the stdlib venv module.
        echo [setup] stdlib venv unavailable - bootstrapping pip + virtualenv instead ...
        python -m ensurepip --upgrade >nul 2>&1
        if errorlevel 1 (
            echo [setup] ensurepip unavailable, downloading get-pip.py ...
            powershell -NoProfile -Command "Invoke-WebRequest -Uri https://bootstrap.pypa.io/get-pip.py -OutFile '%TEMP%\get-pip.py'"
            python "%TEMP%\get-pip.py"
        )
        python -m pip install virtualenv
        python -m virtualenv "%VENV_DIR%"
        if errorlevel 1 (
            echo [error] venv creation failed even with the virtualenv fallback.
            exit /b 1
        )
    )
) else (
    echo [setup] Reusing existing venv at "%VENV_DIR%"
)

echo [setup] Upgrading pip ...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

echo [setup] Checking for an NVIDIA GPU ...
where nvidia-smi >nul 2>&1
if errorlevel 1 goto :torch_cpu_only

REM Plain "pip install torch" does NOT reliably give a CUDA build on
REM Windows - PyPI's default index can silently resolve to CPU-only.
REM The CUDA build requires pip pointed explicitly at PyTorch's own
REM wheel index (see https://pytorch.org/get-started/locally/).
REM
REM cu126 tried FIRST, not cu128/newer: starting with PyTorch 2.11,
REM the cu128/cu129 wheel builds dropped Volta (compute capability
REM 7.0 - e.g. Tesla V100) support entirely, to allow a cuDNN bump
REM incompatible with Volta. torch.cuda.is_available() still reports
REM True on an unsupported-arch build - it just fails the moment a
REM kernel actually runs - so this silently "worked" before while
REM being broken. cu126 still includes Volta and every GPU newer
REM than it (a newer driver runs an older-CUDA-tagged wheel fine),
REM so it's the safer default across all the machines this repo runs
REM on (V100 and RTX-class alike), not just a Volta-specific fix.
REM
REM pip's "already satisfied" check only looks at the version number, not
REM the build variant - a bare "pip install torch" (no index-url) run at
REM any earlier point in this venv's history, or a plain requirements.txt
REM install pulling in accelerate's own minimum-torch dependency, leaves a
REM CPU wheel in place that every later CUDA-indexed install below would
REM otherwise silently no-op on, even though torchvision ends up correctly
REM CUDA-tagged alongside it - a mismatched pair that still imports fine but
REM reports cuda.is_available as False. Check first so a venv that is already
REM correctly CUDA-enabled does not pay for a multi-gigabyte reinstall on
REM every rerun; only force a real reinstall when actually needed.
echo [setup] nvidia-smi found - checking for a working CUDA torch install ...
set "TORCH_CUDA_OK=0"
"%PYTHON%" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" >nul 2>&1
if not errorlevel 1 set "TORCH_CUDA_OK=1"
if not "%TORCH_CUDA_OK%"=="1" goto :torch_cuda_install
echo [setup] torch already has a working CUDA build - skipping reinstall.
goto :after_torch_install

:torch_cuda_install
echo [setup] Installing/repairing CUDA-enabled torch + torchvision (forced) ...
"%PYTHON%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu126
if not errorlevel 1 goto :after_torch_install
echo [setup] cu126 index failed, trying cu128 ...
"%PYTHON%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
if not errorlevel 1 goto :after_torch_install
echo [setup] cu128 index failed, trying cu121 ...
"%PYTHON%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu121
if not errorlevel 1 goto :after_torch_install
echo [warning] Could not install a CUDA build of torch - falling back to CPU-only.
echo           Check https://pytorch.org/get-started/locally/ for the current CUDA index for your driver.
"%PYTHON%" -m pip install --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cpu
goto :after_torch_install

:torch_cpu_only
echo [setup] No nvidia-smi on PATH - installing CPU-only torch + torchvision ...
"%PYTHON%" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

:after_torch_install
if errorlevel 1 exit /b 1

echo [setup] Installing everything else from requirements.txt ...
"%PYTHON%" -m pip install -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 exit /b 1

echo [setup] Verifying torch sees the GPU AND can actually run a kernel on it ...
REM torch.cuda.is_available() alone is NOT enough - it returns True even on a
REM build that was compiled without kernels for this GPU's compute capability
REM (see the cu126-vs-cu128 note above), and only fails once a real op runs.
"%PYTHON%" -c "import torch; print('torch.cuda.is_available() =', torch.cuda.is_available()); x = torch.randn(4, 4, device='cuda') if torch.cuda.is_available() else None; y = (x @ x) if x is not None else None; torch.cuda.synchronize() if x is not None else None; print('GPU kernel test:', 'OK on ' + torch.cuda.get_device_name(0) if x is not None else 'skipped (no GPU)')"

echo.
echo === Environment ready at "%VENV_DIR%" ===
echo.
echo Reminder - these are gitignored and will NOT have come across on
echo a fresh git clone (only relevant if that's how you moved the code):
echo   - api_key.txt      (NVIDIA NIM / OpenRouter key, one per line)
echo   - hf_token.txt     (Hugging Face token)
echo   - data\            (downloaded datasets)
exit /b 0

:usage
echo Usage: %~nx0
echo.
echo Creates .venv and installs torch (GPU or CPU build, auto-detected)
echo plus every package in requirements.txt - covers the API pipeline,
echo local inference, and legacy scripts in one pass.
exit /b 1
