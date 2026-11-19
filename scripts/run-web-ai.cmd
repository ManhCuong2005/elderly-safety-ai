@echo off
setlocal
cd /d "%~dp0.."
set MPLCONFIGDIR=%CD%\tools\matplotlib
set TEMP=%CD%\tools\tmp
set TMP=%TEMP%
"tools\python\python.exe" ai_engine\web_server.py %*
exit /b %ERRORLEVEL%
