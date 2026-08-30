@echo off
REM Wipe any cached GitHub credential (e.g. a stale account) from Windows.
cmdkey /delete:LegacyGeneric:target=git:https://github.com >nul 2>&1
(echo protocol=https& echo host=github.com& echo.) | git credential reject 2>nul
echo Cleared cached GitHub credential.
