@echo off
chcp 65001 >nul
title DeepSeek 余额查询
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo [错误] 未找到虚拟环境
    echo 请先执行: uv venv venv ^&^& uv pip install pystray Pillow requests
    pause
    exit /b 1
)

:: 后台静默启动（无命令行窗口）
start /b "" "venv\Scripts\pythonw.exe" "%~dp0main.py" >nul 2>&1

:: 等待一会检查是否启动成功
timeout /t 3 /nobreak >nul

:: 检查托盘图标是否运行
tasklist /FI "WINDOWTITLE eq DeepSeek*" 2>nul | findstr /i "pythonw" >nul
if errorlevel 1 (
    echo [信息] 启动后台进程，请查看任务栏托盘区域
    echo [信息] 右键图标可查看详情和设置
    timeout /t 5 /nobreak >nul
)
