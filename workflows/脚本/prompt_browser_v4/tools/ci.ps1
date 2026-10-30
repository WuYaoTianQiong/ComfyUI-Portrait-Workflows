# 后端一键校验：契约测试 + 真实拉起服务的冒烟测试
#
# 用法（任意目录）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ci.ps1
#
# 两道关：
#   1) pytest  —— 108 条契约/行为用例，覆盖全部 GET 端点不 5xx、CRUD 语义、迁移与标签
#   2) verify_smoke.py —— 真起一个 uvicorn（临时库 + 临时端口），打关键接口并扫日志
# 静态 py_compile 发现不了"启动期崩溃""运行期 500"，所以第 2 步不能省。

$ErrorActionPreference = 'Stop'

$PY = 'C:\Users\ws\AppData\Local\Python\pythoncore-3.12-64\python.exe'
if (-not (Test-Path $PY)) { $PY = 'python' }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PB_NO_BROWSER = '1'
$env:PYTHONIOENCODING = 'utf-8'

Write-Host '=== 1/2 pytest ===' -ForegroundColor Cyan
& $PY -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host 'FAILED: pytest' -ForegroundColor Red
    exit 1
}

Write-Host '=== 2/2 verify_smoke ===' -ForegroundColor Cyan
& $PY verify_smoke.py
if ($LASTEXITCODE -ne 0) {
    Write-Host 'FAILED: verify_smoke' -ForegroundColor Red
    exit 1
}

Write-Host 'CI PASS' -ForegroundColor Green
exit 0
