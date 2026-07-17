@echo off
chcp 65001 >nul
title Prompt Browser v4 (FastAPI)
cd /d "%~dp0"

set "PYEXE=C:\Users\ws\AppData\Local\Python\pythoncore-3.12-64\python.exe"
if not exist "%PYEXE%" set "PYEXE=py"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_helper.ps1"

echo 正在启动 Prompt Browser v4 ...
"%PYEXE%" main.py
pause
