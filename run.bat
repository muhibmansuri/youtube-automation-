@echo off
title CodeAura Cinema Studio - Autonomous AI Movie Generator
echo =====================================================================
echo           CodeAura Cinema Studio - Continuous Movie Automation
echo =====================================================================
echo.
echo [1/3] Checking Python Virtual Environment...
set "PY_EXE=python"
if exist "C:\cinema_venv\Scripts\python.exe" (
    set "PY_EXE=C:\cinema_venv\Scripts\python.exe"
    echo Using isolated environment: C:\cinema_venv
)
%PY_EXE% --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not found in PATH! Please install Python 3.10+.
    pause
    exit /b 1
)

echo [2/3] Checking Playwright Chromium...
%PY_EXE% -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    %PY_EXE% -m pip install -r requirements.txt
    %PY_EXE% -m playwright install chromium
)

echo [3/3] Launching CinemaStudio Web Application...
echo Local Web Dashboard: http://127.0.0.1:5000
echo.
start http://127.0.0.1:5000
%PY_EXE% app.py
pause
