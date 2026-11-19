@echo off
setlocal
cd /d "%~dp0.."
set MPLCONFIGDIR=%CD%\tools\matplotlib
set TEMP=%CD%\tools\tmp
set TMP=%TEMP%
if not exist "tools\python\python.exe" (
  echo Run scripts\setup.ps1 first.
  exit /b 1
)
"tools\python\python.exe" ai_engine\main.py --mode local %*
exit /b %ERRORLEVEL%
