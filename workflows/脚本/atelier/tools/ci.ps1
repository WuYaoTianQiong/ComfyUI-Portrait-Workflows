# 一键校验：后端契约 + 冒烟 + 前端类型/单测/构建 + 前端 E2E
#
# 用法（任意目录）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\ci.ps1
#
# 七道关，缺一不可：
#   1) pytest            —— 后端契约/行为用例（迁移、标签、CRUD、upsert 语义）
#   2) 硬编码颜色守护    —— frontend/src/**/*.vue 的 <style> 块里十六进制色值必须为 0
#   3) 契约类型同步      —— 重新生成 openapi.json/openapi.d.ts，工作区必须无差异
#   4) vue-tsc --noEmit  —— 前端类型检查（TS strict 只在编辑器里生效过，命令行没人跑）
#   5) vitest            —— 前端单测/组件测试
#   6) vite build        —— 构建产物（构建失败 = 部署不了）
#   7) tools/smoke.py    —— 真起一个 uvicorn（库副本 + 临时端口），打关键接口并扫日志
# 附加：run_e2e.py      —— 前端端到端：库副本 + 临时服务 + Playwright 跑五个页签
#
# 为什么不能只留第 1 道：静态检查发现不了"启动期崩溃""运行期 500""页面整体白屏"。
# 为什么不能只留第 4 道：组件测试测不到静态资源 404、接口路径拼错、路由挂载顺序。
#
# 硬编码颜色基线（0）来自《atelier_UI卖相提升计划_20261104》§2 P0 的验收目标：
# 色值一律走 styles/tokens.css，页面只写 var(--token)。
#
# 口径说明（2026-11-04 验收后收紧）：
#   只统计 <style> 块。`<script>` 里的色值可能是写入数据库的「数据」
#   （如 TaxonomyView 的分类配色板），不属于样式硬编码，按样式口径统计才不误伤。
#   已下线的只有 React 子应用 gallery-web/（2026-11-05 阶段 4.3 删除）；ReferenceView.vue / Lightbox.vue / frontend/src/api/reference.ts 仍在用，正常计入本守护。
# 新增色值应改走 styles/tokens.css，不要在这里放水提高基线。
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

Step '1' '7' 'pytest'
& $PY -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host 'FAILED: pytest' -ForegroundColor Red
    exit 1
}

Step '2' '7' '硬编码颜色守护'
$colorBaseline = 0
$vueRoot = Join-Path $root 'frontend\src'
$hardcodedColors = 0
$offenders = @()
if (Test-Path $vueRoot) {
    foreach ($file in (Get-ChildItem -Path $vueRoot -Recurse -Filter *.vue -File)) {
        $text = Get-Content -LiteralPath $file.FullName -Raw
        if ($null -eq $text) { continue }
        # 只看 <style> 块：<script> 里的色值可能是写库的数据色板
        $count = 0
        foreach ($block in [regex]::Matches($text, '(?s)<style[^>]*>(.*?)</style>')) {
            $count += [regex]::Matches($block.Groups[1].Value, '#[0-9a-fA-F]{3,8}\b').Count
        }
        if ($count -eq 0) { continue }
        $hardcodedColors += $count
        $offenders += "$($file.Name)($count)"
    }
}
if ($hardcodedColors -gt $colorBaseline) {
    Write-Host "FAILED: .vue 的 <style> 里还有 $hardcodedColors 处硬编码颜色（基线 $colorBaseline）：$($offenders -join ', ')" -ForegroundColor Red
    Write-Host '  改法：在 styles/tokens.css 加令牌，页面写 var(--token)' -ForegroundColor Yellow
    exit 1
}
Write-Host "硬编码颜色 $hardcodedColors 处（基线 $colorBaseline）" -ForegroundColor Gray

$frontend = Join-Path $root 'frontend'
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host '前端依赖未安装，跳过前端三道关（frontend/node_modules 缺失）' -ForegroundColor Yellow
} else {
    Push-Location $frontend

    # IDE（CodeBuddy/VS Code 扩展）会往 NODE_OPTIONS 注入 node-language-shim.cjs：
    # - vue-tsc 在它下面会 "Zone Allocation failed - process out of memory"（内存被 shim 拖爆）；
    # - vite build 的 emptyOutDir 会报 trash operation failed。
    # 前端三道关都不需要这个 shim，统一在这里清掉。
    $env:NODE_OPTIONS = ''

    Step '3' '7' '契约类型同步'
    # openapi.json 已有 pytest 快照兜底；这里把生成物 openapi.d.ts 也纳入：
    # 只改 schemas/路由、忘记重新生成时，CI 直接红，而不是等用户点到 undefined。
    # 用生成前后的哈希比较，而不是 git diff —— 本地未提交时也能正确判断"是否已同步"。
    $snapshotFiles = @(
        (Join-Path $root 'frontend\openapi.json'),
        (Join-Path $root 'frontend\src\api\openapi.d.ts')
    )
    $beforeHashes = @{}
    foreach ($f in $snapshotFiles) {
        $beforeHashes[$f] = if (Test-Path -LiteralPath $f) {
            (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash
        } else { '' }
    }
    & $PY (Join-Path $root 'tools\gen_api_types.py')
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: 生成 OpenAPI 类型' -ForegroundColor Red
        Pop-Location
        exit 1
    }
    $drifted = @()
    foreach ($f in $snapshotFiles) {
        $after = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash
        if ($after -ne $beforeHashes[$f]) { $drifted += (Split-Path -Leaf $f) }
    }
    if ($drifted.Count -gt 0) {
        Write-Host "FAILED: 契约类型未同步（生成后发生变化：$($drifted -join ', ')）" -ForegroundColor Red
        Write-Host '  改法：运行 python tools/gen_api_types.py 并提交生成物' -ForegroundColor Yellow
        Pop-Location
        exit 1
    }

    Step '4' '7' 'vue-tsc --noEmit'
    & npx vue-tsc --noEmit
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: vue-tsc' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Step '5' '7' 'vitest'
    & npx vitest run --reporter=basic
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: vitest' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Step '6' '7' 'vite build'
    # 1) 清 NODE_OPTIONS：IDE 注入的 safe-delete shim 会让 vite 的 emptyOutDir 报
    #    "trash operation failed" 而构建失败（等价于"代码没问题但 CI 红了"）。
    $env:NODE_OPTIONS = ''
    # 2) 显式清空 web/：本机实测 emptyOutDir 不生效，旧产物会一直堆积
    #    （2026-11-04 验收时堆到 13 份 index-*.js / 52MB）。用 .NET 删，比 Remove-Item 稳。
    $webDir = Join-Path $root 'web'
    if (Test-Path $webDir) {
        try {
            [System.IO.Directory]::Delete($webDir, $true)
        } catch {
            Write-Host "WARN: 清空 web/ 失败（$($_.Exception.Message)），继续构建" -ForegroundColor Yellow
        }
    }
    & npx vite build
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'FAILED: vite build' -ForegroundColor Red
        Pop-Location
        exit 1
    }

    Pop-Location

    Step '7' '7' 'smoke'
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