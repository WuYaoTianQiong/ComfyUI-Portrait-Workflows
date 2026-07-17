# 释放端口上的旧进程（精确查杀监听套接字拥有者，跳过系统进程）
# 端口取自 config.py 的 port 设置，作为唯一数据源，避免多处硬编码
$configPath = Join-Path $PSScriptRoot "config.py"
$port = 8656
if (Test-Path $configPath) {
    $txt = Get-Content $configPath -Raw
    if ($txt -match 'port\s*:\s*int\s*=\s*(\d+)') {
        $port = [int]$Matches[1]
    }
}

Write-Host "正在释放端口 $port 上的旧进程..."
$ids = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
foreach ($id in $ids) {
    if ($id -le 4) {
        Write-Host "  跳过系统进程 PID=$id"
    } else {
        Write-Host "  结束进程 PID=$id"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2

if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "  警告：端口 $port 仍被占用，启动可能失败"
}
