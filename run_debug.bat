@echo off
echo DeepSeek Balance Tray - Debug Mode
echo Console stays open to show errors
echo.
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found
    pause
    exit /b 1
)
echo [INFO] Starting...
"venv\Scripts\python.exe" "%~dp0main.py"
echo.
if errorlevel 1 (
    echo [ERROR] Exit code: %errorlevel%
) else (
    echo [INFO] Exited.
)
pause
