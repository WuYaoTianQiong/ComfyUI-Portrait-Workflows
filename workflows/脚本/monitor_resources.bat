@echo off
echo 监控 ComfyUI 资源占用...
echo.

:loop
cls
echo ========== %time% ==========
echo.
echo [GPU 显存占用]
nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader
echo.
echo [CPU 和内存占用]
wmic cpu get loadpercentage
wmic computersystem get TotalPhysicalMemory
tasklist | findstr "python.exe"
echo.
timeout /t 2 > nul
goto loop
