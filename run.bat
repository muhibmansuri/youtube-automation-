@echo off
title CodeAura Cinema Studio - Autonomous AI Movie Generator
echo =====================================================================
echo           CodeAura Cinema Studio - Continuous Movie Automation
echo =====================================================================
echo.
echo [1/3] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not found in PATH! Please install Python 3.10+.
    pause
    exit /b 1
)

echo [2/3] Checking Playwright Chromium...
python -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    playwright install chromium
)

echo [3/3] Launching CinemaStudio Web Application...
echo Local Web Dashboard: http://127.0.0.1:5000
echo.
start http://127.0.0.1:5000
python app.py
pause
