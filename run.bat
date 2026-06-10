@echo off
title DeepSeek Balance Tray
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo [ERROR] venv not found.
    pause
    exit /b 1
)

start "" "venv\Scripts\pythonw.exe" "%~dp0main.py" >nul 2>&1
exit 0
