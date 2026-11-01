"""直接下载 flux1-fill-dev.safetensors，显示进度"""
import os
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

HF_TOKEN = os.environ.get("HF_TOKEN", "")
target_dir = r"F:\ComfyUI_Migration\models\diffusion_models"
os.makedirs(target_dir, exist_ok=True)

model_path = os.path.join(target_dir, "flux1-fill-dev.safetensors")
if os.path.exists(model_path):
    size_gb = os.path.getsize(model_path) / 1024**3
    print(f"文件已存在: {model_path} ({size_gb:.2f} GB)")
    if size_gb > 12:
        print("文件完整，无需重复下载")
        exit(0)
    else:
        print(f"文件不完整({size_gb:.2f} GB < 14GB)，重新下载...")

from huggingface_hub import hf_hub_download, logging
logging.set_verbosity_info()

print("正在从 huggingface.co 下载 flux1-fill-dev.safetensors (~14GB) ...")
print("会显示下载进度条...")
path = hf_hub_download(
    repo_id="black-forest-labs/FLUX.1-Fill-dev",
    filename="flux1-fill-dev.safetensors",
    local_dir=target_dir,
    local_dir_use_symlinks=False,
    token=HF_TOKEN,
    resume_download=True,
)
print(f"下载完成: {path}")
print(f"文件大小: {os.path.getsize(path) / 1024**3:.2f} GB")
