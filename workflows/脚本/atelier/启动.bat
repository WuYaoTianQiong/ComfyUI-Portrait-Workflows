@echo off
chcp 65001 >nul
title Atelier (FastAPI)
cd /d "%~dp0"

REM 18+ 内容总闸：1=允许前端开关切换，0=后端完全过滤（彻底关闭）
set "ATELIER_REFERENCE_ALLOW_NSFW=1"

set "PYEXE=C:\Users\ws\AppData\Local\Python\pythoncore-3.12-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=py"


powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_helper.ps1"

echo 正在启动 画室 Atelier ...
"%PYEXE%" main.py
pause
