@echo off
chcp 65001 >nul
title Atelier (FastAPI)
cd /d "%~dp0"

REM 18+ 内容总闸：1=允许前端开关切换，0=后端完全过滤（彻底关闭）
set "ATELIER_REFERENCE_ALLOW_NSFW=1"

set "PYEXE=C:\Users\ws\AppData\Local\Python\pythoncore-3.12-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=py"

REM ---- 参考图库 Web（上游 React 台，独立静态服务 :8760）----
REM 已监听则不重复拉起；日志落点：workflows\脚本\参考图库Web\logs\serve.log
set "REFWEB_DIR=%~dp0..\参考图库Web"
set "REFWEB_LOG=%REFWEB_DIR%\logs\serve.log"
netstat -ano -p tcp | findstr /C:"127.0.0.1:8760" | findstr /C:"LISTENING" >nul 2>&1
if errorlevel 1 (
    if not exist "%REFWEB_DIR%\logs" mkdir "%REFWEB_DIR%\logs"
    echo 正在启动 参考图库 Web :8760 ...
    start "" /b "%PYEXE%" "%REFWEB_DIR%\serve.py" --port 8760 >> "%REFWEB_LOG%" 2>&1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_helper.ps1"

echo 正在启动 画室 Atelier ...
"%PYEXE%" main.py
pause
