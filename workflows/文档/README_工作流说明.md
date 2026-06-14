# 工作流使用说明

> 最后更新: 2026-06-14
> 当前保留 4 个工作流，其余旧版已清理

---

## 工作流总览

| 工作流 | 文件 | 模型 | 用途 |
|--------|------|------|------|
| Moody ZIT V7 写实人像 | `MoodyZIT_V7_写实人像_小图放大超分_4K级竖屏.json` | MoodyRealMix ZIT V7 FP8 | **主力** — 写实人像，质量最高 |
| Hunyuan 2.1 文生图 | `混元2.1_Q3_竖屏两阶段超分精修_4K级人像.json` | HunyuanImage 2.1 Lite Q3 | 中文原生理解 + 文字渲染（**不推荐写实人像**） |
| QwenImage 文字生成 | `QwenImage_文字生成_1024x1024.json` | QwenImage 2512 FP8 | 纯文字/招牌图生成 |
| Anima v10 图生图批量 | `Anima_v10_图生图_批量处理.json` | Anima-base v1.0 | Anime 风格批量图生图 |

---

## 一、Moody ZIT V7 写实人像（主力）

**一句话**：先画小图（640×960），再放大、重绘、AI 超分到 2720×4080（4K 级竖屏）。

> **完整指南**：[Moody_ZIT_完整指南与踩坑手册.md](./Moody_ZIT_完整指南与踩坑手册.md)
> 包含从零安装、模型下载、插件安装、出图步骤、Prompt 工程、参数微调、常见问题等全部内容。

---

## 二、Hunyuan 2.1 文生图

**一句话**：腾讯混元开源文生图模型，原生中文理解强，可在图中渲染汉字。

> **⚠️ 写实人像不推荐**：经实测，混元 2.1 在写实人像场景下效果远不如 MoodyZIT V7（不到一半水平）。
> 即使套用了相同的后处理管线（两阶段采样 + 潜空间放大 + UltimateSDUpscale + FaceDetailer），
> 上游模型质量差距无法通过下游精修弥补。混元 2.1 更适合中文场景理解、文字渲染等通用任务。
> 详见下方「为什么混元写实人像效果差」分析。

### 模型依赖

| 文件 | 放置路径 | 大小 |
|------|---------|------|
| hunyuanimage2.1-q3_k_s.gguf | models/diffusion_models/ | ~8GB |
| qwen_2.5_vl_7b_fp8_scaled.safetensors | models/text_encoders/ | ~5GB |
| byt5-small-glyphxl/byt5_small_glyphxl.safetensors | models/text_encoders/ | ~1.5GB |
| pig_hunyuan_image_vae_fp32-f16.gguf | models/vae/ | ~600MB |

### 插件依赖
- `ComfyUI-GGUF`（Manager 搜索安装）

### 关键设计
- **DualCLIP**：Qwen2.5-VL（语义理解）+ ByT5（字形编码），缺一不可
- **CLIP 放 CPU**：`DualCLIPLoaderGGUF` 的 device 设为 `cpu`，为 12GB 显存让路
- 分辨率：768×1344 竖屏（两阶段采样后约 1152×2016）
- 步数：第一阶段 15（euler/simple），第二阶段 10（dpmpp_2m_sde/sgm_uniform, denoise=0.65）
- 后处理：UltimateSDUpscale 1.5x（denoise=0.23）+ FaceDetailer（denoise=0.45）
- 最终输出：约 1728×3024（接近 4K 竖屏）

### 为什么混元写实人像效果差

| 原因 | 说明 |
|------|------|
| **模型定位** | 混元 2.1 是通用生图模型，MoodyZIT 的 moodyRealMix 是专门针对写实人像微调的 |
| **缺少 LoRA** | MoodyZIT 叠了两个写实人像 LoRA（momoka-zib-v2 + zit_sda_v1），混元社区目前无适配 LoRA |
| **VAE 精度** | 混元用 GGUF 量化 VAE（fp32-f16），MoodyZIT 用全精度 ae.safetensors，解码细节有差距 |
| **Q3 量化** | 权重精度损失在写实人像这种对细节要求极高的场景下会被放大 |
| **结论** | 同样的后处理管线，上游模型质量差，下游再怎么修也救不回来 |

### 常见问题
- **爆显存闪退**：确认没有其他模型常驻显存，必要时重启 ComfyUI
- **OSError / 模型加载失败**：确认 GGUF 文件完整，未损坏
- **API 提交失败 (HTTP 400/500)**：工作流 JSON 必须是 API 格式（以节点 ID 为 key），不能直接用 UI 格式（nodes/links 数组）提交

---

## 三、QwenImage 文字生成

**一句话**：专门生成带文字的图像（招牌、海报、UI 文字），文字渲染准确度高于通用模型。

### 模型依赖

| 文件 | 放置路径 |
|------|---------|
| qwen_image_2512_fp8_e4m3fn.safetensors | models/diffusion_models/ |
| qwen_2.5_vl_7b_fp8_scaled.safetensors | models/text_encoders/ |
| qwen_image_vae.safetensors | models/vae/ |

### 使用提示
- prompt 里直接写你要的文字内容，用英文引号包裹
- 适合：店铺招牌、海报标题、UI 界面文字
- 分辨率：1024×1024

---

## 四、Anima v10 图生图批量

**一句话**：把一批图片批量转换成 anime/2.5D 风格。

### 模型依赖

| 文件 | 放置路径 |
|------|---------|
| anima-base-v1.0.safetensors | models/diffusion_models/ |
| qwen_3_06b_base.safetensors | models/text_encoders/ |
| qwen_image_vae.safetensors | models/vae/ |
| Niji_cute_epoch_8.safetensors | models/loras/ |

### 使用步骤
1. 将图片放入 `ComfyUI/input/img2img/` 文件夹
2. 拖入 JSON 加载工作流
3. 选择批量模式（自动读取文件夹）或单张模式（手动加载）
4. 调节 denoise：0.25-0.35 轻风格化 / 0.4 推荐 / 0.5-0.6 强风格
5. Queue Prompt

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| denoise | 0.4 | 风格转换强度 |
| LoRA 权重 | 0.8 | Niji cute 风格 |
| CFG | 5 | 引导强度 |
| Steps | 28 | 采样步数 |
| scale_by | 2 | 输出放大倍率 |
| crop 尺寸 | 768×1024 | 输入图片裁剪尺寸 |

### 输出位置
`ComfyUI/output/Anima/img2img/`

---

## 快速选型

| 需求 | 推荐工作流 |
|------|-----------|
| 写实人像，最高质量 | Moody ZIT V7 |
| 中文场景，图中带汉字 | Hunyuan 2.1（通用任务可用，写实人像不推荐） |
| 纯文字/招牌生成 | QwenImage |
| 图片转 anime 风格 | Anima v10 |

---

## 常见问题

### Q: 加载工作流出现红色节点？
A: 记录红色节点的名称，在 Manager 中搜索安装对应插件后重启 ComfyUI。

### Q: 模型路径显示红色？
A: 确认模型文件已放入文档中指定的目录，文件名完全一致（含大小写）。

### Q: 显存不足 (OOM)？
A: 关闭其他占用显存的程序，重启 ComfyUI 确保显存释放。Hunyuan 用户可尝试将分辨率降至 512×512。
