@echo off
REM DeepSeek 余额查询小工具 - 启动脚本
cd /d "%~dp0"
call venv\Scripts\activate.bat
python main.py
pause
