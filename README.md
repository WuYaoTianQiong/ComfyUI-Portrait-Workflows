# ComfyUI Portrait Workflows

ComfyUI 写实人像工作流合集，专注于高质量人像生成与提示词管理。

## 工作流列表

> 以 `workflows/` 根目录磁盘为准（当前 **10 个 JSON**，2026-11-01）。
> 另有 `workflows/历史工作流/`（归档）：Atelier 默认只扫根目录，归档/其他目录需要时
> 在「分类与标签 → 工作流」手动上传 JSON。

### 文生图
- **`MoodyKrea2_V8SE_文生图_单程8步_1128x2008_画质优先.json`** — Krea2 单程 8 步，画质优先
- **`MoodyZIT_V13_Visual_文生图_双程采样_快速预览_文字渲染.json`** — Z-Image 双程采样，文字渲染
- **`PornMaster_Krea2V25_文生图_单程8步_1192x2112_fp8_画质优先.json`** — Krea2V25 单程 8 步 fp8

### 图像编辑（Flux.2 Klein）
- **`PornMaster_Flux2Klein9B_单图编辑_可选遮罩.json`** — 单图编辑 + 可选遮罩
- **`PornMaster_Flux2Klein9B_双图参考换衣_可选遮罩.json`** — 双图参考换衣
- **`PornMaster_Flux2Klein9B_三图参考编辑_自动尺寸.json`** — 三图参考编辑

### 辅助
- **`Qwen3VL_API_图生中文提示词.json`** — VLM 图生中文提示词
- **`图片超分_SeedVR2_7B_源图命名_最高4K实测.json`** — SeedVR2 7B 超分

### 视频（Atelier 不收录）
- **`MiniMax_H3_文生视频_官方原版.json`**
- **`MiniMax_H3_图生视频_官方原版.json`**

> 这两个工作流含 `SaveVideo`，Atelier 的工作流下拉默认隐藏；请直接在 ComfyUI 里运行。
> Atelier 的画廊/结果中心只处理图片，视频没有对应归档链路。

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
- [资产清单](workflows/文档/资产清单.md) - 工作流 / 模型 / 插件 / LoRA 的磁盘实测清单
- [命名规范](workflows/文档/命名规范.md) - 工作流/目录/代码/API 的命名约定
- [画室 Atelier](workflows/脚本/atelier/) - 提示词资产 + ComfyUI 出图/组合/换脸工作台

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

- 2026-11-01: 工作流列表按磁盘实测同步（10 个在用 + 2 个视频工作流标记为 Atelier 不收录）；
  文档链接清理，补充资产清单与命名规范。
- 2026-06-14: 初始版本，包含 4 个工作流
