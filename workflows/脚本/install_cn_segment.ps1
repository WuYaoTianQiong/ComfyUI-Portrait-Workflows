# ComfyUI 中文语义分割扩展安装脚本
# 安装 comfyui_segment_anything (GroundingDINO + SAM)
# 支持中文文本提示做图像分割，替代 CLIPSeg

$ErrorActionPreference = "Stop"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  安装 comfyui_segment_anything" -ForegroundColor Cyan
Write-Host "  (支持中文语义分割的 GroundingDINO + SAM)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$WORKFLOWS_DIR = Split-Path -Parent $SCRIPT_DIR
$COMFYUI_DIR = Split-Path -Parent $WORKFLOWS_DIR
$CUSTOM_NODES_DIR = Join-Path $COMFYUI_DIR "ComfyUI\custom_nodes"
$MODELS_DIR = Join-Path $COMFYUI_DIR "ComfyUI\models"
$REPO_URL = "https://github.com/storyicon/comfyui_segment_anything.git"
$CLONE_DIR = Join-Path $CUSTOM_NODES_DIR "comfyui_segment_anything"

# ============================================
# 步骤 1：克隆扩展
# ============================================
Write-Host "[1/4] 安装 comfyui_segment_anything 扩展..." -ForegroundColor Yellow

if (Test-Path $CLONE_DIR) {
    Write-Host "  扩展目录已存在，跳过 git clone。如需重新安装请手动删除：" -ForegroundColor Green
    Write-Host "  $CLONE_DIR" -ForegroundColor Gray
} else {
    Write-Host "  git clone $REPO_URL" -ForegroundColor Gray
    git clone $REPO_URL $CLONE_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] git clone 失败，请检查网络或手动安装。" -ForegroundColor Red
        Write-Host "手动安装命令：cd $CUSTOM_NODES_DIR; git clone $REPO_URL" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  扩展安装成功！" -ForegroundColor Green
}

# ============================================
# 步骤 2：安装 Python 依赖
# ============================================
Write-Host "[2/4] 安装 Python 依赖..." -ForegroundColor Yellow
$REQUIREMENTS = Join-Path $CLONE_DIR "requirements.txt"
if (Test-Path $REQUIREMENTS) {
    $PYTHON_DIR = Join-Path $COMFYUI_DIR "python"
    $PIP = Join-Path $PYTHON_DIR "python.exe"
    $PIP_ARGS = "-m pip install -r `"$REQUIREMENTS`""
    Write-Host "  $PIP $PIP_ARGS" -ForegroundColor Gray
    if (Test-Path $PIP) {
        & $PIP -m pip install -r $REQUIREMENTS
    } else {
        pip install -r $REQUIREMENTS
    }
    Write-Host "  依赖安装完成！" -ForegroundColor Green
} else {
    Write-Host "  requirements.txt 不存在，跳过依赖安装。" -ForegroundColor Yellow
}

# ============================================
# 步骤 3：下载模型
# ============================================
Write-Host "[3/4] 下载模型..." -ForegroundColor Yellow

# --- SAM 模型 (375MB) ---
$SAMS_DIR = Join-Path $MODELS_DIR "sams"
$SAM_FILE = Join-Path $SAMS_DIR "sam_vit_b_01ec64.pth"
if (Test-Path $SAM_FILE) {
    Write-Host "  SAM 模型已存在，跳过下载。" -ForegroundColor Green
} else {
    New-Item -ItemType Directory -Force -Path $SAMS_DIR | Out-Null
    Write-Host "  下载 SAM vit_b 模型 (375MB)..." -ForegroundColor Gray
    Write-Host "  来源: https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth" -ForegroundColor Gray
    try {
        Invoke-WebRequest -Uri "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth" `
            -OutFile $SAM_FILE -UseBasicParsing
        Write-Host "  SAM 模型下载完成！" -ForegroundColor Green
    } catch {
        Write-Host "[警告] SAM 模型下载失败，请手动下载：" -ForegroundColor Yellow
        Write-Host "  URL: https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth" -ForegroundColor Gray
        Write-Host "  存放: $SAMS_DIR" -ForegroundColor Gray
    }
}

# --- GroundingDINO 模型 (694MB config+model) ---
$GDINO_DIR = Join-Path $MODELS_DIR "grounding-dino"
$GDINO_MODEL = Join-Path $GDINO_DIR "groundingdino_swint_ogc.pth"
$GDINO_CFG = Join-Path $GDINO_DIR "GroundingDINO_SwinT_OGC.cfg.py"

if ((Test-Path $GDINO_MODEL) -and (Test-Path $GDINO_CFG)) {
    Write-Host "  GroundingDINO 模型已存在，跳过下载。" -ForegroundColor Green
} else {
    New-Item -ItemType Directory -Force -Path $GDINO_DIR | Out-Null
    Write-Host "  下载 GroundingDINO SwinT_OGC (694MB)..." -ForegroundColor Gray
    Write-Host "  来源: huggingface.co/ShilongLiu/GroundingDINO" -ForegroundColor Gray

    # 下载配置文件
    try {
        Invoke-WebRequest -Uri "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/GroundingDINO_SwinT_OGC.cfg.py" `
            -OutFile $GDINO_CFG -UseBasicParsing
        Write-Host "  配置文件下载完成。" -ForegroundColor Green
    } catch {
        Write-Host "[警告] 配置文件下载失败。" -ForegroundColor Yellow
    }

    # 下载模型文件
    try {
        Invoke-WebRequest -Uri "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swint_ogc.pth" `
            -OutFile $GDINO_MODEL -UseBasicParsing
        Write-Host "  GroundingDINO 模型下载完成！" -ForegroundColor Green
    } catch {
        Write-Host "[警告] GroundingDINO 模型下载失败，请手动下载：" -ForegroundColor Yellow
        Write-Host "  模型: https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swint_ogc.pth" -ForegroundColor Gray
        Write-Host "  配置: https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/GroundingDINO_SwinT_OGC.cfg.py" -ForegroundColor Gray
        Write-Host "  存放: $GDINO_DIR" -ForegroundColor Gray
    }
}

# --- bert-base-uncased (如不存在则提示) ---
Write-Host "[4/4] 检查 bert-base-uncased..." -ForegroundColor Yellow
$BERT_DIR = Join-Path $MODELS_DIR "bert-base-uncased"
if (Test-Path $BERT_DIR) {
    Write-Host "  bert-base-uncased 已存在，跳过下载。" -ForegroundColor Green
} else {
    Write-Host "  bert-base-uncased 未找到，ComfyUI 首次推理时会自动下载。" -ForegroundColor Yellow
    Write-Host "  如遇网络问题，可手动下载：" -ForegroundColor Gray
    Write-Host "  huggingface-cli download bert-base-uncased --local-dir $BERT_DIR" -ForegroundColor Gray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  已安装的节点:" -ForegroundColor Yellow
Write-Host "    - SAMModelLoader           (加载 SAM 分割模型)" -ForegroundColor Gray
Write-Host "    - GroundingDinoModelLoader (加载 GroundingDINO 检测模型)" -ForegroundColor Gray
Write-Host "    - GroundingDinoSAMSegment  (用文本提示做分割，支持中文)" -ForegroundColor Gray
Write-Host ""
Write-Host "  使用方式：重新启动 ComfyUI 后加载工作流即可。" -ForegroundColor Yellow
Write-Host "  提示词示例：'短裤'、'长发'、'红色的裙子'、'person wearing red dress'" -ForegroundColor Gray
