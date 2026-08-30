@echo off
setlocal
REM Runs from anywhere: hop to repo root (parent of scripts\).
cd /d "%~dp0.."
REM Reads the PAT from pat.txt (gitignored) in repo root. No secret in this file.
if not exist "pat.txt" (
  echo Missing pat.txt in repo root. Put a fresh PAT in it, then rerun.
  exit /b 1
)
set /p PAT=<pat.txt
if "%PAT%"=="" (
  echo pat.txt is empty.
  exit /b 1
)
git config user.name "Sadif Ahmed"
git config user.email "ahmedsadif67@gmail.com"
(
  echo protocol=https
  echo host=github.com
  echo username=Sadif-Ahmed
  echo password=%PAT%
  echo.
) | git credential approve
if errorlevel 1 (
  echo git credential approve failed. Run "git push" once and paste the PAT when prompted.
  exit /b 1
)
echo Stored credential for Sadif-Ahmed. You can delete pat.txt now.
endlocal
