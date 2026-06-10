@echo off
title DeepSeek Balance Tray - Debug
cd /d "%~dp0"

echo ========================================
echo  DeepSeek Balance Tray - DEBUG MODE
echo  Console stays open to show log output
echo ========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found. Run: uv venv venv
    pause
    exit /b 1
)

echo [INFO] venv OK
echo [INFO] Starting...
echo.

"venv\Scripts\python.exe" "%~dp0main.py"

echo.
if errorlevel 1 (
    echo [ERROR] Exit code: %errorlevel%
) else (
    echo [INFO] Program exited.
)
pause
