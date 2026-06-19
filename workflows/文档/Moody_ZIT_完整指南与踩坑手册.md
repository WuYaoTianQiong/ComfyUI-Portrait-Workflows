# Moody ZIT V7 写实人像 — 完整指南与踩坑手册

> 最后更新: 2026-06-18
> 适用环境: ComfyUI-aki-v2 + RTX 5070 12GB (或同等显卡)
> 模型: moodyRealMix_zitV7GlobalFP8.safetensors (Z-Image-Turbo 6B)
> 推荐工作流:
>   - 1080P日常: MoodyZIT_V7_1080P清晰版_API.json (20秒)
>   - 4K超分: MoodyZIT_V7_API_双程采样_SeedVR2_4K超分_文字渲染.json (~55秒，CodeFormer可选关闭)
>
> **本文档包含从零安装到出图的全部内容，新手按顺序执行即可。**

---

## 一、从零开始安装（新手必读）

### 1. 硬件要求

| 项目 | 最低 | 推荐 | 本工作流验证环境 |
|------|------|------|-----------------|
| 显卡 | NVIDIA ≥ 8GB | 12GB+ | RTX 5070 12GB |
| 硬盘剩余 | ≥ 50GB | SSD | — |
| 系统 | Windows 10/11 | — | — |
| Python | 3.10-3.12 | 3.12 | 3.12.10 |
| PyTorch | 2.6+ | 2.11 + CUDA 12.8 | — |
| ComfyUI | **v0.24.0+**（低于此版本 SeedVR2 无法加载） | — | v0.24.0 |

### 2. 安装 ComfyUI

**方式 A（推荐，一键包，Windows）**：
1. 搜索下载「ComfyUI 秋叶启动器」（绘世启动器）
2. 解压到任意目录（路径**不要含中文或空格**）
3. 运行「绘世启动器.exe」→ 点击「启动」
4. 等待自动下载依赖，浏览器打开 http://127.0.0.1:8188

**方式 B（官方源码，全平台）**：
1. 安装 Git → https://git-scm.com/download/win
2. 安装 Python 3.10-3.12 → https://python.org（安装时勾选「Add to PATH」）
3. 终端执行：
   ```
   git clone https://github.com/comfyanonymous/ComfyUI.git
   cd ComfyUI
   pip install -r requirements.txt
   python main.py
   ```
4. 浏览器访问 http://127.0.0.1:8188

### 3. 安装插件

打开 ComfyUI → 右侧「Manager」→ 搜索安装以下插件：

| 插件名 | 搜索关键词 | 用途 |
|--------|-----------|------|
| ComfyUI_UltimateSDUpscale | UltimateSDUpscale | 分块超分（必须） |
| ComfyUI-Impact-Pack | Impact | FaceDetailer 人脸精修（可选） |
| ComfyUI-Inspire-Pack | Inspire | MediaPipe 人脸检测（可选） |

安装完成后，点击 Manager →「Restart」重启 ComfyUI。

### 4. 下载模型文件

以下 6 个文件**必须全部下载**并放入指定目录，总大小约 25GB。建议用迅雷或 IDM 加速。

