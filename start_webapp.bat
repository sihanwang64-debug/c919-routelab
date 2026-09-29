@echo off
rem c919-routelab web app launcher (Windows, double-click me)
rem Uses the project venv when present, otherwise falls back to system python.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)
%PY% run_server.py
pause
