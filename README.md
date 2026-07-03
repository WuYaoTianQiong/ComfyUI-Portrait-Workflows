# ComfyUI Portrait Workflows

ComfyUI 写实人像工作流合集，专注于高质量人像生成与提示词管理。

## 工作流列表

### API 远程生成类
- **`MoodyZIT_V7_API_图生图_Inpaint手动遮罩_SeedVR2超分.json`** — API 模式，Inpaint + 超分
- **`MoodyZIT_V7_API_文生图_双程采样_SeedVR2_4K超分_文字渲染.json`** — API 模式，双程采样 + 4K 文字渲染
- **`Work-Fisher_Qwen-AIO_DWPose提取_图生图_API.json`** — API 模式，DWPose 骨骼控图
- **`Qwen3VL_API_图生中文提示词.json`** — API 模式，VLM 图生提示词

### Visual 编辑器类
- **`MoodyZIT_V7_Visual_文生图_双程采样_快速预览_文字渲染.json`** — Visual 模式，双程采样 + 文字渲染
- **`Qwen-2512_OpenPose编辑器_ControlNet_文生图_12G.json`** — OpenPose 编辑器控图
- **`Qwen-Rapid_OpenPose_文生图_9x16画幅切换.json`** — OpenPose 编辑器 + 画幅切换
- **`灵犀控骨_VNCCS骨骼控图_一键横竖切换_图生图_Visual.json`** — VNCCS 骨骼控图

### 风格化 & 动漫类
- **`AnimagineXL_3.1_漫画文生图.json`** — AnimagineXL 漫画风格
- **`Flux1_Dev_漫画文生图.json`** — Flux 漫画风格
- **`MoodyProMix_中文漫画_文生图.json`** — MoodyProMix 中文漫画
- **`NoobAI-XL_Vpred_动漫文生图.json`** — NoobAI 动漫风格
- **`Qwen-Rapid_中文文生图.json`** — Qwen-Rapid 通用文生图
- **`Anima_2.5D_文生图_基础版.json`** — Anima 2.5D 风格
- **`Anime_Bushes_EN.json`**  / **`Anime_PearlyToon_EN.json`** — Anime 风格英文版

### 超分 & 辅助类
- **`图片超分_SeedVR2_多分辨率版.json`** — SeedVR2 通用超分

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

## 文档与工具

- [MoodyZIT 完整指南](workflows/文档/Moody_ZIT_完整指南与踩坑手册.md) - 从安装到出图的完整教程
- [LoRA 训练规划](workflows/文档/LoRA训练_定制人脸_完整规划.md) - 自定义人脸训练
- [提示词浏览器](workflows/脚本/prompt_browser_v4/) - 提示词管理、组合创作、历史追踪的 Web 工具

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
