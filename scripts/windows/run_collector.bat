@echo off
rem Runs the CAMMESA collector from the repo root. Usage: run_collector.bat <mode> [options]
cd /d "%~dp0..\.."
py -3 scripts\collect_cammesa.py %*
exit /b %ERRORLEVEL%
