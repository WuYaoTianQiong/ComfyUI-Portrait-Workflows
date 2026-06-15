"""
下载 CLIPSeg 模型到 ComfyUI/models/clip_seg/ 目录

使用方法：
1. 确保已安装依赖：pip install huggingface_hub transformers
2. 运行脚本：python download_clipseg_model.py
3. 模型会自动下载到：ComfyUI/models/clip_seg/CIDAS--clipseg-rd64-refined/
"""

import os
import sys

# 设置 HF 镜像（必须在导入 huggingface_hub 之前设置）
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 获取 ComfyUI 根目录（脚本放在 workflows/脚本/ 下）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS_DIR = os.path.dirname(SCRIPT_DIR)
COMFYUI_DIR = os.path.dirname(WORKFLOWS_DIR)
MODELS_DIR = os.path.join(COMFYUI_DIR, "models")
CLIPSEG_DIR = os.path.join(MODELS_DIR, "clip_seg")
TARGET_DIR = os.path.join(CLIPSEG_DIR, "CIDAS--clipseg-rd64-refined")

# 检查是否已下载
if os.path.exists(TARGET_DIR) and len(os.listdir(TARGET_DIR)) > 0:
    print(f"[成功] 模型已存在于：{TARGET_DIR}")
    print("无需重新下载。")
    sys.exit(0)

# 创建目标目录
os.makedirs(TARGET_DIR, exist_ok=True)

print("开始下载 CLIPSeg 模型...")
print(f"目标目录：{TARGET_DIR}")
print(f"使用镜像：{os.environ['HF_ENDPOINT']}\n")

try:
    from huggingface_hub import snapshot_download
    
    # 下载模型
    snapshot_download(
        repo_id="CIDAS/clipseg-rd64-refined",
        local_dir=TARGET_DIR,
        local_dir_use_symlinks=False
    )
    
    print(f"\n[成功] 模型下载完成！")
    print(f"路径：{TARGET_DIR}")
    print("\n现在可以加载 Inpaint 工作流，CLIPSeg 节点会从本地加载模型。")
    
except ImportError as e:
    print(f"[错误] 未安装 huggingface_hub: {e}")
    print("请先安装依赖：")
    print("pip install huggingface_hub transformers")
    sys.exit(1)
    
except Exception as e:
    print(f"[错误] 下载失败：{e}")
    print("\n可能的原因：")
    print("1. 网络不通（需翻墙或设置镜像）")
    print("2. HuggingFace 账号未登录（运行：huggingface-cli login）")
    print(f"\n当前镜像设置：{os.environ.get('HF_ENDPOINT', '未设置')}")
    print("如果镜像无效，尝试直接翻墙后运行脚本。")
    sys.exit(1)
