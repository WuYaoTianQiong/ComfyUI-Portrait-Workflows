# 一键校验：后端契约 + 冒烟 + 前端类型/单测/构建 + 前端 E2E
#
# 用法（任意目录）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ci.ps1
#
# 六道关，缺一不可：
#   1) pytest            —— 后端契约/行为用例（迁移、标签、CRUD、upsert 语义）
#   2) 硬编码颜色守护    —— frontend/src/**/*.vue 的十六进制色值数不得超过基线 55
#   3) vue-tsc --noEmit  —— 前端类型检查（TS strict 只在编辑器里生效过，命令行没人跑）
#   4) vitest            —— 前端单测/组件测试
#   5) vite build        —— 构建产物（构建失败 = 部署不了）
#   6) tools/smoke.py    —— 真起一个 uvicorn（库副本 + 临时端口），打关键接口并扫日志
# 附加：run_e2e.py      —— 前端端到端：库副本 + 临时服务 + Playwright 跑五个页签
#
# 为什么不能只留第 1 道：静态检查发现不了"启动期崩溃""运行期 500""页面整体白屏"。
# 为什么不能只留第 4 道：组件测试测不到静态资源 404、接口路径拼错、路由挂载顺序。
#
# 硬编码颜色基线（55）来自《atelier_UI卖相提升计划_20261104》§1 的实测：
#   Get-ChildItem -Path frontend\src -Recurse -Filter *.vue |
#       Select-String -Pattern '#[0-9a-fA-F]{3,8}\b' -AllMatches
# 新增色值应改走 styles/tokens.css；确需写死时同步收紧基线，并在本注释记录原因。
#
# E2E 需要 Playwright 与 Chromium；缺失时会自动 SKIP（不算失败），不阻断其它关卡。

$ErrorActionPreference = 'Stop'

$PY = 'C:\Users\ws\AppData\Local\Python\pythoncore-3.12-64\python.exe'
if (-not (Test-Path $PY)) { $PY = 'python' }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:ATELIER_NO_BROWSER = '1'
$env:PYTHONIOENCODING = 'utf-8'

function Step($index, $total, $title) {
    Write-Host "=== $index/$total $title ===" -ForegroundColor Cyan
}

Step '1' '6' 'pytest'
& $PY -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host 'FAILED: pytest' -ForegroundColor Red
    exit 1
}

Step '2' '6' '硬编码颜色守护'
$colorBaseline = 55
$vueRoot = Join-Path $root 'frontend\src'
$hardcodedColors = 0
if (Test-Path $vueRoot) {
    foreach ($file in (Get-ChildItem -Path $vueRoot -Recurse -Filter *.vue -File)) {
        $text = Get-Content -LiteralPath $file.FullName -Raw
        if ($null -ne $text) {
            $hardcodedColors += [regex]::Matches($text, '#[0-9a-fA-F]{3,8}\b').Count
        }
    }
}
if ($hardcodedColors -gt $colorBaseline) {
    Write-Host "FAILED: frontend/src/**/*.vue 硬编码颜色 $hardcodedColors 处，超过基线 $colorBaseline" -ForegroundColor Red
    exit 1
}
Write-Host "硬编码颜色 $hardcodedColors 处（基线 $colorBaseline）" -ForegroundColor Gray

$frontend = Join-Path $root 'frontend'
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host '前端依赖未安装，跳过前端三道关（frontend/node_modules 缺失）' -ForegroundColor Yellow
} else {
    Push-Location $frontend

    Step '3' '6' 'vue-tsc --noEmit'
    & npx vue-tsc --noEmit
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: vue-tsc' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Step '4' '6' 'vitest'
    & npx vitest run --reporter=basic
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: vitest' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Step '5' '6' 'vite build'
    & npx vite build
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: vite build' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Pop-Location

    Step '6' '6' 'smoke'
    & $PY tools\smoke.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: smoke' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Write-Host '=== 附加：前端 E2E（Playwright）===' -ForegroundColor Cyan
    & $PY tests\e2e\run_e2e.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: e2e' -ForegroundColor Red
        exit 1
    }
}

Write-Host 'CI PASS' -ForegroundColor Green
exit 0