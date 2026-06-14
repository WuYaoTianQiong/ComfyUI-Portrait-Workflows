# ComfyUI Portrait Workflows

ComfyUI 写实人像工作流合集，专注于高质量人像生成。

## 工作流列表

### 1. MoodyZIT V7 - 写实人像（主力）
- **文件**: `MoodyZIT_V7_写实人像_小图放大超分_4K级竖屏.json`
- **特点**: 两阶段采样 + 潜空间放大 + UltimateSDUpscale + FaceDetailer
- **输出**: 2720×4080（4K级竖屏）
- **显存**: 约 9GB
- **文档**: [完整指南](workflows/文档/Moody_ZIT_完整指南与踩坑手册.md)

### 2. Hunyuan 2.1 - 混元文生图
- **文件**: `混元2.1_Q3_竖屏两阶段超分精修_4K级人像.json`
- **特点**: 腾讯混元模型，中文理解强
- **输出**: 768×1344 → 1728×3024
- **显存**: 约 12GB
- **注意**: 写实人像效果不如 MoodyZIT，更适合中文场景

### 3. QwenImage - 文字生成
- **文件**: `QwenImage_文字生成_1024x1024.json`
- **特点**: 专门用于生成带文字的图像
- **输出**: 1024×1024

### 4. Anima v10 - 图生图批量
- **文件**: `Anima_v10_图生图_批量处理.json`
- **特点**: Anime 风格批量转换
- **输出**: 1536×2048

## 快速开始

### 环境要求
- NVIDIA 显卡，显存 ≥ 8GB（推荐 12GB+）
- Python 3.10-3.12
- ComfyUI 最新版

### 安装步骤
1. 安装 ComfyUI（推荐使用秋叶整合包）
2. 安装必要插件（通过 ComfyUI Manager）
3. 下载模型文件（见各工作流文档）
4. 导入工作流 JSON 文件
5. 开始生成

### 必要插件
- ComfyUI-Manager
- ComfyUI-GGUF
- ComfyUI-Impact-Pack
- ComfyUI-Inspire-Pack
- ComfyUI_UltimateSDUpscale

## 模型下载

### MoodyZIT V7 模型
| 文件 | 大小 | 来源 |
|------|------|------|
| moodyRealMix_zitV7GlobalFP8.safetensors | ~16GB | [HuggingFace](https://huggingface.co/Aitrepreneur/moodyRealMix_Zit_V7) |
| qwen_3_4b.safetensors | ~7.6GB | 同上 |
| ae.safetensors | ~300MB | 同上 |
| momoka-zib-v2_clean.safetensors | ~150MB | HuggingFace/Civitai |
| zit_sda_v1.safetensors | ~150MB | 同上 |
| 4xNomos8kDAT.safetensors | ~150MB | [OpenModelDB](https://openmodeldb.info/models/4x-Nomos8kDAT) |

### Hunyuan 2.1 模型
| 文件 | 大小 | 来源 |
|------|------|------|
| hunyuanimage2.1-q3_k_s.gguf | ~8GB | [HuggingFace](https://huggingface.co/Tencent/HunyuanImage) |
| qwen_2.5_vl_7b_fp8_scaled.safetensors | ~5GB | [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct-FP8) |
| byt5-small-glyphxl.safetensors | ~1.5GB | [HuggingFace](https://huggingface.co/Tencent/HunyuanImage) |
| pig_hunyuan_image_vae_fp32-f16.gguf | ~600MB | [HuggingFace](https://huggingface.co/Tencent/HunyuanImage) |

### 国内下载方案
```bash
# 使用 hf-mirror.com 镜像
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download <repo_name>

# 或手动访问镜像站下载
# https://hf-mirror.com/<repo_name>
```

## 文档

- [工作流说明](workflows/文档/README_工作流说明.md) - 各工作流详细说明
- [MoodyZIT 完整指南](workflows/文档/Moody_ZIT_完整指南与踩坑手册.md) - 从安装到出图的完整教程
- [LoRA 训练规划](workflows/文档/LoRA训练_定制人脸_完整规划.md) - 自定义人脸训练

## 常见问题

### Q: 显存不足怎么办？
A: 关闭其他占用显存的程序，或降低 UltimateSDUpscale 的 tile_size（默认 1024，可降至 768 或 512）。

### Q: 模型下载失败？
A: 使用 hf-mirror.com 镜像，或检查网络连接。

### Q: 工作流加载后节点显示红色？
A: 缺少必要的插件，通过 ComfyUI Manager 安装对应插件后重启。

## License

MIT

## 更新日志

- 2026-06-14: 初始版本，包含 4 个工作流