| # | 文件名 | 放置路径 | 大小 | 来源 |
|---|--------|---------|------|------|
| 1 | moodyRealMix_zitV7GlobalFP8.safetensors | models/diffusion_models/ | ~16GB | [HuggingFace](https://huggingface.co/Aitrepreneur/moodyRealMix_Zit_V7) |
| 2 | qwen_3_4b.safetensors | models/text_encoders/ | ~7.6GB | 同上 |
| 3 | ae.safetensors | models/vae/ | ~300MB | 同上 |
| 4 | momoka-zib-v2_clean.safetensors | models/loras/ | ~150MB | HF/Civitai 搜索「momoka zib v2」 |
| 5 | zit_sda_v1.safetensors | models/loras/ | ~150MB | 同上 HuggingFace |
| 6 | 4xNomos8kDAT.safetensors | models/upscale_models/ | ~150MB | [openmodeldb](https://openmodeldb.info/models/4x-Nomos8kDAT) |

**目录结构**：
```
ComfyUI/
├── models/
│   ├── diffusion_models/
│   │   └── moodyRealMix_zitV7GlobalFP8.safetensors
│   ├── text_encoders/
│   │   └── qwen_3_4b.safetensors
│   ├── vae/
│   │   └── ae.safetensors
│   ├── loras/
│   │   ├── momoka-zib-v2_clean.safetensors
│   │   └── zit_sda_v1.safetensors
│   └── upscale_models/
│       └── 4xNomos8kDAT.safetensors
```

### 5. 加载工作流并出图

1. 确保 ComfyUI 正在运行（http://127.0.0.1:8188）
2. 将 `MoodyZIT_V7_写实人像_小图放大超分_4K级竖屏.json` **直接拖入** ComfyUI 画布
3. 检查是否有**红色节点**（缺失插件）→ 有则回到第 3 步安装
4. 检查模型路径是否显示**红色**（文件名不匹配）→ 有则核对文件名
5. 双击节点 8（CLIPTextEncode，绿色文本框）修改 prompt
6. 点击「Queue Prompt」，等待 3-5 分钟
7. 输出图片保存在 `ComfyUI/output/` 目录

---

## 二、核心结论

**本工作流是 MoodyRealMix ZIT 系列的最新主力版本，全面取代 V6。**

相比 V6，V7 FP8 的改进：
- 面部质感和光影准确度更高
- 训练数据更丰富，肢体畸形率降低
- FP8 量化在 12GB 显存下运行稳定

### 分辨率管线

| 阶段 | 分辨率 | 操作 | 输出 |
|------|--------|------|------|
| 基底生成 | 640×960 | KSamplerAdvanced 12步(0→12) | 低分辨率草图 |
| Latent 放大 | 1088×1632 | 1.7x bislerp | latent 空间放大 |
| ZIT 精修 | 1088×1632 | KSamplerAdvanced(5→999步) | 细节填充 |
| VAEDecode | 1088×1632 | 解码到像素 | 中间图像 |
| CodeFormer | 1088×1632 | 面部增强(fidelity=0.55) | 面部精修 |
| SeedVR2 | **2160×3240** | 超分到目标分辨率 | **最终输出** |

> 总像素：约 700 万（4K 级竖屏）

### 关键参数速查

| 参数 | 值 |
|------|-----|
| 阶段一 采样器 | euler / simple |
| 阶段二 采样器 | dpmpp_2m_sde / sgm_uniform |
| 阶段一 CFG | 3.0 |
| 阶段二 CFG | 1.0 |
| 阶段一 步数 | 17(0→12) |
| 阶段二 步数 | 11(5→999) |
| LatentUpscaleBy | 1.7x bislerp |
| CodeFormer fidelity | 0.55 |
| SeedVR2 resolution | 2160 |
| 显存占用 | ~8-9GB |
| 单图耗时 | 3-4 分钟 (RTX 5070) |

---

## 二、模型依赖

以下 9 个文件必须全部下载并放入指定目录。

| # | 文件 | 放置路径 | 用途 |
|---|------|---------|------|
| 1 | moodyWild_zibV4Base40steps_fp8.safetensors | models/diffusion_models/ | 阶段一：基底生成 |
| 2 | moodyRealMix_zitV7GlobalFP8.safetensors | models/diffusion_models/ | 阶段二：ZIT精修 |
| 3 | seedvr2_ema_3b_fp8_e4m3fn.safetensors | models/diffusion_models/ | SeedVR2超分 |
| 4 | qwen_3_4b.safetensors | models/text_encoders/ | 文本编码器 |
| 5 | ae.safetensors | models/vae/ | 主VAE |
| 6 | ema_vae_fp16.safetensors | models/vae/ | SeedVR2 VAE |
| 7 | momoka-zib-v2_clean.safetensors | models/loras/ | 角色LoRA(阶段一) |
| 8 | zit_sda_v1.safetensors | models/loras/ | ZIT风格LoRA(阶段二) |
| 9 | codeformer.pth | models/facerestore_models/ | 面部增强 |

### 插件依赖

| 插件 | 搜索关键词 | 用途 |
|------|-----------|------|
| ComfyUI-SeedVR2_VideoUpscaler | `SeedVR2` | 超分 |
| facerestore_cf | `facerestore` | 面部增强 |

---

## 三、使用步骤

### 1. 环境确认
- NVIDIA 显卡，显存 >= 8GB（推荐 12GB+）
- 硬盘剩余 >= 50GB
- ComfyUI 本体已安装并运行

### 2. 安装插件
打开 ComfyUI → Manager → 搜索安装以下插件 → Restart

| 插件 | 搜索关键词 |
|------|-----------|
| ComfyUI-SeedVR2_VideoUpscaler | `SeedVR2` |
| facerestore_cf | `facerestore` |

### 3. 放置模型
按上表将 9 个模型文件放入对应目录。

### 4. 加载工作流
将 `MoodyZIT_V7_文生图_写实人像_SeedVR2超分_CodeFormer面部增强.json` 拖入 ComfyUI 画布。

### 5. 修改 Prompt
双击节点 7（CLIPTextEncode）修改积极提示词，节点 8 修改消极提示词。

### 6. 生成
点击 **Queue Prompt**，等待 3-4 分钟。

---

## 四、Prompt 工程指南

### 提示词节点

| 节点 | 用途 |
|------|------|
| 节点 7（CLIPTextEncode） | **积极提示词** — 描述你想生成的画面 |
| 节点 8（CLIPTextEncode） | **消极提示词** — 描述不想出现的内容，可留空 |

### 负面词策略

本工作流使用独立的消极提示词节点（节点 8），可以留空或填写不想出现的内容。
如果效果不佳，优先优化**正提示词**的描述精度。

### 肢体/姿势避坑

以下描述容易导致 AI 解剖错误，建议避免或简化：

| 高风险描述 | 问题 | 替代方案 |
|-----------|------|---------|
| 蹲姿 + 抬脚跟 + 露脚底 | 脚趾蜷缩、脚底变形 | 改为"双脚自然放松，脚趾舒展" |
| 手指触碰玻璃 + 复杂手部动作 | 多指、畸形 | 减少手部动作，或只保留单手指触碰 |
| 极度夸张的透视角度 | 面部/身体比例崩坏 | 使用平视或轻微俯仰角 |

### 光线与材质

以下关键词对本模型效果显著：

- `冷白荧光灯从上方打下` — 便利店/室内场景
- `皮肤油亮，胸口汗珠滑落` — 增强真实肤质
- `背景货架虚化` — 自然景深
- `玻璃 reflection` — 已内置，可追加 `ray tracing, physically accurate lighting`

---

## 五、面部增强与超分

### 内置管线

本工作流已内置完整的面部增强和超分管线：

```
VAEDecode → CodeFormer面部增强(fidelity=0.55) → SeedVR2超分(→4K) → SaveImage
```

- **CodeFormer**：自动检测并增强面部细节，fidelity=0.55 平衡了修复强度和原貌保留
- **SeedVR2**：原生DiT扩散超分，resolution=2160 输出4K级竖屏

### 调整面部增强强度

如需调整CodeFormer强度，修改节点17的 `codeformer_fidelity` 参数：

| 值 | 效果 |
|-----|------|
| 0.2-0.3 | 强修，磨皮感重 |
| 0.5-0.6 | 平衡（默认0.55） |
| 0.7-0.8 | 轻修，保留原貌 |

### 调整超分分辨率

修改节点20的 `resolution` 参数（目标最短边）：

| 值 | 输出尺寸（竖屏） | 显存占用 |
|-----|----------------|---------|
| 1080 | 1080×1620 | ~6GB |
| 2160 | 2160×3240（默认） | ~8-9GB |
| 2560 | 2560×3840 | ~10GB |

> **注意**：`resolution` 是最短边，不是长边。设 2160 才能得到 2160×3240 的竖屏4K。

---

## 六、常见问题与踩坑

### Q1: 红色节点报错？
**原因**：缺少插件或模型文件未找到。

**排查**：
1. 记录红色节点的名称（如 `SeedVR2VideoUpscaler`）
2. Manager 中搜索并安装对应插件
3. 重启 ComfyUI
4. 检查模型路径是否显示为红色（文件名不匹配或目录错误）

### Q2: 生成结果和预期差距大？
**排查清单**：
- [ ] 9 个模型文件全部正确放置（特别是两个 LoRA）
- [ ] 节点 4/12 的 LoRA 路径未显示红色
- [ ] 阶段一用 moodyWild_zibV4Base，阶段二用 moodyRealMix_zitV7Global
- [ ] 提示词已正确填写

### Q3: 显存不足 (OOM) 或闪退？
**解决**：
1. 关闭其他占用显存的程序
2. 重启 ComfyUI（确保之前模型的显存缓存已释放）
3. 降低 SeedVR2 的 `resolution`（默认 2160，可降到 1080）
4. 增大 SeedVR2 的 `blocks_to_swap`（默认 6，可提高到 12-36）

### Q4: 面部模糊/眼神空洞？
**方案 A**：提高 CodeFormer fidelity（默认 0.55，可试 0.7-0.8 轻修保留更多细节）
**方案 B**：在正提示词中追加 `detailed face, clear eyes, sharp focus`

### Q5: 皮肤太白/太假？
本工作流默认风格是**极致冷白皮**，如需自然肤色：
- 删除或弱化 prompt 中的 `极致冷白皮，通体雪白，overexposure`
- 替换为 `自然肤色，柔和光影`

### Q6: 输出有水印/文字/签名？
本工作流已内置文字抑制（`text` 关键词在负面抑制列表中）。如果出现：
- 检查是否使用了其他 embedding 或 LoRA 引入了水印
- 在正提示词末尾追加 `no watermark, no text, no signature`

### Q7: 玻璃反射效果不明显？
- 确认 prompt 中保留了内置的玻璃反射关键词
- 追加 `ray tracing, physically accurate lighting, visible reflection on floor`
- 注意：ZIT V7 训练数据以人像为主，物理反射是模拟效果，非光线追踪级真实

---

## 七、参数微调建议

| 需求 | 修改项 | 建议值 |
|------|--------|--------|
| 更快出图 | 阶段一 end_at_step | 10（默认 12） |
| 更稳构图 | 阶段一 end_at_step | 14（默认 12） |
| 更锐超分 | SeedVR2 input_noise_scale | 0.05（默认 0） |
| 更大胆创意 | 阶段一 CFG | 4.0-5.0（默认 3.0） |
| 更保守还原 | 阶段二 CFG | 0.8-1.0（默认 1.0） |
| 更轻面部修复 | CodeFormer fidelity | 0.7-0.8（默认 0.55） |
| 更低显存 | SeedVR2 blocks_to_swap | 12-36（默认 6） |

> **注意**：阶段一 CFG > 5.0 可能导致色彩过饱和或伪影。ZIT 阶段二推荐 CFG=1.0。

---

## 八、ZIB/ZIT 双程 LoRA 使用技巧

> 来源: 原版 ZIT 双程工作流（Moody_ZIT_V7.6_原版工作流_ZIT双程.json）

### 核心原则

- **全线 MOODY 系列模型均推荐使用 ZIB LoRA**
- ZIB 步骤使用的 LoRA → 影响**构图和动作**
- ZIT 步骤使用的 LoRA → 影响**更多细节**

### 权重建议

| 步骤 | LoRA 类型 | 最大推荐强度 | 说明 |
|------|----------|------------|------|
| ZIB（阶段一） | ZIB LoRA | ≤ 1.2 | 控制构图、姿势 |
| ZIT（阶段二） | ZIT LoRA | ≤ 0.5 | 控制细节 |

### 高度相似人物技巧

如需超级相似的人物，可将 ZIB 人物 LoRA **同时放在 ZIB 和 ZIT 两步**中。

---

## 九、分辨率参考表

| 画面比例 | 备注 | 基础分辨率 (W×H) | 最终分辨率 ×1.8 (W×H) | 最终总像素 |
|---------|------|-----------------|---------------------|----------|
| 2:3 | 基础竖图 | 640 × 960 | 1152 × 1728 | 1,990,656 |
| 3:4 | 稳定竖图 | 672 × 896 | 1210 × 1613 | 1,951,730 |
| 9:16 | 手机竖屏长图 | 576 × 1024 | 1037 × 1843 | 1,911,191 |
| 3:2 | 横图基准 | 960 × 640 | 1728 × 1152 | 1,990,656 |
| 4:3 | 平衡横图 | 896 × 672 | 1613 × 1210 | 1,951,730 |
| 16:9 | 宽屏视频 | 1024 × 576 | 1843 × 1037 | 1,911,191 |
| 1:1 | 正方形 | 768 × 768 | 1382 × 1382 | 1,909,924 |

---

## 十、补充模型下载链接

### ZIT/ZIB 模型系列

| 模型名 | 类型 | 链接 |
|--------|------|------|
| Moody Real Mix | 软核，人像（推荐） | https://civitai.com/models/621441/moody-real-mix |
| Moody Porn Mix | 硬核 | https://civitai.com/models/620406/moody-porn-mix |
| Moody Wild Mix | ZIB/ZID 模型 | https://civitai.com/models/2384856/moody-wild-mix |

### Diversity Fix Adapter（多样性修复）

- **文件:** `zit_sda_v1.safetensors`
- **链接:** https://huggingface.co/F16/z-image-turbo-sda/resolve/main/zit_sda_v1.safetensors
- **用途:** 解决少步数蒸馏 Flow Matching / Diffusion 模型中的"多样性崩塌"问题

### 放大模型备选

| 模型 | 特点 | 链接 |
|------|------|------|
| 4xNomosWebPhoto_RealPLKSR | 推荐，更均衡 | https://github.com/Phhofm/models/releases/tag/4xNomosWebPhoto_RealPLKSR |
| 4xNomos8k_atd_jpg | 推荐，质量好但慢 | https://github.com/Phhofm/models/releases/download/4xNomos8k_atd_jpg/4xNomos8k_atd_jpg.safetensors |
| 4x UltraSharp | 通用 | https://openmodeldb.info/models/4x-UltraSharp |
| 1x SkinContrast | 皮肤增强 | https://openmodeldb.info/models/1x-SkinContrast-SuperUltraCompact |

---

## 十一、与其他工作流的对比

| 维度 | Moody ZIT V7 文生图 | 混元1.5 I2V | Wan2.2 TI2V 5B |
|------|-------------------|------------|----------------|
| 核心用途 | 写实人像生成 | 图片生成视频 | 图片生成长视频 |
| 输出类型 | 静态图片 | 视频(5秒) | 视频(10秒) |
| 模型大小 | ~8GB+6GB+3B | ~8GB | ~5GB(GGUF) |
| 最佳分辨率 | 2160×3240 | 704×1280 | 704×1280 |
| 中文理解 | 一般 | 优秀 | 一般 |
| 出图/视频速度 | 3-4min | 5-8min | 8-12min |
| 写实质量 | **最高** | 高 | 中高 |

---

## 九、技术选型与淘汰记录

### 为什么从 UltimateSDUpscale 切换到 SeedVR2

| 维度 | UltimateSDUpscale | SeedVR2 |
|------|-------------------|---------|
| 水印/水渍 | 高频出现地面彩色水渍、涂鸦 | 无此问题 |
| 面部效果 | 眼神疲惫、眼袋粗大（重绘过度平均化） | 更自然，保留原图神态 |
| 放大原理 | 潜空间重绘 + 分块tile拼接 | 原生DiT扩散超分，整体一致性更好 |
| 速度 | 3-5分钟 | 2-3分钟 |
| 显存 | ~9GB | ~8-9GB（blocks_to_swap=36） |

**结论**：SeedVR2 在写实人像超分场景下全面优于 UltimateSDUpscale，已成为当前主推超分方案。

### SeedVR2 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| resolution | 2160 | 目标最短边像素。640×960肖像 → 2160×3240（4K级） |
| blocks_to_swap | 6 | CPU offload 块数，12GB显存默认6，OOM可提高到12-36 |
| encode_tiled | true | VAE编码分块，防OOM |
| decode_tiled | true | VAE解码分块，防OOM |
| attention_mode | sdpa | 标准注意力，兼容性好 |

> **注意**：`resolution` 是最短边，不是长边。设 2160 才能得到 2160×3240 的竖屏4K。

### SeedVR2 踩坑：ComfyUI 版本过低导致加载失败

**现象**：ComfyUI 日志报 `Could not find working import path for comfy_api.latest`，`/object_info` 返回 500。

**原因**：SeedVR2 使用 **V3 API**（`ComfyExtension`）注册节点，依赖 `comfy_api/latest` 模块。该模块在 ComfyUI v0.12.x 之后的版本才加入。旧版（如 v0.9.x）没有此模块，导致节点注册失败。

**解决**（已验证，2026-06-16）：
1. 备份 `main.py` 等修改过的文件（`git stash`）
2. 执行 `git checkout master && git pull` 更新到最新版
3. 执行 `pip install -r requirements.txt` 安装新增依赖
4. Windows 用户额外执行 `pip install triton-windows`（PatchTritonVAE 需要）
5. 清缓存：删除 `__pycache__` 目录
6. 重启 ComfyUI

**对照表**：

| ComfyUI 版本 | comfy_api.latest | SeedVR2 加载 | 验证日期 |
|-------------|-----------------|-------------|---------|
| v0.9.2 | 不存在 | ❌ | 2026-06-15 |
| v0.24.0 | 存在 | ✅ | 2026-06-16 |

**来源**：[CSDN 博客](https://blog.csdn.net/m0_46551456/article/details/157871087)、ComfyUI 官方仓库

### SeedVR2 前端踩坑：JS 控制台报 "Cannot read properties of null (reading 'type')"

**现象**：浏览器 F12 控制台报错，但 SeedVR2 节点功能正常。

**原因**：新版 ComfyUI 前端尝试加载旧版节点 schema 时触发的兼容性警告，不影响功能。ComfyUI v0.24.0 下已无此问题。

### FaceDetailer 踩坑：ONNXDetectorProvider 不兼容 YOLOv8

**现象**：使用 `ONNXDetectorProvider` + `face_yolov8m.onnx` 时，FaceDetailer 报错 `bbox_detector is not a BBOX_DETECTOR`。

**原因**：Impact-Pack 的 ONNXDetectorProvider 只接受 mmdetection 风格的 ONNX（输出头分离：labels/scores/boxes）。YOLOv8 导出的 ONNX 是单输出头 `[num_predictions, 84]`，解析失败返回 None。

**正确方案**：使用 `MediaPipeFaceMeshDetectorProvider //Inspire`（来自 ComfyUI-Inspire-Pack），无需额外模型，直接调用 MediaPipe 人脸检测。

**操作**：
1. 安装 `ComfyUI-Inspire-Pack`
2. 在 FaceDetailer 的 `bbox_detector` 端连接 `MediaPipeFaceMeshDetectorProvider`
3. 参数：face=enable, max_faces=1，其余全部 disable

### 已淘汰的工作流与模型

| 淘汰项 | 淘汰原因 | 替代方案 |
|--------|---------|---------|
| 直接高分辨率生成（>960px） | VAE伪影、地面幻觉（鹅卵石/垃圾） | 640×960 + Lanczos |
| Qwen-Image 文字融合方案 | 两模型素材融合不自然 | MoodyZIT 原生文字渲染 |
| SeedVR2 @1080P | 低分辨率下降质严重 | Lanczos 或 SeedVR2@2160+ |
| UltimateSDUpscale 主超分 | 水渍、面部平均化 | SeedVR2 3B FP8 |
| YOLOv8 ONNX 人脸检测 | 与 Impact-Pack ONNXDetectorProvider 不兼容 | MediaPipeFaceMeshDetectorProvider |
| moody-wild-v4 / moody-real-V7G | 本地未找到模型文件 | moodyRealMix_zitV7GlobalFP8 |
| FP8_LoRA_雨天过马路 等旧工作流 | 参数过时，已被 V7 统一管线取代 | MoodyZIT_V7_写实人像 或 SeedVR2 |
| GGUF_Q8 系列工作流 | 画质不如 FP8，且 LoRA 兼容性差 | moodyRealMix_zitV7GlobalFP8 |

---

## 十二、2026-06-18 深度测试：分辨率、文字渲染与地面踩坑

> **结论先行**：MoodyZIT V7 的**唯一最佳分辨率就是 640×960**。任何试图直接生成更高分辨率的行为都会导致严重伪影。

### 模型架构真相

| 误解 | 真相 | 影响 |
|------|------|------|
| MoodyZIT = Flux 微调 | MoodyZIT = **Z-Image-Turbo 6B** 微调 | 6B小模型，分辨率上限低 |
| 和其他 Flux 模型一样 | Z-Image-Turbo 原生最高 ~1024×1024 | 640×960 是最优解 |
| V7 Global 是新版本 | 仅改善非亚洲脸，架构不变 | 分辨率限制依旧 |

> **Z-Image-Turbo 6B vs Flux 12B vs Flux.2 32B**：参数规模差距巨大，不是版本迭代能弥补的。

### 分辨率踩坑（核心！）

**问题**：直接生成 1152×1728 或更高分辨率时出现：

| 现象 | 根因 |
|------|------|
| 地面出现**沙子、鹅卵石、树枝** | AI把"水渍地面"错误关联为"池塘/河床" |
| 地面铺满**垃圾、碎屑** | 训练数据中"雨夜街道"=脏乱差 |
| 整体像**磨砂玻璃/高斯模糊** | ae.safetensors VAE 在大分辨率下降质 |
| 出现**电路板马赛克** | VAE 完全崩溃（>1400px） |

**解决**：**死守 640×960**，然后用 Lanczos 无损放大。

```
640×960 生成(18秒) → VAEDecode → ImageScale(Lanczos) → 1080×1620
         ↑ 原生舒适区                    ↑ 零AI伪影
```

| 方案 | 耗时 | 地面 | 清晰度 |
|------|------|------|--------|
| 640×960 原生 | 18秒 | ✅ 干净水泥+水渍 | ✅ 锐利 |
| 640×960 + Lanczos 1080P | ~20秒 | ✅ 同上 | ✅ 可用 |
| 1152×1728 直接 | 99秒 | ❌ 垃圾+鹅卵石 | ❌ 磨砂 |
| SeedVR2 @1080P | 39秒 | ⚠️ | ❌ 全图高斯模糊 |

> **SeedVR2 注意**：`resolution` 参数必须 ≥ 2160 才能正常工作。设为 1080 会严重降质。

### 文字渲染重大发现

**MoodyZIT 原生支持中英文文字渲染！**

| 文字类型 | 效果 | 提示词示例 |
|---------|------|-----------|
| 英文 | ✅ 清晰 | `clear readable neon text "24H OPEN"` |
| 中文 | ✅ 清晰 | `Chinese red neon sign "便利店"` |

- ✅ 无需 Qwen-Image
- ✅ 无需额外插件
- ✅ 直接写在提示词中即可
- ⚠️ 必须在 640×960 分辨率下生成，放大后文字仍可读

> **Qwen-Image 对比**：Qwen-Image 2512 文字渲染更强（尤其是特殊字体/排版），但人物质量远不如 MoodyZIT。**不需要融合方案**，MoodyZIT 自己就够了。

**完整提示词示例**（直接贴入节点 7 CLIPTextEncode）：
```
Full body shot, rainy night convenience store. Adult Chinese girl, innocent small round face, shy expression. Black long hair messy from rain. Standing in front of convenience store glass door. Chinese red neon sign "便利店" on glass. English "24H OPEN" in white neon below. Wearing light pink slim-fit knit top, white jacket, light blue denim shorts, white sneakers. High quality, photorealistic, sharp focus, 85mm lens.
```

### 负面提示词（经过多轮验证）

**推荐的负面词模板**（已实测有效）：
```
trash, garbage, litter, debris, dirt, mud, gravel, sand, pebbles, 
stones, pond, river, lake, nature, natural ground, outdoor wilderness, 
forest, park, garden, moss, soil, rocks, 
messy, dirty, cluttered, blurry, low quality, deformed, artifacts
```

### VAE 选型

| VAE | 适用场景 | 640×960 | >1000px | 备注 |
|-----|---------|---------|---------|------|
| `ae.safetensors` | 默认 | ✅ | ❌ 伪影 | MoodyZIT 专用 |
| `flux_ae.safetensors` | 备选 | ✅ | ⚠️ 颜色偏差 | Flux 原生 VAE |
| `ema_vae_fp16.safetensors` | 仅 SeedVR2 | - | - | 不可单独用于解码 |

### 文字渲染方案选型淘汰记录

| 方案 | 尝试 | 结果 | 结论 |
|------|------|------|------|
| Qwen-Image 融合 | MoodyZIT人物+Qwen文字→合成 | 色调/透视不匹配，融合度~70% | ❌ 淘汰 |
| MoodyZIT 直接文字 | 提示词中写文字描述 | 中英文均清晰 | ✅ 采用 |
| FluxText 插件 | 阿里场景文字编辑 | 需额外4个模型文件，未测试 | ⚠️ 备选 |
| ImageScale Lanczos | 640→1080 像素放大 | 零伪影 | ✅ 采用 |

### 模型选型淘汰记录（2026-06-18）

| 模型 | 测试 | 优势 | 淘汰原因 |
|------|------|------|---------|
| **Qwen-Image 2512** | 独立文生图 | 文字渲染🥇（远超MoodyZIT） | ❌ 人物质量差（"太丑"）、构图诡异 |
| **Qwen-Image 融合** | 双模型合成 | 理论上两者兼得 | ❌ 两个模型VAE/潜空间/色调完全不同，融合不自然 |
| **Qwen-Image Inpainting** | 局部重绘文字 | 可保留人物 | ❌ ControlNet模型补丁未下载 |
| **FluxText** | 场景文字编辑 | Flux原生兼容 | ⚠️ 需下载4个额外模型+自定义节点，未实际测试 |
| **FLUX.2** | 32B大模型 | 原生4K+强文字 | ❌ RTX 5070 12GB跑不动（需32GB+） |
| **直接 1152×1728** | 高分辨率生成 | 一步到位1080P | ❌ VAE伪影+地面幻觉 |
| **640×960 + Lanczos** | 原生+Lanczos | 20秒1080P | ✅ 当前最优 |

> **核心认知**：MoodyZIT（Z-Image-Turbo 6B）在 640×960 分辨率下是写实人像神器，文字、人物、地面全方位优秀。突破这个分辨率的任何尝试（换VAE、换超分、换模型）都会引入新的问题。**接受限制比强行突破更高效。**

### 最终推荐工作流

**1080P 快速出图**（推荐日常使用）：
```
UNETLoader(moodyRealMix_zitV7GlobalFP8)
CLIPLoader(qwen_3_4b, type=lumina2)
VAELoader(ae.safetensors)
LoraLoader(momoka-zib-v2_clean, strength=1.0)
ModelSamplingAuraFlow(shift=3.0)
EmptyLatentImage(640×960)
CLIPTextEncode(prompt + text + negative)
KSampler(20steps, dpmpp_2m_sde/sgm_uniform, cfg=1.0, seed=813972274184088)
VAEDecode
ImageScale(lanczos, 1080×1620)
SaveImage
```
> ⏱️ 约 20 秒/张 | 💾 ~8GB 显存

**4K 超分**（推荐日常使用）：
```
640×960 → KSamplerAdvanced(双程12步) → bislerp 1.8x → VAEDecodeTiled
→ [可选 CodeFormer(fidelity=0.75)] → SeedVR2(resolution=2560, tile=1024)
```
> ⏱️ 约 55 秒/张 | 💾 ~8GB 显存 | **CodeFormer 默认关闭**（LazySwitchKJ控制）

### CodeFormer 说明

**CodeFormer 默认关闭**。原因：CodeFormer在任意fidelity下都会显著提亮眼白、磨平虹膜纹理，产生"死鱼眼"效果。对MoodyZIT直接生成的已有好脸的面部是**负优化**。如需开启，将LazySwitchKJ节点的`switch`参数改为`true`。

---

## 十三、2026-06-18 追加：UI格式工作流踩坑、API格式迁移与图生提示词

### UI格式 vs API格式工作流（核心踩坑！）

**这是本次最大的坑。** ComfyUI工作流有两种JSON格式：

| 格式 | 参数传递方式 | 对参数顺序的敏感度 | 典型特征 |
|------|------------|------------------|---------|
| **UI格式** | `widgets_values` 数组，按位置匹配 | **极度敏感**，插件更新参数顺序即错位 | 有 `mode`, `color`, `widgets_values` 字段 |
| **API格式** | `inputs` 键值对，按名称匹配 | **完全不敏感**，顺序无关 | 只有 `class_type` + `inputs` |

**踩坑过程**：
1. SeedVR2插件从v2.5.x更新到v2.5.24，将 `color_correction` 参数从第6位移到第9位（`prepend_frames`之后）
2. 旧的UI格式工作流 `widgets_values` 数组仍按旧顺序排列，导致所有后续参数错位
3. 表现为连锁类型错误：`color_correction: 0 not in ['lab',...]`、`offload_device: False not in ['none','cpu','cuda:0']`、`latent_noise_scale, cpu, could not convert string to float: 'cpu'`、`batch_size: Value 0 smaller than min of 1`
4. 反复修改 `widgets_values` 顺序无效（ComfyUI可能缓存了旧参数）

**根因**：UI格式的位置参数天然脆弱，插件任何参数顺序变更都会导致错位。

**解决方案**：**全面迁移到API格式工作流**。API格式用命名参数（如 `"color_correction": "lab"`），按名称匹配，不受插件参数顺序变更影响。

**参考工作流为什么不报错**：`MoodyZIT_V7_写实人像_SeedVR2超分_CodeFormer面部增强.json` 本身就是API格式，所以不受影响。

### SeedVR2 插件 v2.5.24 参数顺序变更

**SeedVR2VideoUpscaler 当前参数顺序**（从插件源码 `video_upscaler.py` 确认）：

```
image, dit, vae, seed, resolution, max_resolution, batch_size,
uniform_batch_size, temporal_overlap, prepend_frames,
color_correction, input_noise_scale, latent_noise_scale,
offload_device, enable_debug
```

**SeedVR2LoadDiTModel 参数**：
```
model, device, blocks_to_swap, swap_io_components,
offload_device, cache_model, attention_mode
```
- `attention_mode` 可选值：`sdpa`, `flash_attn_2`, `flash_attn_3`, `sageattn_2`, `sageattn_3`
- **重要**：`cache_model=True` 时 `offload_device` 不能为 `"none"`，必须设为 `"cpu"` 或其他

**SeedVR2LoadVAEModel 参数**：
```
model, device, encode_tiled, encode_tile_size, encode_tile_overlap,
decode_tiled, decode_tile_size, decode_tile_overlap,
tile_debug, offload_device, cache_model
```
- `tile_debug` 必须是**字符串** `"false"`，不是布尔值 `false`

### SaveImage 路径变量踩坑

**现象**：`filename_prefix` 使用 `%date:yyyy-MM-dd%` 等Windows环境变量时，API模式提交报错 `[WinError 267] 目录名称无效`。

**原因**：ComfyUI API模式不会展开Windows环境变量，`%date%` 被当作字面目录名。

**解决**：使用简单前缀，如 `"filename_prefix": "ZIT-4K"`。

### 双程采样设计说明

当前工作流使用ZIT V7双程采样（Dual-pass sampling），**不需要传统负面提示词**：

| 参数 | Pass1 (KSamplerAdvanced) | Pass2 (KSamplerAdvanced) |
|------|-------------------------|-------------------------|
| steps | 9 | 9 |
| sampler | dpmpp_2m_sde | dpmpp_2m_sde |
| scheduler | beta | sgm_uniform |
| start_at_step | 0 | 4 |
| end_at_step | 7 | 999 |
| leftover_noise | enable | disable |
| 负面条件 | ConditioningZeroOut（归零向量） | 同左 |

`ConditioningZeroOut` 把正向条件向量归零作为负向条件，这是ZIT模型的训练方式。

### SageAttention 安装与兼容性

**RTX 5070 (Blackwell, SM 12.0) 兼容 SageAttention 2.2.0**：
- 需要 `triton-windows` + `sageattention` 两个包
- wheel命名规则：`sageattn-{version}+cu{cuda}torch{pytorch}-{python}-{os}.whl`
- 启动参数：`--use-sage-attention`（添加到 `start_comfyui.bat`）
- SeedVR2 的 `attention_mode` 设为 `sageattn_2` 可启用

### 批量执行策略

**分阶段执行避免模型反复装载卸载**：
- **阶段1**：Base图 + CodeFormer面部增强（所有提示词共用ZIT模型）
- **阶段2**：SeedVR2 4K超分（所有图片共用SeedVR2模型）
- 每个阶段只装载一次模型，大幅减少I/O开销

**显存监控**：
- GPU峰值：10.7-11.4GB（4K超分时）
- 12GB显存刚好够用，`blocks_to_swap=8` 是安全值
- `cache_model=True` 让模型常驻显存，避免反复加载

### JoyCaption 图生提示词

**插件**：`ComfyUI-JoyCaption`（通过 `comfyui-florence2` 插件加载）

**模型下载**：
- 模型名：`joycaption-beta-one`（约6-8GB）
- 放置路径：`models/LLM/llama-joycaption-beta-one/`
- 国内镜像：`https://hf-mirror.com` 或 `https://huggingface.erdda.com`
- 首次运行自动下载，也可手动下载

**12GB显存配置**：
- `memory_management`: `"Keep in Memory"` — 模型常驻显存，首次加载后后续秒出
- `quantization`: `"Balanced (8-bit)"` — 约8GB显存
- GGUF量化版（IQ4_XS, 4.48GB）可进一步降低显存和加速加载

**comfyui-florence2 插件真相**：
- 该插件的 `Florence2ModelLoader` 节点只支持 `llama-joycaption-beta-one` 模型
- **不支持**微软 Florence-2 小模型（0.7B）
- 底层用的是JoyCaption大模型，速度不会因"Florence"之名而变快

**预期耗时**：
- 首次加载（Keep in Memory）：约50-80秒
- 后续执行：数秒（模型已常驻显存）

### 当前可用工作流清单

| 工作流文件 | 格式 | 用途 | 状态 |
|-----------|------|------|------|
| `MoodyZIT_V7_双程采样_CodeFormer面部增强_SeedVR2_4K超分_API.json` | API | 生图+面部增强+4K超分 | ✅ 已验证 |
| `JoyCaption_图生提示词_API.json` | API | 参考图反推英文提示词 | ✅ 已验证 |
| `MoodyZIT_V7_写实人像_SeedVR2超分_CodeFormer面部增强.json` | API | 参考工作流（ZIB+ZIT双模型） | ✅ 只读参考 |

**已删除的工作流**：
- `MoodyZIT_V7_双程采样_CF_SeedVR2_4K_API.json` — 已重命名为上面的4K超分版本
- `MoodyZIT_V7_双程采样_CF_SeedVR2_4K_v2.json` — UI格式，参数错位，已删除
- `MoodyZIT_V7_双程采样_CodeFormer面部增强_SeedVR2_4K超分.json` — UI格式，参数错位，已删除

---

## 十、版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-18 | **追加章节十三**：UI格式vs API格式工作流踩坑（SeedVR2参数顺序错位）、双程采样设计说明、SaveImage路径变量、SageAttention兼容性、批量执行策略、JoyCaption图生提示词、comfyui-florence2插件真相 |
| 2026-06-18 | **深度测试章节**：分辨率踩坑（640×960为唯一最优）、文字渲染发现（中英文原生支持）、地面AI偏见修复、VAE选型对比、Qwen-Image方案淘汰、Lanczos 1080P方案确定 |
| 2026-06-17 | 新增 SageAttention 2 优化章节，显存降低 21-24%，SeedVR2 4K 超分成功执行 |
| 2026-06-16 | 补充 SeedVR2 踩坑：ComfyUI 版本过低导致加载失败（comfy_api.latest），附解决方法和来源 |
| 2026-06-14 | 升级至 ZIT V7 FP8，新增 SeedVR2 超分方案，删除全部 V6 旧工作流，重写本文档 |
| 2026-06-13 | 创建 V6 参考对齐版指南（已归档） |
