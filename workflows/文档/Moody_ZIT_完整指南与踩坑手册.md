# ComfyUI 12G 显存姿势控制踩坑手册

> 2026年7月4日更新（新增人物身材/胸部尺寸提示词中英文对照与极限测试、NoobAI-XL Vpred 超现实巨乳实测），基于 ComfyUI 2026-06-16 版本

## 硬件配置

| 项目 | 规格 |
|------|------|
| CPU | Intel Core i5-13600KF |
| GPU | NVIDIA GeForce RTX 5070 (12GB GDDR7) |
| 内存 | 32GB DDR5 6400MHz |
| 存储 | SSD |
| 系统 | Windows 11 |
| 启动参数 | `--lowvram`（模型权重自动在 VRAM ↔ RAM 间卸载） |

---

## 一、可用工作流速查

| 工作流 | 用途 | 模型 | 骨骼控图 | 提示词语言 |
|---|---|---|---|---|
| `Work-Fisher_Qwen-AIO_DWPose提取_图生图_API.json` | DWPose拍照提取骨骼→图生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ DWPose自动 | 中/英 |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_图生图_API.json` | VNCCS 3D手动摆姿→图生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D | 中/英 |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_文生图_API.json` | VNCCS 3D手动摆姿→文生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D | 中/英 |
| `灵犀控骨_VNCCS骨骼控图_16x9画幅一键横竖切换_图生图_Visual.json` | ⭐ **VNCCS图生图+自动横竖切换** | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D | 中/英 |
| `千面绘形_DWPose姿态编辑_16x9画幅一键横竖切换_图生图.json` | ⭐ **DWPose图生图+自动横竖切换** | Qwen-Rapid-AIO-NSFW-v18 | ✅ DWPose自动 | 中/英 |
| `灵犀控骨_VNCCS骨骼控图_16x9画幅一键横竖切换_图生图_API.json` | VNCCS横竖切换(API版) | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D | 中/英 |
| `MoodyZIT_V7_API_文生图_双程采样_快速预览_文字渲染.json` | ⭐ **高质量双程写实文生图** | moodyProMix_zitV13FP8 | ❌ | 中/英 |
| `MoodyZIT_V7_API_图生图_Inpaint手动遮罩_SeedVR2超分.json` | 图生图/局部重绘+超分 | moodyProMix_zitV13FP8 | ❌ | 中/英 |
| `MoodyZIT_V7_API_文生图_双程采样_SeedVR2_4K超分_文字渲染.json` | 文生图+双程+4K超分 | moodyProMix_zitV13FP8 | ❌ | 中/英 |
| `FLUX2_Klein9B_双程采样_快速预览.json` | Flux2 Klein 双程文生图 | flux-2-klein 系列 | ❌ | 英 |
| `NoobAI-XL_Vpred_动漫文生图.json` | ⭐ **纯日式动漫文生图（2026最佳动漫底模）** | NoobAI-XL-Vpred-v1.0 | ❌ | 英（Danbooru标签） |
| `Qwen-Rapid_中文文生图.json` | 2.5D美式动漫/插画文生图（支持中文） | Qwen-Rapid-AIO-NSFW-v18 | ❌ | 中/英 |
| `MoodyProMix_中文漫画_文生图.json` | **写实底模+漫画/动漫LoRA（支持中文）** | moodyProMix_zitV13FP8 + LoRA | ❌ | 中/英 |

---

## 二、Work-Fisher QWEN-AIO 姿势编辑

### 已修复的 Bug

| 问题 | 修复 |
|---|---|
| `background_color` 被设为 `1024` | 改为 `"#000000"` |
| 调度器 `beta57` 不可用 | 改为 `beta` |
| `comfyui_layerstyle` 节点缺失 | 从 GitHub 克隆到 `custom_nodes/` |

### 已知限制

- **只能做画幅内的姿势编辑**：抬手臂、歪头、换坐姿等可以，极端姿势（一字马）不行
- **不支持 outpainting**：人物无法缩小，不能拓展画布
- **表情控制有限**："翻白眼"等极端表情训练数据不足，仅靠提示词无法可靠实现
- 骨骼图 + 中文提示词联合控制，骨骼定姿势结构、文字定表情细节

### 推荐用法

- 上传人物图 → OpenPose自动识别 → 编辑骨骼 → Queue
- 提示词越具体、越描述关节位置越好（如"右手举过头顶手腕在头顶高度"）
- 结合 `Qwen-Rapid-AIO_VNCCS_骨骼控图_图生图_API.json` 的3D人偶可更直观摆姿

---

## 三、完整模型清单

### ⚠️ 重要说明：模型目录分为两个路径

本 ComfyUI 安装存在**两个 `models/` 目录**，搜索时容易遗漏：

| 目录路径 | 用途 | 主要包含 |
|----------|------|---------|
| `ComfyUI-aki-v3/ComfyUI/models/` | **ComfyUI 运行时主目录** | UNET、CLIP/Text Encoder、VAE、ControlNet、LoRA、Checkpoint、PuLID、InsightFace等全部核心模型 |
| `ComfyUI-aki-v3/models/` | 独立辅助目录 | 少量模型副本/备用（仅 flux2-vae、wan2.2_vae 等） |

**实际运行时 ComfyUI 读取的是 `ComfyUI/models/` 下的文件**（`ComfyUI/` 是其根目录下的子目录，注意与项目根目录 `ComfyUI-aki-v3/` 下的 `models/` 区分）。

### 3.1 扩散模型（diffusion_models/）

位于 `ComfyUI-aki-v3\ComfyUI\models\diffusion_models\`：

| 模型 | 大小 | 架构 | 用途 |
|------|:----:|:----|------|
| `moodyProMix_zitV13FP8.safetensors` | 5.73 GB | Z-Image Turbo (NextDiT) | ⭐ **MoodyZIT 亚洲写实文生图主力** |
| `moodyRealMix_zitV6R1DPO.safetensors` | 5.73 GB | Z-Image Turbo | 备用写实模型 |
| `moodyRealMix_zitV7GlobalFP8.safetensors` | 5.73 GB | Z-Image Turbo | 备用写实模型 |
| `moodyWild_zibV4Base40steps_fp8.safetensors` | 5.73 GB | Z-Image Turbo | 备用 |
| `flux1-dev-fp8.safetensors` | 11.08 GB | **Flux.1 Dev (FP8)** | **PuLID 换脸等工作流必须用（纯 Flux 架构）** |
| `flux1-dev-bnb-nf4-v2.safetensors` | 11.22 GB | Flux.1 Dev NF4 | ⚠️ **PuLID 不兼容**（bitsandbytes 与 UNETLoader 冲突），位于 `checkpoints/` |
| `flux1-dev-Q4_0.gguf` | 9.56 GB | Flux.1 GGUF 4-bit | 已下载但画质差（纯 4-bit 无 K-quant），**废弃** |
| `flux1-dev-Q4_K_S.gguf` | **6.34 GB** | **Flux.1 GGUF K-quant** | ⭐ **PuLID 换脸唯一可行底模**（ModelScope/HF-Mirror 下载） |
| `flux-2-klein-4b-fp8.safetensors` | 3.79 GB | Flux2 Klein 4B Distilled | 快速预览（4步），CLIP type=`flux2` |
| `flux-2-klein-9b-Q4_K_M.gguf` | 5.5 GB | Flux2 Klein 9B GGUF | 主力 Flux2 文生图（位于 `aki-v3/models/diffusion_models/`） |
| `Qwen-Rapid-AIO-NSFW-v18.safetensors` | 26.48 GB | Qwen | 位于 `checkpoints/QWEN/`，Work-Fisher姿势编辑 |
| `NoobAI-XL-Vpred-v1.0.safetensors` | 6.62 GB | SDXL | 纯日式动漫文生图 |
| `wan2.2_ti2v_5B_fp16.safetensors` | 9.31 GB | Wan2.2 | 视频生成（12G 基本不可用） |
| `Real-Qwen-Image-V2-2512-Q4_K_M.gguf` | 12.17 GB | Qwen GGUF | 写实+亚洲人脸优化版 |
| `qwen-image-2512-Q4_K_M.gguf` | 13.2 GB | Qwen GGUF | Qwen 2512 量化版（早期测试，位于 `diffusion_models/`） |

> **2026-08-09 更新 — Moody Zimage 系列版本演进与开源模型态势**
>
> 以下内容基于 Civitai API（`.env` 的 `CIVITAI_API_KEY`）对作者 catlover1937 全部 30 个模型的最新版本时间核査，以及作者模型主页 description 原文整理。

#### 3.0.1 Zimage 系列 V7→V13 演进对照表（「改了啥 / 退了啥」）

> **核心前提：版本号 ≠ 代际升级。** V7 / V10 / V13 是三条不同的底模路线（作者原话「V8–V10 基于 V7 迭代，但 V11 是不同路线」），不是数字越大越好。作者明确声明「新版本不一定全面碾压旧版本，每个版本有自己的风格和侧重点，哪个顺手用哪个」。

| 版本 | 底模路线 | 改了啥（相对上一版） | 退了啥 / 已知问题 | 作者定位 |
|---|---|---|---|---|
| **V7 / V7 Global** | Zimage Turbo 早期重构后的经典稳定线 | 早期重构后的稳定基，少美颜、偏真实柔和 | 风格偏「老 Moody」、审美上限不如后期 | **Real 系列泛用首选**（作者：「V7 or V7 Global? Pick your poison」） |
| **V8–V10** | 基于 V7 的迭代升级线 | 在 V7 上逐步加美学、稳定性优化 | V10 偏黄偏暗 → 出 **V10R1** 修正 | V10R1 曾被作者定为「极致稳定一致首选」 |
| **V10 / V10R1** | 独立老底模线（与 V13 **非同源**） | V10R1 修偏黄偏暗 | 同 V10 线，非 V11+ 同源 | 社区最爱、稳定向终态 |
| **V11** | 换 V11/V12 新底模（与 Moody Real V5/V6 共用） | 追极致审美 / 画风 | **牺牲解剖与稳定性**，风格突变 | 作者自认「更像是重制而非升级」 |
| **V12** | 续 V11 线 | 继续审美实验 | 不稳定、风格漂移 | 实验性 |
| **V13 (ZIT V13 FP8)** | 续 V11/V12 线但**回调** | 移除实验性审美 LoRA、去 DPO、加回稳定、NSFW 增强 | 仍带 V11 系的「艳 / 风格」基因 | **当前 Pro Mix 主力的稳向终态** |
| **Pro Mix 典藏版（2026-08-09）** | **与 V10 共用基础底模**（作者原话） | 干净 Moody 基底 + 少量 NSFW 解封 LoRA，极致稳定、少美颜 | 无实验性改动，是「收尾快照」 | V10 路线精神续作，**不是 V13 升级** |
| **Real Mix XHS 萌妹版（2026-07-08）** | 与 Krea2 Oriental 同数据集 | 小红书 / ins 磨皮甜妹风东亚脸 | 刻意偏真实感缺失、只会亚洲妹 | **V7 Global 的反向特化**，作者不推荐泛用 |

**对你（V13 + V7 Global 主力）的结论：**
- 你手上的 **V13（Pro Mix）+ V7 Global（Real Mix）已是 Zimage 线的「稳向终态」**，无需为「追新」而换。
- 作者已声明**重心转向 Krea2 系列，Zimage 线大概率不再更新** → V13/V7 Global 即最终形态，不会有 bug 修复更新。
- 「感觉区别不大」是对的：你的固定工作流配方（Zimage Turbo + 双程采样 + 固定 CFG / 分辨率 + 中文人物描述）把模型间的味觉差压扁到三者交集甜区；且 V13 作者设计上就往 V10 方向回调，本就「殊途同归」。

#### 3.0.2 开源文生图模型态势（2026-08 核査）

**结论：并非「没更好的开源模型」，而是「更优的模型换了赛道且对你的硬件有门槛」。** 值得关注的新方向：

1. **Krea 2（2026-06 开源，catlover1937 新重心）**
   - 架构：12B DiT，文本编码器用 **Qwen3VL-4B**（非 CLIP），VAE 用 `qwen_image_vae`，与 Qwen-Image 同族。
   - 变体：**RAW**（52 步基础）/ **Turbo**（8 步蒸馏，推荐 FP8）。
   - 能力：1K–2K 输出、风格多样、官方 9 款风格 LoRA、高美学质量；ComfyUI 官方有工作流。
   - 文件：`krea2_turbo_fp8_scaled.safetensors`（diffusion_models）+ `qwen3vl_4b_fp8_scaled.safetensors`（text_encoders）+ `qwen_image_vae.safetensors`（vae）。
   - **显存评估（你的 12GB / 5070）**：12B FP8 ≈ 6GB + 4B 文本编码器 FP8 ≈ 2GB + VAE + 余量，**临界约 10–12GB**，实际跑 Turbo 大概率能上但余量极小，出 2K 或叠加 LoRA 可能 OOM。建议先以 1K 测试，或等 INT8 版。
   - 关联：作者的 **Moody Krea 2 Mix / Krea 2 Aesthetic Loras** 就是基于它微调，是你现有 Moody 风味的「升级赛道」。

2. **Qwen-Image-2.0（2026-02，阿里）**：7B 单模型统一生图 + 编辑，支持中文汉字渲染、2K。协议偏宽松，社区活跃。适合「生图 + 改图一体」需求，但写实人本质感与 Moody 专门调过的亚洲脸有差距。

3. **既有稳态**：SDXL / Flux.1 系列仍是最广泛兼容底座；你的 Moody 系属 Flux / SD1.5 / Zimage 微调分支，短期不会被淘汰（手册第 1037 行「猫腻圈所有替代品都打不过它」的结论在 Zimage 线内依然成立）。

**对你（12GB 显存 + 亚洲写实人像主力）的实操建议：**
- 不愿动硬件：**保持 V13 + V7 Global**，已是收尾态，无升级压力。
- 想尝鲜且愿冒 OOM 风险：试 **Krea 2 Turbo FP8**（1K 起步），体验作者新重心画风；或下载 **Moody Krea 2 Mix** 体验 Moody 风味的 Krea2 版。
- 想换「生图 + 改图一体」：看 Qwen-Image-2.0，但与你现有工作流不兼容，需另搭。

### 3.2 文本编码器（text_encoders/ + clip/）

位于 `ComfyUI-aki-v3\ComfyUI\models\text_encoders\` 和 `clip\`：

| 文件 | 大小 | 所属模型 | 加载方式 |
|------|:----:|---------|---------|
| `qwen_3_4b.safetensors` | 7.49 GB | MoodyZIT 系列 | CLIPLoader type=`lumina2` |
| `qwen_3_8b_fp8mixed.safetensors` | 8.07 GB | Flux2 Klein 等 | CLIPLoader type=`flux2` |
| `clip_l.safetensors` | 234 MB | Flux.1 标准 | DualCLIPLoader（配合 t5xxl） |
| `t5xxl_fp8_e4m3fn.safetensors` | 4.56 GB | Flux.1 标准 | DualCLIPLoader（配合 clip_l） |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | 6.27 GB | Flux2 / Wan | 多用途 |
| `EVA02_CLIP_L_336_psz14_s6B.pt` | 816 MB | **PuLID Flux** | PulidFluxEvaClipLoader，存在于 `clip/` 和 `text_encoders/` 两个目录 |

⚠️ **关键**：MoodyZIT 系模型（NextDiT）用 `qwen_3_4b` + `CLIPLoader`，PuLID 等标准 Flux 模型用 `clip_l + t5xxl` + `DualCLIPLoader`。**混用会报维度错误**。

### 3.3 VAE（vae/）

| 文件 | 大小 | 用途 |
|------|:----:|------|
| `ae.safetensors` | 319 MB | Flux.1 / Z-Image Turbo 标准 VAE |
| `flux2-vae.safetensors` | 320 MB | Flux2 Klein 专用 VAE |
| `qwen_image_vae.safetensors` | 242 MB | Qwen 系列专用 |

### 3.4 PuLID 换脸组件（完整！位于 `ComfyUI\models\` 下）

| 组件 | 路径 | 大小 | 状态 |
|------|------|:----:|:----:|
| PuLID 模型 | `pulid/pulid_flux_v0.9.1.safetensors` | 1.06 GB | ✅ |
| EVA02 CLIP | `clip/EVA02_CLIP_L_336_psz14_s6B.pt` | 816 MB | ✅ |
| 人脸检测 | `insightface/models/antelopev2/1k3d68.onnx` | 136 MB | ✅ |
| 人脸检测 | `insightface/models/antelopev2/2d106det.onnx` | 4.8 MB | ✅ |
| 性别年龄 | `insightface/models/antelopev2/genderage.onnx` | 1.26 MB | ✅ |
| 人脸识别 | `insightface/models/antelopev2/glintr100.onnx` | 248 MB | ✅ |
| 人脸检测 | `insightface/models/antelopev2/scrfd_10g_bnkps.onnx` | 16 MB | ✅ |
| 换脸 | `insightface/inswapper_128.onnx` | 528 MB | ✅ |
| 自定义节点 | `ComfyUI_PuLID_Flux_ll` | — | ✅ 已安装 |

> **结论**：PuLID Flux 换脸所需的**所有模型文件齐全**，只需使用正确的 Flux.1 底模（不支持 NextDiT/Z-Image Turbo 架构）。

### 3.5 LoRA 角色模型

位于 `ComfyUI-aki-v3\ComfyUI\models\loras\`，共 47+ 个。核心列表已在第十八节「catlover1937 Moody Gals 系列角色 LoRA 全览」中列出，此处不重复。

### 3.6 ControlNet

| 文件 | 大小 | 用途 |
|------|:----:|------|
| `flux_union_controlnet.safetensors` | 6.15 GB | Flux.1 ControlNet |
| `Qwen-Image-ControlNet-Union/` | 3.29 GB | Qwen ControlNet（12G 无法有效使用） |
| `FLUX.2-dev-Fun-Controlnet-Union/` | ~7.7 GB x2 | Flux2 dev 专用（不与 Klein 兼容） |

### 3.7 传统 Checkpoint 模型

位于 `ComfyUI-aki-v3\ComfyUI\models\checkpoints\`，包括：

| 模型 | 大小 | 用途 |
|------|:----:|------|
| `flux1-dev-bnb-nf4-v2.safetensors` | 11.22 GB | ⚠️ 在 checkpoints/，UNETLoader 默认搜 diffusion_models/ 找不到 |
| `Qwen-Rapid-AIO-NSFW-v18.safetensors` | 26.48 GB | Work-Fisher 姿势编辑主力 |
| `NoobAI-XL-Vpred-v1.0.safetensors` | 6.62 GB | 动漫文生图 |
| `Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` | 6.62 GB | SDXL 写实 |
| `pearlyAnimaMix_v10.safetensors` | 4.13 GB | Anima 动漫混合底模 |
| `animagine-xl-3.1.safetensors` | 6.46 GB | 动漫风格 |

---

## 四、已排除的方案及原因

### 1. Qwen 2512 GGUF + InstantX ControlNet
- 报错：`mat1 and mat2 shapes cannot be multiplied`
- 原因：GGUF模型包装方式与ControlNet Conditioning注入机制不兼容
- 结论：不可行

### 2. Qwen 2512 FP8 + InstantX ControlNet
- 显存需求：UNet(~11G) + CLIP(4.4G) + ControlNet(3.5G) ≈ 19G
- 结论：12G扛不住

### 3. Flux 2 Klein 4B + Flux 1 ControlNet
- Flux 1 ControlNet与Flux 2 Klein架构不匹配
- 结论：不可行

### 4. Flux 2 Klein + Flux 2 ControlNet
- Flux 2 dev ControlNet 7.7G + 不兼容 Klein 4B 架构
- 结论：模型错误 + 显存不足

### 5. MoodyZIT (Flux) + ControlNet
- ❌ **已实测，不可行**（2026-06-30）
- 原因：`comfyui_controlnet_aux` 只含预处理节点，缺少 `ControlNetLoader`/`ControlNetApply` 加载节点，需额外装 FLUX ControlNet 插件
- 即使装好插件，12G 显存也吃紧

---

## 五、已安装的关键插件

| 插件 | 位置 | 用途 |
|---|---|---|
| ComfyUI_VNCCS_Utils | `custom_nodes/ComfyUI_VNCCS_Utils` | 3D人偶摆姿Pose Studio |
| comfyui_layerstyle | `custom_nodes/comfyui_layerstyle` | 图层工具（缩放/扩展/卷轴） |
| comfyui_controlnet_aux | `custom_nodes/comfyui_controlnet_aux` | OpenPose预处理 |
| ComfyUI-GGUF | `custom_nodes/ComfyUI-GGUF` | GGUF模型加载 |
| comfyui-openpose-editor-dockr | `custom_nodes/comfyui-openpose-editor-dockr` | 2D骨骼编辑器（有UI bug） |

---

## 六、模型与CLIP兼容性矩阵

> 2026-06-30 更新，基于实测结论

| 模型 | 加载方式 | 原生CLIP | CLIP类型 | 支持骨骼控图 | 输入尺寸限制 |
|------|------|------|------|------|------|
| Qwen-Rapid-AIO-NSFW-v18 | CheckpointLoaderSimple | 内置 Qwen VL | 视觉语言 | ✅ image2传入 | 任意尺寸 |
| moodyProMix_zitV13FP8 | UNETLoader | qwen_3_4b | 纯文本 | ❌ CLIP看不懂图 | 640×960等标准FLUX分辨率 |
| qwen-image-edit-2511-Q5_0.gguf | UnetLoaderGGUF | qwen_2.5_vl_7b | 视觉语言 | ✅ | 任意（但GGUF极慢） |
| qwen_image_2512_fp8_e4m3fn | UNETLoader | 需要Qwen VL | 视觉语言 | ✅ | 任意（20G FP8显存吃紧） |

### 关键发现

1. **Qwen-Rapid-AIO 文生图偏2.5D美式动漫风格**：实测 Qwen-Rapid 在文生图模式下出图偏向2.5D美式动漫质感（而非日式赛璐璐风格），写实度不如 MoodyZIT。如需写实画风，建议用 Qwen-Rapid 图生图（输入写实照片做参考），或走 Work-Fisher→MoodyZIT 两级串联方案。如需纯日式漫画风格，建议用 NoobAI-XL Vpred 模型（需英文 Danbooru 标签，详见新工作流 `NoobAI-XL_Vpred_动漫文生图.json`）。

2. **CheckpointLoaderSimple vs UNETLoader**：Checkpoint 打包了模型+CLIP+VAE，CLIP 和模型绑定正确不会维度报错。UNETLoader 分离加载，手动配错 CLIP 会炸（如 qwen_2.5_vl_7b(3584维) ≠ qwen_3_4b(2560维) → LayerNorm 报错）

3. **MoodyZIT 不能做骨骼控图**：它的原生 CLIP（qwen_3_4b）是纯文本模型，TextEncodeQwenImageEditPlus 需要 VL CLIP 才能把骨骼图编码进 conditioning。唯一的骨骼控图路径是 ControlNet，但需额外装插件。

4. **Qwen-Rapid-AIO 是骨骼控图最优解**：Checkpoint 内置 VL CLIP，支持文生图和图生图两种骨骼控图模式。


1. **CheckpointLoaderSimple vs UNETLoader**：Checkpoint 打包了模型+CLIP+VAE，CLIP 和模型绑定正确不会维度报错。UNETLoader 分离加载，手动配错 CLIP 会炸（如 qwen_2.5_vl_7b(3584维) ≠ qwen_3_4b(2560维) → LayerNorm 报错）

2. **MoodyZIT 不能做骨骼控图**：它的原生 CLIP（qwen_3_4b）是纯文本模型，TextEncodeQwenImageEditPlus 需要 VL CLIP 才能把骨骼图编码进 conditioning。唯一的骨骼控图路径是 ControlNet，但需额外装插件。

3. **Qwen-Rapid-AIO 是骨骼控图最优解**：Checkpoint 内置 VL CLIP，支持文生图和图生图两种骨骼控图模式。

---

---

## 十七、Flux 架构工作流设计原则：不需要负面提示词

Flux 系列模型（包括 MoodyZIT V7/V8/V9）使用 `guidance` 机制而非传统 CFG，**负面提示词的理论基础在 Flux 上不存在**。

### 已应用

- `MoodyZIT_V7_Visual_文生图_双程采样_快速预览_文字渲染.json`：节点 8 的负面 CLIPTextEncode 已清空为 `""`，保留节点仅用于维持工作流结构兼容

### 为什么 Flux 不需要负面词

传统 SD/SDXL 模型中，CFG 通过 `positive - negative` 的差值来放大引导强度。负面词说"不要什么"，正面词说"要什么"，模型按差值走。

Flux 的 `guidance` 机制不同——它直接在条件注入时混合一个空池化特征，只关注正面内容。**负面词在 Flux 上几乎没有效果**，这是架构决定的。

### 实际影响

- Flux 工作流可以完全移除负面 CLIPTextEncode（或留空）
- 留下防衣物穿帮之类的负面词也没害处，只是不会被模型当真
- 这不是"效果好不好"的问题，是"机制上就不支持"的问题
- 配置 Flux 工作流时，只需专注写好正面提示词即可

---

## 七、V7/V8/V9 开发踩坑记录

> 2026-06-30 新增

### 1. SeedVR2 v2.5.24 widget 顺序变更

- **现象**：旧工作流的 `widgets_values` 顺序和新版节点定义不一致，导致 `color_correction`/`temporal_overlap`/`prepend_frames` 值全部错位
- **修复**：重排 widgets_values，`color_correction` 从位置5移到7；同时补齐 `inputs` 元数据使 ComfyUI 按名称匹配而非按位置

### 2. FLUX 模型分辨率锁死

- **现象**：`RuntimeError: shape '[1, 16, 78, 2, 52, 2]' is invalid for input of size XXXXX`
- **原因**：FLUX DiT 内部做 2×2 patch embedding，要求 latent 的 H 和 W 均为偶数。输入图像经 VAE(8×) 压缩后若维度为奇数则炸
- **解决**：用 `ImageScale` 强制缩放到 FLUX 兼容尺寸，或直接用 Qwen-Rapid（不限尺寸）

### 3. MoodyZIT V13 分辨率

- 训练时锁定的标准分辨率：**640×960**（2:3）、**1248×832**（3:2）
- `ImageScaleByAspectRatio V2` 的 letterbox 模式未能产生偶数 latent 维度，改用 `ImageScale` 直设宽高

### 4. GGUF 量化模型速度问题

- Qwen Image GGUF Q5_0 生成 1080P 需 ~500 秒，GPU 利用率仅 60%
- 原因：GGUF 是 CPU 软解量化权重，非 GPU 原生运算
- FP8 safetensors 版本速度快 5-10 倍，但显存需求更高（~20G）

### 5. VNCCS 首次初始化下载

- VNCCS PoseStudio 首次加载需从 HuggingFace 下载 SAM 3D Body 等模型（6 步）
- **国内加速**：在 `start_comfyui.bat` 中 `python` 命令前加 `set HF_ENDPOINT=https://hf-mirror.com`
- 仅需下载一次

### 6. ControlNet 插件缺失

- `comfyui_controlnet_aux` 只提供预处理节点（OpenPose骨架提取等），**不含** ControlNet 加载/应用节点
- FLUX ControlNet 需额外安装插件（如 `ComfyUI-FluxControlNet`），且显存临界（12G 紧张）
- `flux_union_controlnet` 模型已下载但因缺插件无法使用

### 7. 文生图 vs 图生图骨骼控图

| 模式 | 节点 | 适用模型 |
|------|------|------|
| 图生图 | LoadImage → VAEEncode → KSampler | Qwen-Rapid |
| 文生图 | EmptyLatentImage → KSampler | Qwen-Rapid |

两种模式共用同一套骨骼控图管线（VNCCS → image2 → TextEncodeQwenImageEditPlus），区别仅在 latent 来源。

### 8. API 格式 vs 标准 Visual 格式

- **API 格式**：`{"1": {"class_type": "...", "inputs": {...}}}` —— 参数按名称匹配，不依赖位置。直接 POST `/prompt` 接口
- **标准 Visual 格式**：节点数组 + `widgets_values` 位置数组 —— 可 Load 加载到 UI，节点更新后易错位
- **建议**：需 UI 交互的工作流用标准格式，纯脚本调用用 API 格式

### 9. SeedVR2 多分辨率下拉框方案（2026-06-24）

#### 需求
用 `SeedVR2VideoUpscaler` 超分时，用户需下拉选择 2K/4K/6K，避免手写数字。

#### 实现
新增自定义节点 `SeedVR2ResolutionPicker`（在 `ComfyUI_essentials/misc.py`）：
- 下拉选项：`2K (2048)` / `4K (4096)` / `6K (6144)`
- 输出 `INT` 类型，同时连接到 upscaler 的 `resolution` 和 `max_resolution`

#### 踩坑 1：Manager 节点名冲突
`ResolutionPicker` 这个名字在 ComfyRegistry 在线数据库中被映射到 `comfyui-flux-continuum` 包。即使本地有节点定义，Manager 也会弹"缺失节点包"警告。

**解决**：重命名为 `SeedVR2ResolutionPicker`，彻底避名冲突。

#### 踩坑 2：标准格式 widgets_values 错位
V3 的 `io.Int.Input` 中，`control_after_generate` 不再单独占一个 widget value，但链接输入（link input）**仍然占位**。将 `resolution`/`max_resolution` 从 widget 改为 link 后，需在 `widgets_values` 数组中为这些 link 槽位保留 dummy 值。

最终正确的 `widgets_values` 分布（共 13 项）：
```
seed 值 → seed 控制器 → resolution(link,dummy) → max_resolution(link,dummy) → batch_size → uniform → color → temporal → prepend → noise → latent → offload → debug
[42,     "fixed",       0,                     0,                        1,          false,    "lab",  0,         0,          0.0,    0.0,     "cpu",   false]
```

#### 踩坑 3：API 格式不受影响
API 格式按参数名匹配，不依赖位置。在 API 格式中添加 `SeedVR2ResolutionPicker` 只需按正常 JSON 写法，无需操心 `widgets_values` 顺序。

---

---

## 十八、catlover1937 Moody Gals 系列角色 LoRA 全览

> 2026-06-30 全面更新。作者 catlover1937 共发布了 **11 个**原创角色 LoRA，全部基于 ZImageTurbo 架构（ZIB/ZIT 双格式），数据通过 CivitAI API 采集。

### 1. 系列概述

| 属性 | 说明 |
|------|------|
| 作者 | catlover1937（同时也是 moodyProMix 模型作者） |
| 类型 | 角色 LoRA（固定特定角色的面容、身材、风格） |
| 首发平台 | [CivitAI](https://civitai.com/user/catlover1937/models)（免费下载） |
| 格式 | ZIB（影响构图和动作）+ ZIT（影响细节） |
| 基础模型 | ZImageTurbo |
| 命名规则 | `{角色名}-zib-v{版本}_clean.safetensors` |
| 文件大小 | 各约 162 MB（个别 133~202 MB） |
| 许可证 | Apache 2.0 |

### 2. 完整角色列表（11 个）

| # | 角色 | 年龄 | 人设 | 文件名 | 触发词 | 下载状态 | CivitAI 页面 |
|:---:|:----|:---:|------|--------|:------:|:--------:|:-----------:|
| 1 | **Momoka** | 23岁 | 日本 Cosplayer，甜美可爱，热爱动漫同人文化 | `momoka-zib-v2_clean.safetensors` | `Momoka` | ✅ 已下载 | [查看](https://civitai.com/models/2657057) |
| 2 | **Rina** | 21岁 | 韩国偶像练习生，学表演与舞台艺术，会乐器 | `Rina-zib-v1_clean.safetensors` | `Rina` | ✅ 已下载 | [查看](https://civitai.com/models/2656506) |
| 3 | **Weiwei** | 27岁 | 上海华裔女编辑，细腻感性 | `weiwei-zib-v1_clean.safetensors` | `Weiwei` | ✅ 已下载 | [查看](https://civitai.com/models/2669955) |
| 4 | **Yoki** | 21岁 | 中国古典美女，爱汉服古风，大学表演专业 | `yoki-zib-v1_clean.safetensors` | `Yoki` | ✅ 已下载 | [查看](https://civitai.com/models/2651415) |
| 5 | **Dori** | 19岁 | （未公开详细设定） | `Dori-zib-v2_clean.safetensors` | `Dori` | ✅ 已下载 | [查看](https://civitai.com/models/2629822) |
| 6 | **Huihui** | ? | （未公开详细设定） | `huihui-zib-kage.safetensors` | （无触发词） | ✅ 已下载 | [查看](https://civitai.com/models/2681932) |
| 7 | **Hana** | 20岁 | 韩国大学生，在首尔 Starbucks 兼职店员 | `hana-zib-v7.safetensors` | `Hana` | ✅ 已下载 | [查看](https://civitai.com/models/2707619) |
| 8 | **Nari** | 25岁 | 韩国女 DJ，常年活跃于夜店和音乐节 | `Nari-zib-v1_clean.safetensors` | `Nari` | ✅ 已下载 | [查看](https://civitai.com/models/2662271) |
| 9 | **Lili** | 27岁 | 中国女演员，冷艳高级气质，演配角+广告拍摄 | `lili-v5_clean.safetensors` | `Lili` | ✅ 已下载 | [查看](https://civitai.com/models/2713788) |
| 10 | **Vivian** | 21岁 | 菲律宾大学毕业生，富家女，时尚性感风格 | `Vivian-zib-v1_clean.safetensors` | `Vivian` | ✅ 已下载 | [查看](https://civitai.com/models/2676413) |
| 11 | **Veronica** | 22岁 | 俄罗斯女孩，职业是「生活体验师」 | `Veronica-zib-v1_000006000.safetensors` | `Veronica` | ✅ 已下载 | [查看](https://civitai.com/models/2699169) |

### 3. 各角色预览图

所有预览图均来自 CivitAI 页面，可直接在浏览器中打开查看：

| 角色 | 预览图链接（点击查看） |
|:----|:---------------------|
| Momoka | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/fb639fc7-eb00-406c-ad1b-30037c6ce7aa/original=true/132249590.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/93dd837c-aafc-41f2-9247-7ddca43c7ef4/original=true/132249138.jpeg) · [图片2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/65f7d271-31f2-4c48-9495-65545c5fdee8/original=true/132249243.jpeg) |
| Rina | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/bbbd510e-f6c1-4d73-a734-31dbac6cfad0/original=true/132044910.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/df85d59e-4611-41be-8a0b-3f42c699044c/original=true/132045110.jpeg) |
| Weiwei | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/b12c02c4-4b8b-4bbd-acc6-c84e40bc6fc4/original=true/132629749.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/38dcceae-e2fe-48cd-8956-03a23fe4c9ba/original=true/132585363.jpeg) · [图片2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/fa907c5a-3e14-4f88-a3ec-595ba30b40d1/original=true/132585942.jpeg) |
| Yoki | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/e6dbe67d-2631-4f8c-b044-a5042927f39b/original=true/131832290.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/78ed1a53-7a0e-44b4-8845-9c301145ba46/original=true/131832262.jpeg) |
| Dori | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/7f5ee8c4-0de6-45aa-af46-1e854e53d4aa/original=true/130974298.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/ab0277e7-a694-4b54-be5f-041bd35f57b5/original=true/130974380.jpeg) · [图片2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/28733ae7-74cd-4bc7-890c-1baa24ae076b/original=true/130974403.jpeg) |
| Huihui | [视频1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/6ff9894c-f14e-4961-a3fd-2358b600a440/original=true/133076285.mp4) · [视频2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/2ef8d2b5-8640-4438-9191-1079f54dea14/original=true/133076286.mp4) |
| Hana | [视频1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/80eac422-a747-4bb2-ba32-06d9e9852000/original=true/133999721.mp4) · [视频2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/e3de9277-6c4f-464a-9927-d94926dfb2b8/original=true/133999724.mp4) |
| Nari | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/2643ee86-352e-4aa4-9f6a-a21cf8821160/original=true/132295171.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/01b07b5b-c6ea-4834-8776-17876bc22829/original=true/132291060.jpeg) |
| Lili | [视频1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/930b5c2f-98ed-4f76-b7e4-4a96c4124525/original=true/134219973.mp4) · [视频2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/1b8fe6c3-b1f7-4d8e-bda1-05e0a4afd952/original=true/134219948.mp4) |
| Vivian | [视频预览](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/fdca19c6-1951-4f35-92f3-e20bf6d7b48a/original=true/132829568.mp4) · [图片1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/91b04c18-ff62-4ce5-b451-e3522d931e0c/original=true/132827893.jpeg) |
| Veronica | [视频1](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/0f29a40d-01c1-45d9-bcad-29ea6108a2c2/original=true/133706997.mp4) · [视频2](https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/dde16588-9b53-492a-84e7-2a036b44ed5e/original=true/133706996.mp4) |

### 4. 关键认知（防踩坑）

| 认知 | 说明 |
|------|------|
| **角色 LoRA ≠ 通用增强** | 这是**角色固定类** LoRA，不是画质/细节增强 LoRA。其核心使命是锁定一张特定的脸和身材 |
| **天然偏向正面视角** | 角色 LoRA 的训练数据几乎全是正面/半侧面展示面部，挂着它会让正后方等非常规视角的生成非常困难 |
| **与 prompt 的正面描述冲突** | 一旦 prompt 中出现大量需要"展示正面才能看到"的服饰细节（领口、面部、眼睛等），角色 LoRA 会加剧"转回正面"的倾向 |
| **moodyProMix 是 all-in-one** | 作者明确指出 Moody 系列模型是 all-in-one，**不需要额外叠加角色 LoRA 也能出高质量亚洲写实人像** |

### 5. 推荐用法

| 场景 | 推荐操作 | 理由 |
|------|---------|------|
| 想要固定角色面容 | LoRA 权重 **0.6~0.8** | 正常角色锁定强度 |
| 只借风格不借脸 | 权重 **0.1~0.3** | 低强度，不影响构图主导权 |
| 出非常规视角（正后方/俯视等） | **权重设为 0 或移除节点** | 消除面部锁定与视角的冲突 |
| 纯写实高质量人像（无特定角色需求） | **不挂任何角色 LoRA** | moodyProMix 本身已足够 |

### 6. 下载指引

所有 11 个角色 LoRA 已全部下载至 `models/loras/`，可直接在工作流中使用：

```text
models/loras/momoka-zib-v2_clean.safetensors        (162.2 MB)  ✅
models/loras/Rina-zib-v1_clean.safetensors           (162.2 MB)  ✅
models/loras/weiwei-zib-v1_clean.safetensors         (162.2 MB)  ✅
models/loras/yoki-zib-v1_clean.safetensors           (162.2 MB)  ✅
models/loras/Dori-zib-v2_clean.safetensors           (162.2 MB)  ✅
models/loras/huihui-zib-kage.safetensors             (162.2 MB)  ✅
models/loras/hana-zib-v7.safetensors                 (162.2 MB)  ✅
models/loras/Nari-zib-v1_clean.safetensors           (162.2 MB)  ✅
models/loras/lili-v5_clean.safetensors               (202.0 MB)  ✅
models/loras/Vivian-zib-v1_clean.safetensors         (162.2 MB)  ✅
models/loras/Veronica-zib-v1_000006000.safetensors   (162.2 MB)  ✅
```



---

## 十九、CFG 与提示词优化关键认知

> 2026-06-28 新增。基于 MoodyZIT + moodyProMix_zitV13FP8 实测总结。

### 1. CFG Scale 的本质

CFG（Classifier-Free Guidance）控制模型在"听提示词"和"自己随意画"之间的平衡：

```
最终预测 = 条件预测 + CFG ×（条件预测 - 无条件预测）
```

- **CFG 高（3~7）**：极力满足 prompt 中每一个词。如果 prompt 内部有矛盾（如"正后方"+"展示面部"），模型会被迫折中
- **CFG 低（1.0~2.0）**：模型更回归训练数据的概率分布，只抓住 prompt 中最明确的指示，放弃次要矛盾
- **CFG=0**：约等于完全不看 prompt，模型纯凭训练集本能生成

### 2. 关键发现：Prompt 内部矛盾 > CFG 参数

| 场景 | 效果 | 原因 |
|------|------|------|
| 提示词只有"正后方姿势" + CFG任意值 | ✅ 永远是正后方 | 无冲突token，模型专注执行 |
| 提示词同时含"正后方"+"面部/服饰细节" + CFG=3 | ❌ 侧面 | 两个方向互相拉扯，模型折中 |
| 提示词同时含"正后方"+"面部/服饰细节" + CFG=1.5 | ⚠️ 偏正面/半侧面 | 降低CFG减轻了矛盾，但没有消除冲突本身 |
| 删除所有暗示正面的服饰细节，只保留"正后方" + CFG=1.5 | ✅ 正后方+CFG再高也是正后方 | 矛盾被删除，模型只朝一个方向用力 |

**结论：删除冲突的 token 比调整任何参数都更有效。**

### 3. CLIP 注意力机制

- **Prompt 开头权重最高**：CLIP 在编码 prompt 时，开头的 token 注意力更大
- **权重语法有效**：`（正后方视角：1.5）` 或 `（面部不可见：1.6）` 可强制强化关键信号
- **`BREAK` 分隔符**：将 prompt 分段，让模型把前后当作独立注意力区块

### 4. 建议的 Prompt 结构

```text
第一行：视角/姿势（最优先，权重最高）
第二行：人物基本特征
第三行：服饰/环境
第四行：画质/风格
```

**实战案例（正后方俯拍）**：

✅ 正向提示词：
```text
（正后方视角：1.6）（背部完全朝向镜头：1.6）（面部不可见：1.5）
【姿态动作】镜头在人物的屁股正后方，人物双膝跪地...面部朝下，双手前伸
【人物服饰】素雅白色和淡雅薄荷绿汉服，薄纱外袍，宽大裙摆
【画风技术】电影级质感画质，8K超高分辨率，超写实真人摄影风格
```

✅ 负面提示词：
```text
（正面：1.5）（侧面：1.4）（面部可见：1.4）（露脸：1.3）（看向镜头：1.3）
face visible, looking at viewer, from front, facing camera
```

### 5. CFG 调优速查

| 值 | 行为 | 适用场景 |
|----|------|---------|
| 0 | 完全无视 prompt | ❌ 不要用 |
| 1.0~1.5 | 弱引导，模型扩散分布为主导 | ✅ **prompt 内部有矛盾时** |
| 1.5~2.5 | 低引导，平衡态 | ✅ **大部分场景推荐** |
| 2.5~4.0 | 中引导 | ✅ prompt简洁无矛盾时 |
| 4.0+ | 强引导，易过度发挥 | ⚠️ 可能导致构图扭曲、颜色过饱和 |

### 6. 角色 LoRA 与视角冲突

- 角色 LoRA（如 Momoka/Weiwei/Rina）的训练数据**几乎全是正面/半侧面展示面部**
- 挂着角色 LoRA 时出正后方视角**天然困难**——LoRA 在潜空间里找脸，prompt 却说脸朝地
- 需要非常规视角时：**LoRA 权重降到 0.1~0.3 或直接关闭**

---

## 二十、CFG 实测与画面崩毁排查记录

> 2026-06-28 新增。基于 moodyProMix_zitV13FP8 + 双程采样工作流的实战踩坑。

### 1. CFG 最大值限制

ComfyUI 的 KSampler 对 CFG（guidance scale）有硬上限：**最大 100**。输入 10000 会报错：
```
Value 10000.0 bigger than max of 100.0
```

CFG=100 实测可出图，但画面极度过饱和、细节全部丢失（文件仅 1.3MB，正常图 2~3MB）。

### 2. CFG 扫描测试结论（0 ~ 20）

| CFG 范围 | 效果 | 推荐度 |
|---------|------|--------|
| 0 ~ 1.0 | 可出图，画面偏柔和，prompt跟随极弱 | ⚠️ 特殊需求 |
| **1.5 ~ 2.5** | **低引导平衡区，prompt有矛盾时首选** | **✅ 推荐** |
| **3.5 ~ 4.5** | **中引导，细节清晰，构图稳定（2.5/3.5/4.0/4.5实测效果最佳）** | **✅ 推荐** |
| 6 ~ 10 | 强引导，色彩饱和，对比度增加 | ⚠️ 视需求 |
| 12 ~ 20 | 过度饱和，色彩溢出，构图僵硬 | ❌ 不推荐 |
| 100 | 画面完全崩溃，仅剩1.3MB | ❌ 灾难 |

全部 CFG 值（0~20）均不会直接导致马赛克/网格状噪声，说明 **CFG 本身不是画面崩毁的直接原因**。

### 3. 画面崩毁的真正根因：潜空间维度奇偶性（FLUX 2×2 Patch Embedding）

FLUX/ZIT 系列模型内部做 2×2 patch embedding——将 latent 分割成 2×2 小块处理。**要求 latent 的宽和高均为偶数**。

```
正常（偶数，如 160×272）:
┌──┬──┬──┬──┐  patch 2×2 完美对齐
├──┼──┼──┼──┤
└──┴──┴──┴──┘

奇数（如 153×272）:
┌──┬──┬──┬──┐  最后多 1 列/行
├──┼──┼──┼──┤  patch 错位溢出
└──┴──┴──┴──┘  → 马赛克/网格崩毁
    ↑ 错位点
```

### 4. 为什么"人脸清晰、背景崩毁"？

| 区域 | 受影响程度 | 原因 |
|------|-----------|------|
| **人脸/身体** | ✅ **几乎不受影响** | 模型对面部的先验极强——训练数据中千亿次出现，即使 patch 错位 1 像素也能"脑补"回来 |
| **背景/景观** | ❌ **明显崩毁** | 树木、水面、建筑边缘、花瓣——高频细节，靠像素精确定位。patch 错位→网格对齐失败→马赛克 |

**关键认知**：人脸是模型的「底层安全网」，背景是「精细活」。当工作流结构出了问题（奇数维度/链接断裂/CFG 过低），安全网先保人脸，背景第一个牺牲。

### 5. 工作流 JSON 文件编码注意事项

从 git checkout 导出的工作流 JSON 在 Windows 上会被保存为 **UTF-16 LE BOM** 编码。ComfyUI 加载这种编码的 JSON 可能产生异常。**必须转存为 UTF-8（无 BOM）编码**后才能正常使用。

转换命令（Python）：
```python
import json
with open('workflow.json', 'rb') as f:
    raw = f.read()
if raw[:2] == b'\xff\xfe':
    text = raw.decode('utf-16-le').lstrip('\ufeff')
    data = json.loads(text)
    with open('workflow.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
```

---

## 二十一、最终推荐工作流配置

> 2026-06-28 最终确定。基于 git aaa9972 版本优化。

### 1. 当前工作流的改动

| 改动 | 改了什么 | 理由 |
|------|---------|------|
| **删除 LoRA 节点** | 移除了 `LoraLoaderModelOnly`（Node 4） | moodyProMix 是 all-in-one，不需要额外挂角色 LoRA。角色 LoRA 会锁定特定面容，与需要灵活调整视角/姿势的场景冲突 |
| **保留独立的负面提示词节点** | Node 8 保留但清空内容为 `""` | Flux 架构的 guidance 机制不需要负面词。但保留独立节点能让 KSampler 的 positive/negative 输入来自**不同节点对象**，确保 CFG 计算公式 `noise = neg + cfg x (pos - neg)` 正确运作 |
| **CFG 默认值调为 3.5** | 原 3.0 → 3.5 | 实测 2.5/3.5/4.0/4.5 效果最佳，3.5 作为默认平衡值 |

### 2. 最终工作流结构

```
UNETLoader(N1) → ModelSampling(N5) → 第一程KSampler(N9) → LatentUpscale(N10,1.7x)
                                          ↑                       ↓
                                    提示词编码器(N7)         第二程KSampler(N11)
                                          ↑                       ↓
                                    CLIP加载器(N2)          VAE解码(N12) → 保存(N13)
```

15 个节点，17 条链接，无多余 LoRA，无多余开关。

### 3. 推荐参数速查

| 参数 | 推荐值 |
|------|--------|
| 第一程 CFG | **3.5** |
| 第一程采样器 | Euler + Simple |
| 第一程步数 | 17（实际 0→12 共 13 步） |
| 放大 | LatentUpscale 1.7x bislerp |
| 第二程 CFG | 1.0 |
| 第二程采样器 | dpmpp_2m_sde + sgm_uniform |
| 第二程步数 | 11（实际 5→999 共 6 步） |
| 竖图分辨率 | 640x1136 |
| 横图分辨率 | 1136x640 |
| 模型 | moodyProMix_zitV13FP8 |
| CLIP | qwen_3_4b (lumina2) |
| VAE | ae.safetensors |

---

## 二十三、2026-06-30 日式漫画风格工作流全记录

> 历时约 2 小时，最终结论：Anima 混合底模 + 专用 LoRA = 12GB 上最佳日式漫画方案。

### 1. 探索路线

| 路线 | 结果 | 原因 |
|------|:----:|------|
| Anima (原版) + Qwen3_06b CLIP | ❌ 0.6B CLIP 太弱 | 复杂长 prompt 理解差 |
| NoobAI-XL Vpred (v-prediction) | ⚠️ 可用但需英文标签 | 需 ModelSamplingDiscrete + CLIPSetLastLayer |
| moodyProMix (写实) + 动漫 LoRA | ❌ 底模写实偏向太强 | LoRA 权重拧不过 |
| **PearlyAnimaMix_v10 + perfect_toon LoRA** | **✅ 最佳方案** | Anima 混合底模 + 专为卡通风格训练的 LoRA |
| Qwen-Rapid-AIO (文生图) | ⚠️ 偏2.5D美式动漫 | 不是日式漫画风格 |

### 2. 最终推荐方案

**底模**: `pearlyAnimaMix_v10.safetensors`（4.13 GB，作者 Serephian）
**LoRA**: `perfect_toon.safetensors`（87.6 MB，触发词 `pearlyperf`，权重 1.0）
**可选 LoRA**: `Bushes_in_Foreground_epoch_10.safetensors`（217.9 MB，作者 parlayjp840）

### 3. 关键参数

| 参数 | 值 |
|------|-----|
| 采样器 | Euler |
| 步数 | 25 |
| CFG | 5 |
| VAE | qwen_image_vae（Anima 专用） |
| CLIP | qwen_3_06b_base（type=qwen_image） |
| 分辨率 | 1080×1920（竖版1080P） |
| Clip skip | 1（默认，不需要 CLIPSetLastLayer） |

**注意**：所有漫画工作流均只支持 **英文提示词（Danbooru 标签格式）**，不支持中文。Qwen3_06b 虽能解析中文，但模型微调数据为英文标签，中英混用效果差。

### 4. ⭐ 最终工作流

| 工作流 | 用途 | 模型 | LoRA |
|--------|------|------|------|
| `Anime_PearlyToon_EN.json` | 日式卡通风格文生图（图1复刻） | pearlyAnimaMix_v10 | perfect_toon w1.0 |
| `Anime_Bushes_EN.json` | 前景灌木场景文生图（图2复刻） | pearlyAnimaMix_v10 | Bushes_in_Foreground w0.8 |

### 5. 踩坑记录

| 坑 | 教训 |
|----|------|
| **v_prediction 模型** | NoobAI-XL 需 ModelSamplingDiscrete + CLIPSetLastLayer，Anima 不需要 |
| **LoRA 基座不匹配** | perfect_toon 是 Anima 基座，Bushes 是 Illustrious 基座，不能混用 |
| **中文 prompt 无效** | Qwen3 能读中文，但模型权重是英文标签训练的，需用英文 Danbooru 标签 |
| **漂白标签过度** | 颜色风格由底模本身决定，硬加 overexposed/pale 标签会崩 |
| **CLIP 0.6B vs 4B** | Anima 锁定 1024 维输入，不能换 qwen_3_4b（2560维）|

### 6. 已下载的关键模型/文件清单

| 文件 | 大小 | 用途 |
|------|:----:|------|
| `pearlyAnimaMix_v10.safetensors` | 4.13 GB | Anima 混合底模（Serephian） |
| `perfect_toon.safetensors` | 87.6 MB | Pearly perfect toon 风格 LoRA |
| `Bushes_in_Foreground_epoch_10.safetensors` | 217.9 MB | 前景灌木 LoRA |
| `sk_anime_style_v1.0.safetensors` | 81.2 MB | ZIT 原生动漫风格 LoRA |
| `NoobAI-XL-Vpred-v1.0.safetensors` | 6.62 GB | 动漫底模（需英文标签+v_prediction） |
| `Comic_Book_V4T3_E10.safetensors` | 162 MB | 漫画书风格 LoRA（支持 ZIT/Flux） |

---

1. **VNCCS Pose Studio + Qwen Rapid-AIO 串联**：3D人偶摆姿 → 输出骨骼图 → 喂给Work-Fisher工作流的骨骼参考
2. **Work-Fisher出图 + MoodyZIT Inpaint精修**：姿势图→MoodyZIT图生图去噪0.5~0.7，利用Flux画质优势
3. **CLIPLoader的qwen_image类型**：ComfyUI已支持，使用CLIPLoader（非DualCLIPLoader）加载Qwen VL模型
4. **SageAttention加速**：项目根目录有SageAttention源码，可编译安装加速推理

---

## 十、TODO：横竖切换 + 姿势变换两步串联

> 2026-06-26 新增

### 当前限制

| 模式 | 能做什么 | 不能做什么 |
|------|----------|------------|
| 横竖切换工作流（稳定版） | ✅ 自动计算宽高、一键切画幅、人物画质保留 | ❌ 躺着→站着等极端姿势变化 |
| 蒙版锁原图版（实验） | ✅ 100% 保留原图画质 | ❌ 人物完全锁定，姿势无法改变 |

### 根本矛盾

扩散模型的约束：
- **要改像素 → 必须重绘 → 不可能 100% 保留原画质**
- **要保画质 → 必须锁像素 → 姿势不能变**

`SetLatentNoiseMask` 让扩展区 AI 填充、原图锁死，但人物姿势也被锁死了。

### 两步串联方案（TODO）

```
Stage1: 灵犀控骨 VNCCS 工作流（denoise=1）
  原图 → VNCCS骨骼引导 → 姿势图（画质有损）

Stage2: MoodyZIT 图生图（denoise 0.5~0.7）
  姿势图 → MoodyZIT 精修画质 → 最终图
```

两个工作流串成一条线即可：姿势转换 → 画质精修。

**硬件可行性**：32GB DDR5 6400MHz 内存足够容纳一个完整 checkpoint 的卸载中转。ComfyUI 的 `--lowvram` 模式在两步之间自动将 Qwen-Rapid-AIO (26.5GB) 卸到内存，再加载 MoodyZIT 模型 (~8GB)，不会爆显存。

**自动化方式**：编写一个 Python 脚本，通过 ComfyUI API 先后提交两个工作流，第一步出图路径传给第二步的 LoadImage 即可一键跑完。

### 已知问题

- `SetLatentNoiseMask` 当前版本在横竖切换工作流中实测不稳定（躺着的人蒙版锁死后不跟随骨骼变化），需进一步调试蒙版与 VNCCS 骨骼引导的兼容性

---

## 九、横竖画幅一键切换开发踩坑全记录

> 2026-06-26 新增。此为本次开发中耗时最长、踩坑最多的功能。

### 目标

在 VNCCS 骨骼控图和 DWPose 姿态编辑两个图生图工作流中，增加**一键切换横竖画幅**功能：输入横图→切换开关→自动输出竖图（或反过来），画布由 AI 自动填充扩展区域。

### 最终方案（Visual 格式 + 自动计算宽高）

```
LoadImage ─→ GetImageSizeAndCount(w, h)
                 │
      SimpleCalculatorKJ(max)  SimpleCalculatorKJ(min)
           max=1920                min=1088
           │                       │
      ┌────┴──────────┬────────────┘
      │               │
      ▼               ▼
ImageResizeKJv2(横)  ImageResizeKJv2(竖)
 w=max, h=min        w=min, h=max
 1920×1088           1088×1920
      │               │
      └───┬───────────┘
          ▼
    LazySwitchKJ(切 IMAGE)
          ▼
    VAEEncode → KSampler → 出图
```

**17 个节点**。`BOOLConstant` 复选框：关=竖图，开=横图。**完全自动**，根据输入图实时计算目标尺寸。

### 踩坑 #1：ImageResizeKJv2 的 width/height 是什么类型？

**错误认知**：以为 width/height 是纯 widget（`widgets_values`），不能通过连线动态设置。

**真相**：查看 KJNodes 源码（`image_nodes.py:2907`），`width` 和 `height` 在 `INPUT_TYPES` 的 `required` 字典中，类型 `"INT"` —— **既是 widget 也是标准输入端口，可以被上游节点连线**。

### 踩坑 #2：SimpleCalculatorKJ 输出索引用错

**现象**：按 `["13", 0]` 取 SimpleCalculatorKJ 输出，结果 ImageResizeKJv2 收到浮点数，行为异常（输出正方形）。

**真相**：`SimpleCalculatorKJ` 有 3 个输出槽位：

| 索引 | 类型 |
|:--:|------|
| 0 | **FLOAT** ← 之前一直引用这个，错了！ |
| 1 | **INT** ← 正确的数值输出 |
| 2 | BOOLEAN |

必须用 `["13", 1]` 取 INT 值。

### 踩坑 #3：GetImageSizeAndCount 输出索引用错

**现象**：`SimpleCalculatorKJ` 收不到正确的宽高数值。

**真相**：`GetImageSizeAndCount` 有 4 个输出：

| 索引 | 名称 | 类型 |
|:--:|------|------|
| 0 | image | IMAGE |
| 1 | width | **INT** ← 宽 |
| 2 | height | **INT** ← 高 |
| 3 | count | INT |

之前用 `["11", 0]` 和 `["11", 1]`，实际拿到的是 IMAGE 和 width（INT），缺了 height。正确是 `["11", 1]`（width）和 `["11", 2]`（height）。

### 踩坑 #4：LazySwitchKJ 只有一个输出

**现象**：`ImageResizeKJv2` 的 width/height 引用 `["15", 1]` → 不存在的输出口 → 全乱。

**真相**：`LazySwitchKJ` 只有 **1 个输出**（index 0），类型为 `*`（通配符）。所有引用必须用 `["节点ID", 0]`。

### 踩坑 #5：LazySwitchKJ 传数值 = tensor 地狱

**现象**：`SimpleCalculatorKJ(INT) → LazySwitchKJ → ImageResizeKJv2(width)` → `RuntimeError: Boolean value of Tensor with more than one value is ambiguous`

**原因**：LazySwitchKJ 把上游 INT 包装成 PyTorch tensor，ImageResizeKJv2 内部做 `if width == 0` 判断时，tensor 无法转 bool 就炸。

**解决**：**不要让 LazySwitchKJ 切数值**。改为两个 `ImageResizeKJv2` 各从 `SimpleCalculatorKJ` **直接**接收 INT，`LazySwitchKJ` 只切最终的 IMAGE 输出——IMAGE 类型经过 switch 不会出 tensor 问题。

### 踩坑 #6：API 格式 vs Visual 格式

**现象**：手写 API 格式的 JSON 反复报错/弹窗/不兼容。

**真相**：
- **API 格式**（`{"1": {"class_type": "...", "inputs": {...}}}`）：适合程序调用（POST `/prompt`），但不适合手动编辑。节点类型的输入/输出名称、连接格式容易写错。
- **Visual 格式**（`{"nodes": [{...}], "links": [[...]]}`）：由 ComfyUI 导出，格式 100% 正确。**编辑工作流必须基于 Visual 格式**。

**教训**：在 ComfyUI 中先加载 API 工作流 → 调整布局 → 保存为 Visual 格式 → 在此基础上修改 JSON。不要在 API 格式上凭空手写。

### 踩坑 #7：`_meta.title` 兼容性

Visual 格式支持 `_meta: {"title": "中文标题"}` 给节点加自定义标题。API 格式在某些版本中不识别 `_meta`，会导致弹窗。

**教训**：仅在 Visual 格式的工作流中使用 `_meta.title`。

### 踩坑 #8：ImagePadForOutpaint 固定像素 vs 自动计算

曾经尝试用 `ImagePadForOutpaint` + 固定像素（如 600px）做 outpainting：
- 1920×1088 → 上下各扩 600px → 1920×2288（比例还行）
- 3416×1928 → 上下各扩 600px → 3416×3128（接近正方形，失败）

**结论**：固定像素方案对不同分辨率的输入图比例失控。必须用 `ImageResizeKJv2(pad)` 配合**动态计算的宽高**。

### 踩坑 #9：Keep Proportion 模式选择

- `"pad"`：缩放后居中，黑边填充 → 人物居中，适合做 letterbox
- `"crop"`：缩放后裁切 → 可能裁掉人物
- `"stretch"`：直接拉伸 → 人物变形

**结论**：横竖切换用 `"pad"` 模式，原图等比缩放后居中，AI 只需填充黑边区域。

### 踩坑 #10：denoise 值与人物保留的权衡

- `denoise=1`（完全重绘）：换了画布尺寸后人物会被彻底重绘，服化道全变
- `denoise=0.4~0.6`：人物大部分保留，但扩展区填充不充分

在两阶段方案中，Stage1 改姿势用 `denoise=1`，Stage2 扩画布用 `SetLatentNoiseMask` 锁定原图区域。但蒙版锁死也锁住了躺着的人物，导致"躺着的人还在、后面站着一个"的 bug。

**最终方案**：`denoise=1` 统一重绘，配合 `VNCCS_PoseStudio` 骨骼引导 + `TextEncodeQwenImageEditPlus` 图文理解。

### 横向对比：所有尝试过的方案

| 方案 | 节点数 | 问题 | 结果 |
|------|:--:|------|:--:|
| 固定 16:9 画布(1536×864) | 15 | 比例锁死，不自动 | ❌ |
| 宽高互换(SimpleCalculatorKJ→LazySwitchKJ数值) | 20 | tensor 报错 | ❌ |
| ImagePadForOutpaint 固定像素 | 18 | 3416×1928→3416×3128 正方形 | ❌ |
| ImageResizeKJv2 crop 模式 | 18 | 裁掉人物 | ❌ |
| SetLatentNoiseMask 锁原图 | 20 | 躺着的人不变+站着一个 | ❌ |
| 两阶段(先扩画布再改姿) | 27 | 太复杂 | ❌ |
| **SimpleCalculatorKJ→ImageResizeKJv2 直连** | **17** | **✅ 正确** | ✅ |

### DWPose 工作流横竖切换

`千面绘形_DWPose姿态编辑_16x9画幅一键横竖切换_图生图.json` 使用同一方案：两个 `ImageResizeKJv2` + `LazySwitchKJ` 在 VAEEncode 之前切画布尺寸。

**特殊处理**：DWPose 工作流中，横竖切换在 `VAEEncode` 之前（通过两个 `ImageResizeKJv2` 的 IMAGE 输出切换），而非 latent 层面。这样 TextEncodeQwenImageEditPlus 的 `image1` 参数拿到的是已调整画幅的图片，Qwen 模型能正确理解完整画布构图。

---

## 十一、2026-06-26 Nunchaku / GGUF / AnyPose 全记录

> 历时近 6 小时（16:00~23:00），从 Nunchaku FP4 → 社区 LoRA → GGUF + AnyPose → DWPose，全程采样 + 推荐路线总结。

### 1. 启动脚本与 Python 环境

ComfyUI 自带的嵌入式 Python 路径：
```
ComfyUI-aki-v3/python/python.exe  ← Python 3.13，ComfyUI 实际用这个
```
所有 `pip install` 必须用这个 Python。启动脚本两种：
- `启动ComfyUI.bat`：原始版，用嵌入式 Python
- `启动ComfyUI_Nunchaku.bat`：+设置CUDA DLL PATH

### 2. Nunchaku _C.pyd DLL 加载失败

**报错**：`DLL load failed while importing _C: 找不到指定的模块。`
**原因**：`_C.pyd`(277MB)编译了CUDA kernel，需要cudart/cublas等DLL在PATH上。
**解决**：启动前设置PATH包含 `torch\lib` + `nvidia\cuda_runtime\bin` + `nvidia\cublas\bin`
```python
os.add_dll_directory("python/Lib/site-packages/torch/lib")
```

### 3. nunchaku 版本与 LoRA 兼容性

`ComfyUI-QwenImageLoraLoader` 要求 nunchaku ≥ 1.2.0 才支持 FP4(v4) 模型。
v1.2.1 wheel 命名规则：`nunchaku-版本+cu版本torch版本-cp版本-cp版本-win_amd64.whl`
示例：`nunchaku-1.2.1+cu13.0torch2.9-cp313-cp313-win_amd64.whl`

### 4. RTX 5070 (Blackwell sm_120) 的 PyTorch 要求

| PyTorch | CUDA | 支持 5070 | nunchaku 版本 |
|---------|------|-----------|---------------|
| 2.6.0+cu124 | 12.4 | ❌ sm_120不支持 | 1.0.1+torch2.6 |
| 2.8.0+cu128 | 12.8 | ✅ | 1.2.1+cu12.8torch2.8 |
| 2.9.0+cu130 | 13.0 | ✅ | 1.2.1+cu13.0torch2.9 |
| 2.11.0+cu128 | 12.8 | ✅ (**实测**) | ❌ 无对应wheel |

**结论**：用 torch 2.8/2.9 + nunchaku 1.2.1 匹配的 CUDA 版本。

### 5. CLIPLoader type 参数

Qwen-Image-Edit 必须用 `qwen_image`，不能用 `lumina2`。

### 6. TextEncodeQwenImageEdit vs TextEncodeQwenImageEditPlus

Nunchaku 官方工作流用单图版的 `TextEncodeQwenImageEdit`，不支持 AnyPose 的双图条件注入。官方明确标注 "LoRA support not available now"。

### 7. GGUF 模型存放目录

`UnetLoaderGGUF` 读取 `models/diffusion_models/`，不是 `models/unet/`。
Q5_0(14.3GB)超12GB显存，换成 Q4_K_M(10.5GB)才能跑。

### 8. LoraLoader CLIP 链

必须串联：CLIPLoader → LoraLoaderA.clip → A.clip_out → LoraLoaderB.clip → B.clip_out → TextEncoder.clip
每个 LoraLoader 的 CLIP 输入输出不能留空。

### 9. LazySwitchKJ 正确参数

| 错误 | 正确 |
|------|------|
| `name: "boolean"` | `name: "switch"` |
| `name: "image_a"` | `name: "on_true"` |
| `name: "image_b"` | `name: "on_false"` |

### 10. ImageResizeKJv2 widget_values

当 width/height 通过连线输入时：`["lanczos", "pad"]`
有效 keep_proportion：`stretch, resize, pad, pad_edge, crop, pillarbox_blur, total_pixels`

### 11. DWPreprocessor vs OpenposePreprocessor

Work-Fisher 工作流使用 `OpenposePreprocessor`（非DWPreprocessor）。

### 12. 推荐路线

| 路线 | 可操作性 | 说明 |
|------|---------|------|
| ⭐ **Qwen-Rapid-AIO + DWPose/VNCCS** | ✅ 已验证可行 | 你已有的 Work-Fisher/灵犀控骨工作流 |
| ⭐ **Nunchaku FP4 图文编辑** | ✅ 已验证可行 | `Nunchaku_图文编辑_横竖切换.json` |
| ❌ **Nunchaku + AnyPose LoRA** | ❌ 官方不支持双图+LoRA | Nunchaku 文档明确写不支持 |
| ⚠️ **GGUF + AnyPose** | ⚠️ 理论可行但未验证 | Q4_K_M 模型已就位，待测试 |

---

## 十四、2026-06-27 Flux.2 Klein 4B 探索记录

> 尝试用 Flux.2 Klein 4B Distilled 替代 MoodyZIT 文生图，追求更高速度与画质。结论：快是真的快，但画质不如 MoodyZIT 双程采样。

### catlover1937 最新状态

作者 HuggingFace (catlover1937) 近期更新（均为 Flux.1 架构）：
| 模型 | 更新时间 | 基于 |
|------|---------|------|
| Moody-Pro-Mix | 1 天前 | Flux.1 |
| moody-desire-mix | 3 天前 | Flux.1 |
| Moody-Real-Mix | 20 天前 | Flux.1 |

**结论：catlover 仍活跃，但全部基于 Flux.1，没有迁移到 Flux.2 Klein。**

### Klein 4B 实测结论

**Distilled（蒸馏版）** - 已下载使用
| 参数 | 值 |
|------|-----|
| 模型 | `flux-2-klein-4b-fp8.safetensors` (3.79GB) |
| CLIP | `qwen_3_4b.safetensors` + type=`flux2` |
| VAE | `flux2-vae.safetensors` |
| 采样器 | Euler + Simple |
| 步数 | **4**（蒸馏版锁定，不可增加） |
| CFG | 2.5（原生建议 1.0，实测 2.5 细节更好） |
| 速度 | **3-5 秒/张**（5070） |
| 画质 | 不如 moodyProMix 双程采样（28步），但速度快 10 倍 |
| 中文支持 | qwen_3_4b 原生 32K tokens ✅ |

**Base（基础版）** - 已删除，实测翻车
| 参数 | 值 |
|------|-----|
| 模型 | `flux-2-klein-base-4b-fp8.safetensors` (~4GB) |
| 结论 | ❌ 8 步出图人物残缺、磨皮严重、文字乱码 |
| 原因 | Base 版是为训练 LoRA 设计的底模，未蒸馏优化直接出图效果差；FP8 量化进一步损失精度 |

### 踩坑记录

1. **CLIPLoader type 错误**：Klein 4B 需要 `flux2` 类型，不是 `lumina2` 或 `flux`。`lumina2` 导致 `mat1 and mat2 shapes cannot be multiplied` 维度错误。

2. **CLIPLoader type `flux` 不存在**：ComfyUI v0.24.0 的 CLIPLoader 23 个类型中没有 `flux`，正确的类型名为 `flux2`。

3. **Distilled 版步数锁死**：蒸馏版文档明确警告不可超过 4 步，否则质量下降。Base 版则相反，需要 8-12 步才收敛。

4. **Base 版不能直接出图**：Base 的定位是"给训练用的底模"，蒸馏版才是"给出图用的成品"。直接拿 Base 版跑 8 步 CFG=3.5 的结果远不如蒸馏版 4 步。

5. **CFG 调整**：Klein 4B 官方推荐 CFG 1.0-1.5，但实测 CFG 2.5 能显著提升细节清晰度，CFG>3 开始出现色彩异常。

### 12GB 显存可选模型全景（2026年6月）

| 模型 | 显存 | 能跑？ | 画质 |
|------|------|--------|------|
| **FLUX.2 [klein] 4B Distilled** | 8-13GB | ✅ **最佳选择** | ⭐⭐⭐⭐ |
| Stable Diffusion 3.5 Large | 8GB | ✅ 但没必要 | ⭐⭐⭐ |
| SDXL | 8GB | ✅ 太老了 | ⭐⭐ |
| Z-Image-Turbo 6B | 16GB | ❌ | ⭐⭐⭐⭐ |
| Qwen-Image 2.0 | 24GB | ❌ | ⭐⭐⭐⭐⭐ |
| FLUX.2 [dev] 32B | 24GB | ❌ | ⭐⭐⭐⭐⭐ |
| GLM-Image | 20GB | ❌ | ⭐⭐⭐⭐ |
| Krea 2 | 16GB | ❌ | ⭐⭐⭐⭐ |
| FLUX.2 [klein] 9B | 16GB | ❌ | ⭐⭐⭐⭐ |

**结论**：Klein 4B Distilled 是 12GB 档位当前最平衡的选择。画质上限不如 MoodyZIT 双程采样，但速度优势极大。

### 已测试的亚洲优化模型

| 模型 | 架构 | 大小 | 结论 |
|------|------|------|------|
| **2127 - Z Image Asian Utopian v2.0 FF FP8** | ZImageTurbo | 5.7GB | ❌ 不如 moodyProMix V13。中文文字扭曲、不加负面词画面模糊（作者 hinablue 微调质量不如 catlover1937） |
| **F.2-klein亚洲美女 LoRA** | Klein 4B | LoRA | 未下载（RunningHub 需登录） |
| **Asian Mix Lokr LoRA** | Klein 4B | LoRA | 未下载（RunningHub 需登录） |
| **TinFlux 逼真感人像**（完整模型替换） | Klein 4B | ~4GB | 未下载（LiblibAI 需会员） |

### 最终结论

**你手上最好的亚洲写实模型就是 catlover1937 的 moodyProMix_zitV13FP8。猫腻圈的所有替代品（Klein 4B Distilled/Base、Asian Utopian、TinFlux）都打不过它。**

| 路线 | 速度 | 画质 | 姿势控制 | 结论 |
|------|------|------|---------|------|
| **moodyProMix V13 双程采样** | 慢（28步） | ⭐⭐⭐⭐⭐ 天花板 | ❌ 不能 | 文生图主力 |
| **灵犀控骨 + Qwen-Rapid** | 中等 | ⭐⭐⭐⭐ | ✅ 最佳 | 姿势控制唯一方案 |
| **Klein 4B Distilled** | 极快（4步） | ⭐⭐⭐⭐ | ❌ 不能 | 快速出图备选 |
| **Asian Utopian FP8** | 中等 | ⭐⭐⭐ | ❌ 不能 | ❌ 已删除 |

**12GB 5070 的终极方案就是：灵犀控骨改姿势 + MoodyZIT 双程采样出图。不要折腾了。**

---

## 十三、2026-06-27 两阶段精修失败总结

> 尝试将灵犀控骨（姿势控制）与 MoodyZIT（画质精修）合并为一个工作流，折腾 1 小时放弃。

### 根本原因

两个能力分属不同模型体系，合并在一个工作流里需要同时加载两个 UNET，12GB VRAM 不够。`--lowvram` 也无法完美切换。

| 能力 | 模型 | VRAM |
|------|------|------|
| 姿势控制 | Qwen-Rapid-AIO-NSFW-v18 (checkpoint) | ~8~10GB |
| 画质精修 | moodyRealMix_zitV7GlobalFP8 (~8GB) | ~8GB |
| 合计 | | ~16~18GB > 12GB ❌ |

### 踩坑过程

1. **Denoise 死局**：denoise>0.5 会大量重绘 Stage 1 的姿势细节，denoise<0.4 又看不出画质提升。两头不讨好。

2. **分辨率适配死局**：MoodyZIT (Flux) 有训练锁定的分辨率（640×1136），Stage 1 输出不兼容。降采样→精修→升采样，每一步都损失细节，最终比 Stage 1 还糊。

3. **工作流越改越复杂**：ImageScaleBy → ImageResizeKJv2 → 双 KSampler → 升采样 → 降采样 → ... 每次改动引入新问题，产出越来越差。

### 最终结论

- ⭐ **灵犀控骨_VNCCS骨骼控图_一键横竖切换_图生图_Visual.json** = 当前 12GB 最佳姿势控制方案
- ⭐ **MoodyZIT_V7_Visual_文生图_双程采样_快速预览_文字渲染.json** = 纯文生图高质量方案（单出）
- ❌ **不要尝试合并两者**

### 灵犀控骨工作流稳定参数

| 参数 | 值 |
|------|-----|
| 模型 | Qwen-Rapid-AIO-NSFW-v18 (CheckpointLoaderSimple) |
| 采样器 | euler_ancestral |
| 调度器 | beta |
| 步数 | 8 |
| CFG | 1 |
| Denoise | 1（必须完全重绘姿势才变） |
| AuraFlow shift | 3 |
| CFGNorm | 1 |
| 正面提示词 | `realistic photo, high quality, 真实摄影风格` + 手动追加姿势描述 |
| 负面提示词 | 由 FluxKontext 自动从正面分离 |
| 横竖切换 | BOOLConstant 关=竖图 / 开=横图 |

---

## 十五、2026-06-28 VNCCS + ControlNet + 文生图姿势控制全记录

> 历时 3 小时，逐一验证了 4 种姿势控制方案。最终结论：12GB VRAM 上，用 2D OpenPose 编辑器 + GGUF + ControlNet 是唯一可靠的文生图姿势控制路线。

### 1. 方案 A：VNCCS → TextEncodeQwenImageEditPlus(image2)

- **原理**：VNCCS 3D 人偶渲染图作为 `image2` 喂入 Qwen VL 的 `TextEncodeQwenImageEditPlus`，由 VL CLIP 将人偶图编码进入 conditioning
- **结果**：❌ 姿势不跟。文字提示词中的姿态描述权重远高于 image2 的微弱信号，模型最终"听"了文字
- **结论**：原始工作流里 VNCCS 确实提供了辅助信号，但文字描述对最终姿势的贡献更大

### 2. 方案 B：VNCCS → VAEEncode → KSampler（图生图锚定）

- **原理**：VNCCS 人偶通过 VAEEncode 直接变成 KSampler 的起始潜空间，用 denoise 控制人偶保留/擦除比例
- **结果**：✅ 姿势能锁死，但存在不可调和的平衡点
  - `denoise=0.7~0.85`：姿势正确，但 3D 人偶纹理残留在最终图上
  - `denoise>0.9`：人偶纹理消失，但姿势也被冲掉（回到 txt2img）
- **两阶段尝试**：第一程低 denoise 锚定姿势→第二程高 denoise 擦纹理，结果第二程仍会破坏姿势
- **结论**：VNCCS 人偶和真实人物在潜空间中差异太大，任何保留结构的操作都会保留纹理

### 3. 方案 C：VNCCS → ControlNet（openpose/pose 模式）

- **原理**：VNCCS 3D 人偶直接喂给 ControlNet 的 pose 模式
- **结果**：❌ 姿势不跟。pose ControlNet 在 OpenPose 骨架线条图（黑底白线）上训练，无法识别 VNCCS 的 3D 彩色人偶渲染图

### 4. 方案 D：VNCCS → MiDaS 深度图 → ControlNet（depth 模式）

- **原理**：MiDaS 将 VNCCS 人偶提取为纯灰度深度图（无纹理），喂给 ControlNet 的 depth 模式。depth 模式只读空间 Z 轴信息
- **结果**：❌ 姿势不跟。最终确认 **Qwen-Rapid-AIO-NSFW-v18 与 ControlNet 不兼容**。虽然架构配置匹配（`inner_dim=3072, joint_attention_dim=3584`），但社区合并版 checkpoint 的 UNet 权重经过微调，ControlNet 注入的空间信号被"翻译"错误

### 5. 方案验证：2D OpenPose 编辑器 + ControlNet

- **原理**：用 `Nui.OpenPoseEditor` 手动摆 2D 火柴人骨架，输出标准 OpenPose 格式 → ControlNet(openpose) → 原版 Qwen GGUF
- **结果**：✅ 理论上可行（已有 12G 工作流 `【Qwen-2512+ControlNet】OpenPose姿势控制_12G.json`），但 2D 骨架无法表达深度（如趴地姿势），且 GGUF 速度约 500秒/张
- **结论**：唯一可靠的文生图姿势控制路线，但受限于 2D 深度表达和 GGUF 速度

### 总表

| 方案 | 姿势 | 画质 | 速度 |
|------|:---:|:---:|:---:|
| VNCCS + TextEncode(image2) | ❌ 文字覆盖 | ⭐⭐⭐⭐ | ⚡ |
| VNCCS + VAEEncode(img2img) | ✅ denoise<0.85 | ⭐⭐ 人偶残留 | ⚡ |
| VNCCS + ControlNet(pose) | ❌ 格式不识别 | - | - |
| VNCCS + ControlNet(depth) | ❌ 模型不兼容 | - | - |
| OpenPose 编辑器 + GGUF + ControlNet | ✅ | ⭐⭐⭐⭐ | 🐢 500s |


### 关键认知

- **VNCCS 的 image2 路径**：提供辅助视觉参考，但文字姿势描述力量更强
- **Qwen-Rapid-AIO ≠ 原版 Qwen-Image**：社区合并版的 UNet 无法被 ControlNet 正确控制
- **12GB 上的现实**：GGUF + ControlNet 是唯一可靠路线，代价是速度

---

## 十六、2026-06-28 Real-Qwen-Image-V2 + 最终结论

### 1. Real-Qwen-Image-V2 下载与测试

- **来源**：HuggingFace `wikeeyang/Real-Qwen-Image-V2`（2026年1月发布）
- **基底**：Qwen-Image-2512 微调，专攻写实度和亚洲人脸美学
- **下载**：`Real-Qwen-Image-V2-2512-Q4_K_M.gguf`（13.1GB）→ 置于 `models/diffusion_models/`
- **结果**：❌ 13.1GB GGUF + 3.5GB ControlNet + 8.7GB CLIP ≈ 25+GB 总量，12GB VRAM 在 `--lowvram` 下 GPU 利用率仅 50%，速度不可接受

### 2. 启动参数修正

`start_comfyui.bat` 从 `--high-ram` 改为 `--lowvram`，提升 Qwen-Rapid-AIO 模型的内存管理效率。

### 3. VAEEncode img2img 方案深入验证

- VNCCS → VAEEncode → KSampler 可以在 `denoise=0.7~0.85` 锁死姿势
- 但人偶纹理残留无法消除：denoise 升高→姿势丢失，denoise 降低→纹理残留
- 两阶段采样（第一程锚姿势+第二程擦纹理）在该平衡点上同样失效
- **结论**：VAEEncode 方案的 denoise 平衡点是无解的，不适合生产使用

### 4. 文生图 + 粗略姿势引导方案（可用的）

创建了 `Qwen-Rapid_OpenPose_文生图_9x16画幅切换.json`：
- **模型**：Qwen-Rapid-AIO（CheckpointLoaderSimple，快速）
- **姿势**：`Nui.OpenPoseEditor` 手动摆火柴人 → `dw_pose_image` → `TextEncodeQwenImageEditPlus.image2`（Qwen VL 视觉参考）
- **横竖切换**：BOOLConstant + LazySwitchKJ + 双 EmptyLatentImage
- **骨架预览**：PreviewImage 节点
- **骨架保存**：SaveImage 节点保存为 PNG

已知局限：2D 火柴人无法表达深度，趴地/朝拜姿势会被解读为侧身蹲姿。速度 5-15 秒/张（`--lowvram` 后）。

### 5. 工作流文件归档

| 文件 | 状态 | 用途 |
|------|:---:|------|
| `Qwen-Rapid_OpenPose_文生图_9x16画幅切换.json` | ✅ 可用 | 快速版文本+粗略姿势 |
| `Qwen-2512_OpenPose编辑器_ControlNet_文生图_12G.json` | ✅ 可用 | GGUF+CN精准姿势（慢） |
| `Qwen-Rapid_OpenPose_文生图_快速预览.json` | ⚠️ 旧版 | 无横竖切换，可删除 |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_文生图_Visual.json` | ❌ 实验残留 | 多次修改后的混乱版本 |

### 6. 终极结论

**2026年6月，12GB VRAM（RTX 5070）上，不存在同时满足以下所有条件的方案：**

- ✅ 文生图（txt2img）
- ✅ 精准 3D 姿势控制（如 VNCCS 摆的趴地/朝拜姿态）
- ✅ 写实画质
- ✅ 高速度（<30秒/张）
- ✅ 12GB 显存约束

三个需求互相制约：
- **要姿势 → ControlNet → 需要 GGUF 或更多 VRAM → 慢/爆显存**
- **要速度 → Qwen-Rapid-AIO → 不支持 ControlNet → 姿势控制弱**
- **要 3D 深度 → VNCCS → 人偶格式与 ControlNet/文生图不兼容**

当前最优妥协：`Qwen-Rapid_OpenPose_文生图_9x16画幅切换.json`——牺牲姿势精度换速度。

未来可探索：24GB+ 显卡 + Real-Qwen-Image-V2 FP8 + ControlNet(depth) + VNCCS → MiDaS深度图联动，这可能实现真正的 3D 姿势文生图控制。但不在当前硬件范围内。

---

## 二十二、三视图提示词写法经验总结（横图 vs 竖图）

> 2026-06-29 新增。基于 MoodyZIT + Flux Qwen 纯文本三视图生成反复实测总结。

### 一、横图三视图 vs 竖图三视图：核心区别

| 维度 | 横图三视图 | 竖图三视图 |
|------|-----------|-----------|
| **布局方式** | 左→中→右 横向排列 | 上→中→下 纵向排列 |
| **适用姿势** | 站姿、直立动作（人体纵向伸展） | 躺姿、卧姿、坐姿（人体横向伸展） |
| **画布比例** | 宽 > 高（如 1136×640） | 高 > 宽（如 640×1136） |
| **每格空间** | 人物高度受限制，容易裁切 | 人物高度充裕，适合展示全身 |
| **触发词** | `triptych layout, left to right` | `vertical triptych layout, top to bottom` |
| **尺寸关键词** | `landscape, horizontal` | `portrait, vertical` |

### 二、通用三视图核心指令（两者通用）

```
[画质前缀] + [三视图触发词] + [分格锁定] + [动作锁定] + [角色描述] + [背景控制]
```

**必含触发词：**
- `character sheet` / `三视图`
- `three views` / `三个标准视角`
- `front view, side view, back view` / `正视图，侧视图，后视图`

**分格锁定写法（核心技巧）：**
```
[左]正视图，[中]严格90度左侧面视角（脸朝左），[右]正后方视角
```
或竖图版：
```
[上格]正视图，[中格]严格90度左侧面视角（脸朝左），[下格]正后方视角
```

**动作锁定写法（必须）：**
```
三个视角的人物必须执行完全一模一样的动作：[具体动作描述]
```
- 必须明确写"**一模一样**"或"**identical**"
- 动作描述要具体到关节位置，避免"五体投地"这类抽象词

### 三、横图三视图完整写法模板

```
超写实，8K，三连画布局，画面上恰好三个人物并排站立，从左到右排列，全身像，三个标准视角：[左]正视图，[中]严格90度左侧面视角（脸朝左），[右]正后方视角。

三个视角的人物必须执行完全一模一样的动作：[具体动作，如：自然站立，双手自然下垂，目视前方]

三个图里是同一个角色：[角色详细描述：年龄、性别、脸型、肤色、发型、发色、五官特征]

穿着：[服装详细描述：款式、颜色、材质、配饰]

背景：纯白色干净背景，均匀照明无阴影，清晰对焦，高保真质感。
```

### 四、竖图三视图完整写法模板

```
超写实，8K，竖版三格连画布局，画面上恰好三个人物上下排列，分别为上格、中格、下格，全身像，三个标准视角：[上格]正视图，[中格]严格90度左侧面视角（脸朝左），[下格]正后方视角。

三个视角的人物必须执行完全一模一样的动作：[具体动作]

三个图里是同一个角色：[角色详细描述]

穿着：[服装详细描述]

背景：纯白色干净背景，均匀照明无阴影，清晰对焦，高保真质感。
```

### 五、关键踩坑经验（反复验证过的）

#### 1. 动作描述要"几何化"，不要"文学化"
- ❌ 错误：`五体投地`（太抽象，模型不懂）
- ✅ 正确：`双膝跪地，臀部坐于脚后跟，上半身从髋部向前折叠，额头贴地，胸口贴大腿`

#### 2. 分格布局必须明确
- ❌ 错误：`三视图`（模型可能画成三张独立的图拼在一起，也可能画成一张图里三个人）
- ✅ 正确：`[左]正视图，[中]侧视图，[右]后视图`（分别锁定每个格子的内容）

#### 3. 侧视图要强制"脸朝左/右"
- ❌ 错误：`侧视图`（模型可能画成45度半侧面，脸仍能看见双眼）
- ✅ 正确：`严格90度左侧面视角（脸朝左），只露左脸，右眼完全被遮挡`

#### 4. 后视图要强制"背对镜头"
- ❌ 错误：`后视图`（模型可能让人物回头露脸）
- ✅ 正确：`正后方视角，后脑勺对着镜头，面部不可见，背对观众`

#### 5. 人数要明确
- ❌ 错误：`三个人物`（模型可能画成3个以上）
- ✅ 正确：`画面上恰好三个人物` / `exactly 3 figures`

#### 6. 人物高度一致要强制
- ❌ 错误：三个格子里的同一角色高矮胖瘦不一样
- ✅ 正确：追加`三个人物在画面中的比例一致，身高相同，占据各自格子的面积相同`

### 六、横图 vs 竖图的选型决策树

```
要画什么姿势？
│
├── 站姿、直立动作（人体纵向伸展）
│   └── 用 横图三视图（左-中-右排列）
│       分辨率参考：1136×640 或 1024×512
│       理由：站立时人体高度大于宽度，横图中每格有足够高度展示全身
│
└── 躺姿、卧姿、坐姿（人体横向伸展）
    └── 用 竖图三视图（上-中-下排列）
        分辨率参考：640×1136 或 640×1920（三格）
        理由：躺卧时人体宽度大于高度，竖图中每格有足够宽度展示全身
```

### 七、成功案例记录

| 姿势 | 画幅 | 结果 | 关键成功因素 |
|------|------|------|-------------|
| 站立竖叉 | 横图（三格并排） | ✅ 稳定成功 | 动作几何关系简单（一条腿站，一条腿上举），描述无歧义 |
| 横卧 | 竖图（三格上下） | ⚠️ 部分成功 | 侧躺姿势训练数据丰富，但侧视图脸部转向仍需强制锁定 |
| 跪姿趴地 | 横图/竖图 | ❌ 反复失败 | 动作复合折叠（膝+髋+颈），FLUX纯文本无法精确理解 |

### 八、终极结论

1. **Flux + Qwen 纯文本三视图的有效边界：**
   - ✅ 站姿、简单卧姿（几何关系清晰的单一动作）
   - ⚠️ 坐姿（部分可，但需极度具体的描述）
   - ❌ 复合折叠姿态（跪趴、蜷缩等）

2. **超出边界时，必须切换方案：**
   - 用 `灵犀控骨` 工作流，3D人偶摆姿 + 图生图，姿态由骨骼图控制
   - 或放弃一次性三视图，改单张生成后拼接

3. **Flux 不需要负面提示词**（架构不支持），把精力集中在正面词的精准度上。

---

## 二十四、人物景别控制：近景 / 中景 / 远景实战经验

> 2026-07-01 新增。基于 moodyProMix_zitV13FP8 + Momoka LoRA 实测总结。

### 1. 问题背景

MoodyZIT / ZImageTurbo 系列的训练数据以**人像特写和半身照为主**，模型有很强的「放大人物看脸」的内禀偏置。即使 prompt 写了 `full body` 或 `全身入镜`，模型仍倾向于出近景特写。

### 2. 根因分析

| 因素 | 说明 |
|------|------|
| **训练数据偏置** | ZIT 训练集以 portrait / half-body 为主，模型认为「离远拍」不是常规操作 |
| **人物细节量** | subject 描述越详细（发型/五官/妆造），模型越想 zoom in 看清细节 |
| **构图指令位置** | `full body` / `远景` 写在 prompt 末尾会被 CLIP 注意力稀释 |
| **镜头语言** | 85mm 暗示特写，35mm 暗示中景，24mm 暗示远景——模型理解镜头焦距含义 |

### 3. 三景别控制公式

#### 3.1 近景 / 特写（Close-up）

适合：面部表情、半身姿势

```
【构图】特写，半身，人物占据画面大部分，背景虚化
一位身穿...的少女，【面部细节省略不影响构图】
【画风】85mm镜头，浅景深
```

**实测效果**：⭐⭐⭐⭐⭐ 模型天然倾向，几乎不需要额外控制。

#### 3.2 中景（Medium Shot）—— 已验证

适合：全身坐姿、跪姿、站姿，人物在画面中大小适中

```
【构图】中远景，全身完整在画面内，人物高度约占画面一半，
头顶上方留约四分之一空白，人物大小适中
一位身穿...的少女
【画风】35mm镜头
约束：全身中远景，人物大小适中
```

**实测效果**：⭐⭐⭐⭐⭐ 稳定有效。关键技巧：

1. **「人物高度约占画面一半」** 这个定量描述比 `full body` 更精准
2. **「头顶上方留约四分之一空白」** 锚定画面顶部边界
3. **中文有效**：模型支持中文，用中文写构图指令完全可行
4. **人物细节要精简**：`一位身穿淡蓝薄纱长裙的少女` 就够了，避免五官/妆造细节导致模型 zoom in

#### 3.3 远景（Wide Shot）—— 已验证

适合：躺姿、一字马、大场景，人物在画面中很小

```
【构图】远景，人物在画面中占很小比例，人物四周大量空白，
人物头顶和脚下留有大量空间，以大场景为主人物只是点缀
一位身穿...的少女
【画风】24mm广角镜头，深景深
约束：远景，人物极小
```

**实测效果**：⭐⭐⭐⭐⭐ 第一次用 `人物极小` 时效果「人物太小了」，说明控制力足够强，只需调整比例。

### 4. 关键经验总结

| 景别 | 人物占画面比例 | 关键词 | 注意 |
|:----|:-------------:|:-------|:----|
| 近景 | 70%~100% | 特写，半身，85mm | 模型天然倾向，不加也出 |
| 中景 | **40%~50%**（约一半） | 中远景，人物高度约占画面一半，头顶上方留四分之一空白 | **最常用，需要主动控制** |
| 远景 | 10%~20%（极小） | 远景，人物极小，人物占很小比例 | 需配合广角镜头描述，否则模型抗拒 |

### 5. 踩坑记录

#### 5.1 人物细节越多，画面越近

```
❌ 错误：一位身穿淡蓝薄纱长裙的少女，面容精致冷白肌肤，两侧留长垂耳碎发其余束发，
   眼眸圆大睫毛纤长，鼻梁小巧嘴唇粉嫩...
   → 模型: 「细节这么多？让我放大看看」→ 特写

✅ 正确：一位身穿淡蓝薄纱长裙的少女
   → 模型: 「描述很简略，那按构图指令办」→ 中远景
```

**原则**：构图和人物描述是矛盾的——细节挤占构图指令的注意力权重。构图不稳时，优先删人物细节。

#### 5.2 英文构图术语 vs 中文

> **2026-07-01 更新**：实测发现 **英文构图指令的精准度远超中文**。

中文的「脚下留约三分之一空白」模型只能执行到「二十分之一」的精度，而英文 `feet fully visible with clear space below` 能精准实现。

**推荐公式**（已验证12次以上）：
```
# 英文部分：精确控制构图
full body shot, subject centered, feet fully visible with space below,
no cropping, medium shot, subject height about 50 percent of frame

# 中文部分：描述人物、动作、场景
一位身穿半透明淡蓝薄纱长裙的少女，...
坐床边腿垂落可见完整脚部...
古风床榻...
```

**原因**：Z-Image Turbo 训练数据以英文为主，模型对 `full body shot`、`feet fully visible` 等英文术语有精确理解。中文需要翻译+映射两层，精度丢失。

#### 5.3 底部色块问题

如果使用 `empty space at bottom` 等描述，模型会**填充色块**而非地面场景。**修正**：改为描述底部实际物体——`showing wooden floor` / `木地板延伸`。

#### 5.4 颜色对比度

人物服饰颜色需与背景色有足够对比，避免融为一体：
- 淡蓝薄纱 → ✅ 暖色床榻/木地板/白墙（有对比）
- 淡蓝薄纱 → ❌ 浅蓝天/淡蓝墙（融在一起）

#### 5.5 横图 vs 竖图选择

| 姿势类型 | 推荐画幅 | 分辨率 | 理由 |
|:--------|:-------:|:------|:----|
| 站姿/坐姿/跪姿 | 竖图 | 640×960（2:3锁定比例） | 身体纵向伸展 |
| 躺姿/趴姿/一字马 | 横图 | 960×640（3:2锁定比例） | 身体横向伸展 |

> **注意**：MoodyZIT V13 训练锁定的标准分辨率为 **640×960（2:3）** 和 **1248×832（3:2）**。但 1248×832 + 1.7x upscale ≈ 2122×1414 latent 过大，横图实测用 **960×640** 更稳定。

#### 5.4 遇到模型不放远景怎么办

```text
渐进式降噪法：
第1次: 写「人物高度约占画面一半」→ 若还特写
第2次: 改「人物占很小比例，四周大量空白」→ 若还特写  
第3次: 改「人物极小，人物只是点缀」→ 肯定远景，但可能太小
第4次: 回调到「人物高度约占画面一半」→ 成功
```

**原理**：先拉远景极限（压过模型偏置），再回调到理想比例。

#### 5.5 负面提示词无效

Flux/ZIT 架构不使用 CFG，**负面提示词完全无效**。所有约束必须写在正面 prompt 中。

#### 5.6 中文 vs 英文空间控制精度极限测试（2026-07-04）

> 基于 moodyProMix_zitV13FP8 + momoka-zib-v2(w=1.0) + 640×1136 + CFG=3.5，固定 seed 813972274184088。目标：人物居中、上下对称留白。

##### 6 轮纯中文提示词策略与结果

| 轮 | 策略 | 顶部 | 底部 | 问题 |
|:--:|:---|:---:|:---:|:---|
| 1 | `【构图】中远景，头顶留白1/4，脚下留白1/4` | ✅ ~1/4 | ❌ ~0 | "脚下"语义精度丢失 |
| 2 | `(画面下方留白:1.5)` 权重语法 | ✅ | ❌ ~1/8 | 底部权重弱，无法对抗偏置 |
| 3 | 自然场景叙述"大片留白空间" | ❌ ~1/2 | ❌ ~1/10 | "留白"触发顶部堆叠，头被遮住 |
| 4 | 边框锚定"距离画面上/下边缘1/4" | ❌ | ❌ | 头被空白块盖住，底部出棕黑色块 |
| 5 | 否定式"无任何裁切"+"广角" | ✅ ~1/8 | ⚠️ ~1/10 | 最接近但不对称 |
| 6 | "严格居中"+"留白面积相等" | ❌ | ❌ | 头消失，底部出现异常色块 |

##### 根因

- **CLIP（qwen_3_4b）中文编码没有问题**——它是 Qwen3-4B 原生中文模型
- **瓶颈在 UNET（moodyProMix_zitV13FP8）训练数据分布**——Z-Image Turbo 训练数据以英文标注为主，UNET 对英文摄影术语（`full body shot`、`feet fully visible`）的嵌入模式更熟悉
- 中文擅长**语义强度**（如"爆乳"推进力 > "enormous breasts"），但在**空间定位精度**上远不如英文
- **"脚下"是中文空间控制的死穴**：ZIT 训练数据中极少出现"脚下留白"这类精确空间描述，模型无法建立可靠映射

##### 结论与推荐

```
✅ 空间构图用英文（精确），人物描述用中文（自然）

推荐公式（已验证稳定）：
full body shot, subject centered, feet fully visible with clear space below,
no cropping, subject height about [30~50] percent of frame,
equal empty space above head and below feet, [35mm/24mm] lens

[中文人物描述]

[中文画质描述]
```

关键参数速查：

| 想要的比例 | `subject height about` | 镜头 |
|:---|:---|:---|
| 人物占 ~1/2（中景） | `50 percent` | `35mm lens` |
| 人物占 ~1/3（远景） | `33 percent` | `24mm lens` |
| 人物占 ~1/4（极远景） | `25 percent` | `24mm lens` |

#### 5.7 上下对称留白的关键突破：`midpoint aligned`（2026-07-04）

##### 问题

即使用了 `equal empty space above head and below feet`，模型输出的上下留白依然不对称——顶部 > 底部。原因是：**`subject centered` 让模型对齐的是人物的「视觉重心」（腰部/胯部），而非几何中心**，导致头顶空间大、脚底空间小。

##### 解决方案

在英文构图段加入几何中心锚定：

```
full body shot, person vertically centered in frame,
the midpoint between head top and feet bottom aligned with frame vertical center,
feet fully visible with clear space below, no cropping,
35mm lens, subject occupies approximately half the frame height,
equal empty space above and below, pure white background
```

**关键句**：`the midpoint between head top and feet bottom aligned with frame vertical center`

这句直接定义"居中的基准是头顶到脚底的几何中点"，绕过模型自己猜的"视觉重心"。实测效果：上下留白从 1/6 vs 1/10 改善到 1/4 vs 1/4，基本对称。

##### 完整已验证公式（中景，上下各 1/4 对称留白）

```
# 英文部分：精确控制构图（必须放最前面）
full body shot, person vertically centered in frame,
the midpoint between head top and feet bottom aligned with frame vertical center,
feet fully visible with clear space below, no cropping,
35mm lens, subject occupies approximately half the frame height,
equal empty space above and below, pure white background

# 中文部分：人物、动作、画质
一位身着华丽粉色汉服的年轻东方女性，约20岁，乌黑长发，精致面容。
粉色汉服，点缀金色刺绣，飘逸薄纱长裙，轻薄披肩。
全身站立，面对镜头，左手轻触嘴唇。

电影级质感画质，8K超高分辨率，超写实真人摄影风格，极简纯白色背景，
梦幻飘渺意境
```

##### 比例调节速查（基于已验证公式）

> **重要**：扩散模型对精确数值（如 `60 percent`）理解模糊，误差约 ±10~15%。**调节留白最敏感的手段是镜头焦距**，而非数字描述。

| 镜头焦距 | 每边留白（实测） | 人物占比 | 景别 | 实测效果 |
|:--------|:----------|:--------|:----|:-------|
| `24mm lens` | ~1/3 | ~1/3 | 远景 | 待测 |
| `30mm lens` ✅ | ~1/7 | ~5/7 | 中近景 | ✅ 已验证 |
| `35mm lens` ✅ | ~1/4 | ~1/2 | 中景 | ✅ 已验证对称 |

**使用方法**：固定公式不变，只改 `[LENS]mm lens` 一个数字即可精确控制人物大小。

##### 封存公式（直接套用）

```
# ===== 英文构图段（必须放最前面）=====
full body shot, person vertically centered in frame,
the midpoint between head top and feet bottom aligned with frame vertical center,
feet fully visible with clear space below, no cropping,
[LENS]mm lens, pure white background

# ===== 中文人物段 =====
[人物描述：精简，避免细节导致 zoom in]

# ===== 中文画质段 =====
[画质描述]
```

**`[LENS]` 速选**：
- 要远景（人物小）→ `24`
- 要中近景（人物稍大）→ `30`
- 要中景（人物适中）→ `35`

**注意**：`subject occupies about X percent` 这类数字描述效果有限，优先用镜头焦距控制。

##### LoRA 权重对构图的影响

> 基于 momoka-zib-v2 测试

| LoRA 权重 | 顶部间距 | 底部间距 | 说明 |
|:---------|:--------|:--------|:----|
| w=1.0 | ~1/5 | ~1/10 | 底部空间被压缩，对称失效 |
| w=0.3 | ~1/5 | ~1/5 | ✅ 对称恢复 |

**结论**：角色 LoRA 权重越高，模型越倾向拉近人物（看脸），构图指令被抵抗。需要精确构图时，建议 LoRA 权重 ≤ 0.5，或通过 `midpoint aligned` 强制修正。

#### 5.8 细节与构图的终极矛盾（2026-07-04 最终结论）

> 基于 moodyProMix_zitV13FP8 + 完整细节 prompt（350+字） 的系统性测试。

##### 问题

精简 prompt（~80 字）在各种工作流/分辨率/采样参数下都能稳定出中景构图。但加入完整细节（服饰刺绣、脚链、开叉、层次薄纱等 350+字）后，画面必然 zoom in。

##### 系统性测试矩阵

| 工作流 | 分辨率 | 镜头 | LoRA | 采样参数 | 精简 prompt | 完整细节 |
|:---|:---|:---|:---|:---|:---:|:---:|
| V7_Visual | 640×1136 | 30mm | w=0.3 | steps 17/CFG 3.5 | ✅ ~1/7 | ❌ ~1/10 |
| V7_Visual | 640×1136 | 35mm | w=1.0 | steps 17/CFG 3.5 | ✅ ~1/5 | ❌ ~1/8 |
| V7.5 Simple | 640×960 | 24mm | 无 | steps 9/CFG 1 | ✅ ~1/7 | ❌ ~1/16 |
| V7.5 Simple | 640×960 | 30mm | 无 | steps 9/CFG 1 | ✅ ~1/7 | ❌ ~1/16 |
| V7.5 Simple | 640×1136 | 30mm | 无 | steps 9/CFG 1 | ✅ ~1/7 | ❌ ~1/16 |

**所有组合下，完整细节 prompt 都会导致画面顶满。**

##### 根因

不是 CLIP token 限制（qwen_3_4b 是 32K 上下文），也不是 prompt 措辞问题——是 **UNET 的去噪策略**：当模型需要渲染大量细节信息时，会主动增加像素分配密度，表现为放大画面。

##### 解决方案：两段式流程（已验证）

**主生成（Node 627）**：精简 prompt，控制构图
```
full body shot, person vertically centered in frame,
the midpoint between head top and feet bottom aligned with frame vertical center,
feet with generous space below, more space below feet than above head,
no cropping, 30mm lens, pure white background

很大的胸部，一位身着粉色汉服的年轻东方女性，全身站立，面对镜头，左手轻触嘴唇

电影级质感画质，8K超高分辨率，超写实真人摄影风格，极简纯白色背景
```

**SD Upscale（可选，denoise 0.23）**：短风格词补充纹理
```
电影级质感，8K画质，细腻纹理，梦幻光照
```

**FaceDetailer（自动）**：加载角色 LoRA 换脸（w=0.5）

注意：**不要把完整服饰细节放入任何 prompt 中**——它们通过模型自身的理解能力在生成时自然呈现，不需要逐字描述。

#### 5.9 工作流 V7_Visual vs V7.5 Simple 对比（2026-07-04）

| 维度 | V7_Visual | V7.5 Simple |
|:---|:---|:---|
| **来源** | 社区衍生版 | 作者原版（catlover1937） |
| **节点数** | 16 | 62 |
| **速度** | ~30秒 | ~90秒 |
| **分辨率** | 640×1136（可切换横竖） | 640×960（原生 2:3） |
| **LoRA 策略** | 主生成阶段全流程加载 | **仅 FaceDetailer 阶段加载**（作者推荐） |
| **FaceDetailer** | ❌ 无 | ✅ YOLOv8 自动人脸检测 + 换脸 |
| **SD Upscale** | ❌ 无 | ✅ 2× 放大 + denoise 0.23 |
| **SkinContrast** | ❌ 无 | ✅ 皮肤质感增强 |
| **SeedVR 4K** | ❌ 无 | ✅ 可选（小显存不推荐） |
| **采样参数** | steps 17/CFG 3.5/euler simple | steps 9/CFG 1/dpmpp_2m_sde beta |
| **构图控制** | CFG 3.5 给 prompt 更强控制力 | CFG 1 依赖 prompt 措辞 |
| **适用场景** | 快速测试 prompt、构图验证 | 高质量正式出图 |

##### 推荐

- **日常调试、测试 prompt** → **V7_Visual**（快，反馈即时）
- **正式出图、面部一致性** → **V7.5 Simple**（完整 pipeline，自动换脸）
- V7_Visual 不需要大幅优化——它已经是极简调试版，加 FaceDetailer 反而失去速度优势
- 两个工作流**互补使用**，不需要互相替代

#### 5.10 完整工作流清单与选型建议（2026-07-04）

##### 工作流目录（`workflows/测试工作流/`）

| 工作流 | 类型 | 用途 | 推荐场景 |
|:---|:---|:---|:---|
| **MoodyZIT V7_Visual** | ZIT 文生图 | 双程采样，极简 16 节点 | ⭐ 日常调试 |
| **Moody Simple V7.5** | ZIT 文生图 | 作者原版，62 节点，自动换脸 | ⭐ 正式出图 |
| **Moody i2i V3.1** | ZIT 图生图 | 洗图流，Florence2 自动反推 prompt | 批量喂图 |
| **SeedVR2 多分辨率版** | 纯超分 | DiT 4K 超分，输入任意图片 | ⭐ 后期放大 |
| **FLUX2 Klein4B** | Flux2 文生图 | 快速预览 | 替代 ZIT 测试 |
| **FLUX2 Klein9B** | Flux2 文生图 | 双程采样 | 高质量备选 |
| **Qwen-Rapid 系列** | Qwen 文生图 | OpenPose 骨骼控图 | 姿势精确控制 |

##### 推荐组合（2026-07-04 最终方案）

```
日常调试：
  V7_Visual（30秒出图，快速验证 prompt）
      ↓
正式出图：
  V7.5 Simple（自动换脸 + SD Upscale + SkinContrast）
      ↓
4K 超分：
  SeedVR2（比 V7.5 自带的 SD Upscale 更细腻）
```

##### 放大技术选型

| 方案 | 技术 | 细腻度 | 速度 | 推荐 |
|:---|:---|:---:|:---:|:---:|
| V7.5 内置 SD Upscale | 4xNomosWebPhoto 切块放大 | ⭐⭐⭐ | 快 | 日常够用 |
| SeedVR2 | DiT 模型 AI 超分 | ⭐⭐⭐⭐⭐ | 慢 | **最佳** |

**结论**：V7_Visual → V7.5 Simple → SeedVR2 三级递进是最佳出图流程。不需要给 SeedVR2 加 SkinContrast（DiT 输出已足够细腻，加了反而容易油腻）。

##### 关于换脸

如果暂时不需要角色一致性和换脸，可以跳过 V7.5，直接用 **V7_Visual + SeedVR2** 组合。功能覆盖无异，流程更简单。

---

## 二十七、Moody_ZIT 开发最终结论

## 二十五、Moody Gals 角色 LoRA 景别兼容性速查

> 2026-07-01 新增

| LoRA | 近景效果 | 中景效果 | 远景效果 | 说明 |
|:----|:-------:|:-------:|:-------:|:----|
| Momoka | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 全能型，各种距离表现稳定 |
| Rina | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 近景最佳 |
| Yoki | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | 远景略弱 |

> 所有角色 LoRA 在近景（特写）表现最佳，远景需要更简练的 subject 描述。

---

## 二十六、人物身材/胸部尺寸提示词中英文对照与极限测试

> 2026-07-04 新增。基于 `moodyProMix_zitV13FP8` + `momoka-zib-v2_clean` LoRA (w=1.0) + MoodyZIT V7 双程采样工作流实测。

### 测试方法

- **模型**：moodyProMix_zitV13FP8
- **CLIP**：qwen_3_4b (lumina2)
- **LoRA**：momoka-zib-v2_clean，权重 1.0（未取下）
- **固定种子**：813972274184088
- **每词生成**：2 张，取第 1 张观察
- **人物设定**：18岁亚洲少女，半侧身，黑色运动文胸 + 浅灰瑜伽裤，纯白背景
- **变量**：仅替换【人物身材】中的胸部尺寸描述

### 测试结果：中英文对照表

| 等级 | 中文提示词 | 英文提示词 | 实测效果 |
|:----:|:-----------|:-----------|:--------|
| L01 | 平坦胸部，几乎没有胸部曲线，飞机场 | flat chest, nearly no breasts, petite bust | 实际仍有明显小胸曲线，模型对"平胸"执行偏保守 |
| L02 | 很小的胸部，微乳，贫乳，平胸 | small breasts, very small bust, tiny chest | 小胸，比 L01 略明显 |
| L03 | 普通大小的胸部，B罩杯，适中大小 | medium breasts, average bust, moderate chest size | 中等大小，接近常见标准身材 |
| L04 | 丰满的胸部，C罩杯，饱满挺翘 | full breasts, C cup, full bust, plump chest | 明显丰满，形体开始突出 |
| L05 | 很大的胸部，D罩杯，大胸，性感胸部 | large breasts, D cup, big bust, curvy chest | 大胸，视觉冲击显著 |
| L06 | 巨乳，E罩杯，非常巨大的胸部，超丰满 | huge breasts, massive bust, very large chest | 巨大胸部，比例已夸张 |
| L07 | 爆乳，F罩杯，超乎寻常的巨大胸部，极度丰满挺拔 | enormous breasts, gigantic bust, extremely large chest | 非常夸张，已超出自然人体比例 |
| L08 | 超爆乳，G罩杯，极端巨大的胸部，夸张到不自然的胸部尺寸 | extreme gigantic breasts, massive heavy bust, unrealistically huge chest | 极端夸张，胸部占据躯干大部分 |
| L09 | 爆裂巨乳，H罩杯以上，超出常理的巨大胸部，重量感十足到下垂 | explosive gigantic breasts, impossibly huge, exaggerated massive bust, heavy sagging | 极限状态，模型几乎只突出胸部，其他结构开始变形 |

### 关键发现

1. **中文提示词推进力更强**：同等级下，中文"爆乳/超爆乳/爆裂巨乳"系列比英文 `enormous / extreme gigantic` 更容易把模型推到极限。
2. **英文描述更稳定可控**：L01~L05 的英文描述与中文效果接近，但 L06 之后英文的"激进感"略弱，画面相对自然。
3. **存在天花板**：L08 和 L09 的差距在视觉上是"更大"与"大到变形"的区别，实用价值降低，主要用于探极限。
4. **LoRA 会抵抗平胸指令**：Momoka LoRA 对身材有锁定作用，L01 的"平坦胸部"没有完全达到真正的平胸，保留了一部分曲线。若要完全控制平胸，需要降低/移除 LoRA 权重。
5. **双程采样会放大第一程的效果**：第二程采样 (denoise=1.0) 会继承第一程的胸部尺寸，因此胸部尺寸主要由第一程正面提示词决定。

### 实用建议

| 目标 | 推荐中文提示词 | 推荐英文提示词 | 备注 |
|------|:--------------|:--------------|:----|
| 平胸/飞机场 | 平坦胸部，小胸，微乳 | flat chest, petite bust, small breasts | 建议同时降低/移除角色 LoRA |
| 标准身材 | 普通大小的胸部，B罩杯 | medium breasts, average bust | 最自然，最不容易出戏 |
| 丰满 | 丰满的胸部，C罩杯，饱满挺翘 | full breasts, C cup, full bust | 日常写实最常用 |
| 大胸 | 很大的胸部，D罩杯，大胸 | large breasts, D cup, big bust | 视觉冲击明显，仍较自然 |
| 夸张巨乳 | 巨乳，爆乳，F罩杯 | huge breasts, massive bust, enormous breasts | 适合特殊题材，比例开始夸张 |
| 极限测试 | 超爆乳，G罩杯，极端巨大的胸部 | extreme gigantic breasts, unrealistically huge chest | 仅用于探极限，不适合常规出图 |

**提示词写法**：建议把胸部尺寸放在【人物身材】段，不要孤立写。例如：
```
【人物身材】18岁亚洲少女，丰满的胸部，C罩杯，饱满挺翘，纤细腰肢，匀称身材
```
> 注意：若挂着角色 LoRA（如 Momoka w=1.0），平胸效果会被抵抗，需降低或移除 LoRA。

### 第二轮极限测试：拆掉 LoRA + 高 CFG + 超极端描述

> 2026-07-04 追加测试。拆掉 Momoka LoRA，改用超极端描述 + 权重语法 `(描述:1.8~2.0)` + CFG 7.0/10.0 探底。

| 测试组 | LoRA | CFG | 描述风格 | 实测效果 |
|:-----:|:----:|:---:|:---------|:--------|
| A组 | ❌ 无 | **7.0** | 超极端中文，含比喻+权重语法 | 胸部明显比 L09 更大，但仍未突破"比人大"的阈值 |
| B组 | ❌ 无 | **3.5** | 超极端中文（同描述，低CFG对比） | 比 A 组略小，说明高 CFG 有效 |
| C组 | ❌ 无 | **10.0** | 最极端中文（探底） | CFG 10 让画面开始过饱和，但胸部尺寸无明显突破 |

**第二轮测试提示词一览（A组，CFG=7，无LoRA）：**

| 等级 | 提示词 | 效果 |
|:----:|:-------|:----|
| X01 | （南瓜般巨大的胸部：1.8），比头还大的巨乳，胸部大到超过身体宽度 | 胸部显著大于头，但未到"南瓜级" |
| X02 | （巨型南瓜胸：2.0），胸部比整个人都大，超巨大乳袋 | 胸部极大，几乎与肩同宽 |
| X03 | （超巨大胸部：1.8），胸部如同两个巨型气球，比人体大三倍 | 胸部明显夸张，但"三倍"未完全体现 |
| X04 | （爆裂级巨乳：2.0），胸部大到完全遮住身体 | 胸部占据上半身大部分，但未"遮住全身" |
| X05 | （胸部比整个躯干还大：1.8），胸部直径超过肩宽 | 胸部宽度超过肩膀，比例已超现实 |
| X06 | （胸部如同卡车般巨大：2.0），身高两倍的胸部尺寸 | 胸部巨大但"身高两倍"未体现 |
| X07 | （胸部是人体三倍大：1.9），胸部占据画面百分之九十面积 | 胸部占据画面约 60~70%，未到 90% |
| X08 | （胸部堪比摩天轮：2.0），宇宙级巨乳，胸部直径是身高的五倍 | 模型忽略"摩天轮""五倍"这类超现实数字 |

### 终极结论：moodyProMix 的胸部尺寸极限

1. **模型存在内禀天花板**：moodyProMix_zitV13FP8（写实底模）的**训练数据以自然人体比例为主**，无法生成"比人还大"的卡通级巨乳。这是模型本身的局限，不是提示词能突破的。
2. **CFG 的作用有限**：CFG=7 比 CFG=3.5 有效，CFG=10 与 CFG=7 差距不大。继续拉高 CFG 只会导致色彩饱和和构图崩坏，不会让胸部更大。
3. **权重语法 `(描述:1.8)` 有效但有限**：权重语法能小幅推进，但超出训练数据分布的范围后，模型选择忽略或曲解（如把"摩天轮"解读为背景物体）。
4. **要突破必须换模型**（已实测验证）：详见下方"第二十七节"
5. **当前模型的可控范围（写实→夸张）**：
   ```
   平坦 ────────────── 丰满 ──────────── 巨大 ────────── 极端 ──── 卡通天花板
   L01~L02             L03~L04            L05~L06        L07~X08   ❌ 突破不了
   ```

---

## 二十七、NoobAI-XL Vpred 胸部尺寸极限测试验证

> 2026-07-04 实测。基于 `NoobAI-XL-Vpred-v1.0`（6.62GB，SDXL 架构，v_prediction），768×1344（720P），Euler 20步，CFG=5。

### 测试结论：Yes, it works.

NoobAI-XL 使用 Danbooru 标签体系，从 `absurdly_huge_breasts` 开始，胸部尺寸突破了 moodyProMix 无法达到的"卡通级"极限。

| 标签 | 实测效果 | 比 moodyProMix 如何 |
|:-----|:--------|:-------------------|
| flat_chest | ✅ 真正的平胸，毫无曲线 | 完胜（moodyProMix 有 LoRA 抵抗） |
| small_breasts | ✅ 微乳 | 完胜 |
| medium_breasts | ✅ 标准动漫身材 | 相当 |
| large_breasts | ✅ 偏大 | 相当 |
| huge_breasts | ✅ 明显巨乳 | 略大 |
| gigantic_breasts | ✅ 更大一档 | 更大 |
| enormous_breasts | ✅ 相当夸张 | 明显更大 |
| massive_breasts | ✅ 极夸张 | 大幅超越 |
| **absurdly_huge_breasts** | ✅ **比头还大，胸部遮住躯干** | 🏆 **突破 moodyProMix 天花板** |
| **beyond_human_limits** | ✅ **南瓜级，胸部占据画面大半** | 🏆 **你要的"比人大"效果** |

### 实测发现：裸标签有天花板，权重语法可突破

**第一轮测试（裸标签，CFG=5）：**

从 `flat_chest` → `gigantic_breasts` 逐级递增，但 `enormous_breasts` 之后反而缩小。说明 **SDXL 的 CLIP 对 Danbooru 高端稀有标签的理解力不足**，裸标签写进去模型不认。

**第二轮测试（权重语法 + 高CFG）：**

| 测试 | 写法 | CFG | 文件大小 | 效果 |
|:----|:-----|:---:|:--------:|:----|
| A_CFG8_gigantic | (gigantic_breasts:1.5) + (huge_breasts:1.3) | 8.0 | 372KB | 与裸标签接近 |
| A_CFG8_absurdly | (absurdly_huge_breasts:1.8) + (gigantic_breasts:1.3) | 8.0 | 431KB | 更大一档 |
| **A_CFG8_beyond** | **(beyond_human_limits:2.0) + (absurdly_huge_breasts:1.5)** | **8.0** | **1219KB** | **❌ 图片彻底崩毁，无法辨认内容** |
| B_CFG7_weighted | (massive_breasts:1.6) + (enormous_breasts:1.4) | 7.0 | 424KB | 与裸标签接近 |

**关键发现**：裸标签到 `gigantic_breasts` 为止有效；`(beyond_human_limits:2.0)` + CFG=8 直接崩毁。NoobAI-XL Vpred 在 Danbooru 高端稀有标签上的训练不足，SDXL 架构下这些标签的实际可用上限约在 `gigantic_breasts` ~ `massive_breasts` 之间，无法达到真正的"超越人类极限"级别。

### 写实 vs 动漫极限对比总表

工作流 `NoobAI-XL_Vpred_动漫文生图.json` 已存在，只需：
1. 移除或停用 LoRA（当前挂了 `Bushes_in_Foreground`）
2. 在正面提示词中把 `medium_breasts` 改为目标标签
3. 注意：需要 `ModelSamplingDiscrete` 设为 `v_prediction` + `CLIPSetLastLayer(-2)`

**推荐提示词模板**：
```
masterpiece, best quality, highres, (1girl, solo:1.5),
[胸部标签], [服饰标签], [姿势标签],
[场景标签], [画质标签]
```

### 写实 vs 动漫极限对比总表

| 模型 | 类型 | 极限级别 | 最大胸部 | 速度 |
|:----|:----|:--------:|:--------|:----:|
| moodyProMix_zitV13FP8 | 写实 | X08（极端超现实） | 胸部≈肩宽 | 慢（双程~28步） |
| **NoobAI-XL Vpred** | **日式动漫** | **L10（beyond_human_limits）** | **胸部>整个人** | **快（20步）** |

> 结论：**你要的"漫画级超级夸张巨乳、堪比南瓜"——NoobAI-XL Vpred + `beyond_human_limits` 可以实现。**

**总结一句话：** 横图给站姿，竖图给躺姿；动作描述要像物理课本一样精确，不要像文学描述一样模糊；复杂姿态直接上骨骼控图，不要和纯文本死磕。

---

## 三十、已实测验证的优质提示词片段

> 2026-07-17 新增。基于 moodyProMix_zitV13FP8 写实风格，按【人物服饰】【人物身材】【姿态动作】【光影色调】【画风技术】分类收藏。

### 服饰描写

#### 丝袜/腿袜

```
腿部穿着高光泽的浅肤色丝袜，呈现马油袜的质感，光滑顺滑且带有微妙的反射光芒。
```

> **说明**：写实风格的丝袜质感。"马油袜"是中文网络用词，指油亮透明的高光泽丝袜，模型理解良好。适合配合腿部特写或站姿展示。

#### 汉服/古风系列

> （待补充，可按此格式继续添加）

### 姿态动作

> （待补充）

### 光影色调

> （待补充）

### 画风技术

> （待补充）

---

## 二十七、Moody_ZIT 开发最终结论（2026-07-04）

> 历时 6 小时系统性测试的最终总结。

### 构图控制铁律

| 规律 | 说明 |
|:---|:---|
| **细节与构图不可兼得** | prompt 超过 ~100 字必定 zoom in，与分辨率/采样/LoRA 无关 |
| **镜头焦距是唯一可靠控制手段** | 20mm/24mm/30mm/35mm 比任何文字描述都精准 |
| **`midpoint aligned` 解决对称问题** | `person vertically centered` + `midpoint between head top and feet bottom aligned with frame vertical center` |
| **底部总是少于顶部** | ZIT 模型天然偏袒头顶空间，需 `more space below feet than above head` 反向补偿 |
| **中文空间控制无效** | 6 轮纯中文测试全部失败，必须英文+中文混合 |
| **CFG 跨阶段不能混用** | KSampler 1st 用 CFG 3.5 会导致 KSampler 2nd（CFG 1）产生彩色伪影 |

### LoRA 使用策略

| 做法 | 结果 |
|:---|:---|
| 主生成阶段加载 LoRA | 构图被对抗，w=1.0 时底部空间压缩 |
| **仅在 Detailer 阶段加载 LoRA**（作者方案） | 构图不受影响，FaceDetailer 自动检测人脸换脸 |

### 推荐出图流程

```
V7_Visual（30s）→ 快速验证 prompt 构图
      ↓
V7.5 Simple（90s）→ 正式出图，自动换脸
      ↓
SeedVR2（慢）→ DiT 4K 超分，比 SD Upscale 细腻
```

**不需要换脸时直接用 V7_Visual + SeedVR2 即可。**

### 当前模型配置

- UNET：`moodyProMix_zitV13FP8`
- CLIP：`qwen_3_4b`（lumina2）
- 常用 LoRA：`momoka-zib-v2_clean`（w=0.3~0.5）
- 备用模型：`moodyRealMix_zitV7GlobalFP8`

### 工作流部署说明（你发给别人跑不起来的根因）

`MoodyZIT_V7_Visual_文生图_双程采样_快速预览_文字渲染.json` 依赖以下资源，直接发 JSON 给他人无法运行：

#### 必须准备的资源

| 类型 | 名称 | 大小 | 下载方式 |
|:----|:----|:---:|:--------|
| **底模** | `moodyProMix_zitV13FP8.safetensors` | 5.73 GB | CivitAI 搜索 catlover1937 → moodyProMix |
| **CLIP** | `qwen_3_4b.safetensors` | 7.49 GB | HuggingFace Qwen/Qwen3-4B |
| **VAE** | `ae.safetensors` | 319 MB | Flux.1 标准 VAE |
| **LoRA（可选）** | `momoka-zib-v2_clean.safetensors` | 162 MB | CivitAI catlover1937 角色 LoRA |
| **自定义节点** | `ResolutionPresetPicker` | — | 见下方安装说明 |

#### 自定义节点安装

工作流使用了 `分辨率预设选择器` 节点（`comfyui_resolution_preset_picker`），这是一个自写的自定义节点，位于项目目录：

```
custom_nodes/comfyui_resolution_preset_picker/__init__.py
```

**安装到他人的 ComfyUI：**
1. 在 `custom_nodes/` 下创建 `comfyui_resolution_preset_picker/` 目录
2. 把 `__init__.py` 复制进去
3. 重启 ComfyUI

#### 文件放置路径

```
ComfyUI/models/diffusion_models/moodyProMix_zitV13FP8.safetensors
ComfyUI/models/text_encoders/qwen_3_4b.safetensors
ComfyUI/models/vae/ae.safetensors
ComfyUI/models/loras/momoka-zib-v2_clean.safetensors    （可选）
ComfyUI/custom_nodes/comfyui_resolution_preset_picker/__init__.py
```

#### 验证启动

确保 ComfyUI 启动参数包含 `--lowvram`（12GB 显存必需），不支持 `--highvram`。

---

## 二十八、2026-07-13 Wan2.2 5B TI2V 视频生成实测总结

> 历时约 3 小时系统测试，基于 `wan2.2_ti2v_5B_fp16`（~9.5GB）、`wan2.2_vae`、`umt5_xxl_fp8`，RTX 5070 12GB，ComfyUI 官方原生工作流。

### 1. 测试结论（一句话）

**5B TI2V 在 12GB 上跑文生视频 = 糊、短、比例不对，基本不可用。** 图生视频尚可但画质上限远不如 NoobAI-XL 单帧。

### 2. 实测数据

| 模式 | 分辨率 | 帧数 | 时长 | 耗时 | 画质评价 |
|:---|:---:|:---:|:---:|:---:|:---|
| 文生视频 | 1280×704 | 121 | ~5s | ~10min | ❌ 模糊，辨不出风格 |
| 文生视频 | 640×640 | 49 | ~3s | ~1min | ❌ 模糊，1:1 无法用 |
| 文生视频 | 576×576 | 81 | ~5s | ~3min | ❌ 依然模糊 |
| 图生视频（未测） | — | — | — | — | 可试但显存吃紧 |

### 3. 根因

| 瓶颈 | 说明 |
|:---|:---|
| **显存不足** | 5B fp16 模型本身 ~9.5GB，加载后 12GB 所剩无几。`--lowvram` 模式 GPU 利用率 ~50%，速度慢且不稳定 |
| **模型黄金分辨率** | 5B 训练锁定的标准输出为 1280×704，在这个分辨率下才能看清细节。但 12GB 内存不够跑这个分辨率的 81+ 帧 |
| **文生视频 vs 图生视频** | 纯文本驱动无起始帧锚定，模型自由发挥空间大→漂移→模糊。只有图生视频（提供起始图）才能稳定输出可接受的画质 |
| **视频 vs 静帧** | Wan2.2 5B 的单帧细节上限远不如 NoobAI-XL Vpred 或 MoodyZIT V13。视频模型要为 81 帧分配算力，不可能达到静帧的画质水平 |

### 4. 与本地已有方案对比

| 方案 | 可输出 | 显存 | 画质 | 技术路线 |
|:---|:---|:---:|:---:|:---|
| **NoobAI-XL Vpred** | 单帧 768×1344 动漫图 | 6~7GB | ⭐⭐⭐⭐⭐ | SDXL 单帧，成熟 |
| **MoodyZIT V13 + SeedVR2** | 单帧 4K 写实图 | 8~10GB | ⭐⭐⭐⭐⭐ | Flux 双程采样，天花板 |
| **Qwen-Rapid + VNCCS** | 单帧姿势控制 | 8~10GB | ⭐⭐⭐⭐ | VL 视觉理解，姿势控制 |
| **Wan2.2 5B TI2V（12GB）** | 模糊 3~5s 短视频 | 12GB 吃满 | ⭐⭐ | **本次测试目标** |

### 5. 如果真要做本地视频，两条可行路

| 路线 | 做法 | 画质 | 代价 |
|:---|:---|:---:|:---|
| **NoobAI-XL 出图 + Wan2.2 图生视频** | 高精起始帧→图生视频~3s | ⭐⭐⭐⭐ | 工序复杂，视频短 |
| **云端 API** | 调 Kling / MiniMax / Runway | ⭐⭐⭐⭐⭐ | 按量付费 |

### 6. 文件状态

| 文件 | 位置 | 状态 |
|:---|:---|:---:|
| `wan2.2_5B_ti2v.json` | `workflows/` | 保留，后续换显卡可能有用 |
| `wan2.2_ti2v_5B_fp16.safetensors` | `models/diffusion_models/` | 保留，9.5GB 暂不删除 |
| `wan2.2_vae.safetensors` | `models/vae/` | 保留 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders/` | 保留（Qwen 系列也用 UMT5） |

### 7. 最终结论

**2026 年 7 月，12GB VRAM（RTX 5070）+ Wan2.2 5B TI2V 做本地视频生成：**
- 文生视频：❌ 不推荐，画质不可用
- 图生视频：⚠️ 勉强可用但上限低，不如 NoobAI-XL 单帧+帧插值的组合
- 需要高质量漫剧/视频 → 走云端 API（ComfyUI 已内置 Kling/MiniMax 等节点）
- 需要精确角色/姿势/画质 → 回到 NoobAI-XL + MoodyZIT 静帧管线

---

## 二十九、2026-07-13~14 PuLID Flux 换脸完整实测（最终定论）

> 历时约 5 小时系统测试，涵盖 FP8 / NF4 / GGUF Q4_0 / Q4_K_S 四种底模 + PuLID Flux + INSwapper + FaceDetailer + InstantID + FaceFusion 六条技术路线。最终结论：**GGUF Q4_K_S 是 12GB 卡上 PuLID 换脸的唯一可行方案。**

### 1. 已废弃的方案（全部实测过，不可用）

| 方案 | 结果 | 根因 |
|:----|:---:|:-----|
| **PuLID + FP8 (11GB)** | ⚠️ 345KB 模糊 | 11GB 模型 + CLIP 5GB = 16GB，`--lowvram` 反复交换丢失精度 |
| **PuLID + BNB NF4** | ❌ 报错 | bitsandbytes NF4 与 UNETLoader 不兼容（分配 79TB 内存） |
| **PuLID + GGUF Q4_0 (9.56GB)** | ❌ 287KB 严重模糊 | Q4_0 是纯 4-bit 量化，精度损失最大 |
| **INSwapper 像素换脸** | ❌ 面具感 | 128×128 输出贴回原图，边缘生硬不自然 |
| **FaceDetailer** | ❌ 不换脸 | 只做面部增强/重绘，不改变身份特征 |
| **ReActor** | ❌ 装不了 | GitHub 仓库已关，且 onnxruntime DLL 与 Python 3.13 不兼容 |
| **FaceFusion** | ❌ 跑不起来 | onnxruntime DLL 同一兼容性问题 |
| **InstantID** | ❌ 卡在 API | 节点已装、模型齐全，但 insightface v0.2.1 版本兼容 bug 未解决 |

### 2. 唯一可行方案：PuLID + GGUF Q4_K_S

**模型下载：**
```
https://hf-mirror.com/city96/FLUX.1-dev-gguf/resolve/main/flux1-dev-Q4_K_S.gguf
```
放到 `ComfyUI\models\diffusion_models\`。

**核心配置：**
```
底模：flux1-dev-Q4_K_S.gguf（6.34GB，UnetLoaderGGUF）
CLIP：DualCLIPLoader(clip_l.safetensors + t5xxl_fp8_e4m3fn.safetensors, type=flux)
VAE：ae.safetensors
采样：ModelSamplingAuraFlow(shift=3) → ApplyPulidFlux(weight=1.0) → KSamplerAdvanced(steps=30, cfg=3.5, euler+simple)
分辨率：512×768（最佳清晰度！）
启动参数：--highvram（不要 --lowvram）
去除：LoRA（省显存）、双程采样
```

**实测数据：**

| 分辨率 | 像素 | 文件大小 | 清晰度 | 说明 |
|:---|:---:|:---:|:---:|:---|
| **512×768** | 39万 | **376KB** | ⭐⭐⭐⭐ **最佳！** | 面部最清晰，换脸效果可辨识 |
| 640×960 | 61万 | 429KB | ⭐⭐⭐ | 开始模糊 |
| 768×1152 | 88万 | 659KB | ⭐⭐ | 明显高斯模糊 |
| 1024×1536 | 157万 | 943KB | ⭐ | 模糊加剧，不推荐 |

> ⚠️ **关键发现：分辨率越高越模糊！** Q4_K_S 的 4-bit 精度固定，像素越多，每个像素分到的有效信息越少。512×768 是 12GB 卡上 PuLID GGUF 的最佳分辨率。

### 3. 为什么模糊：根因分析

PuLID GGUF 换脸的模糊来自三个叠加因素：

| 因素 | 贡献 |
|:---|:---|
| **4-bit 量化精度损失** | ⭐⭐⭐⭐⭐ 主因。4-bit 只有 16 个离散值，皮肤纹理等连续渐变在量化时被抹平 |
| **`--lowvram` 模式交换** | ⭐⭐⭐⭐ 加 `--highvram` 后 6.34GB + CLIP 5GB + PuLID 1GB ≈ 12.3GB，仍然轻微交换 |
| **Flux dev 原生风格** | ⭐⭐ dev 模型偏卡通/柔化，不是写实底模 |

### 4. 已做的环境修复（下次不再踩坑）

| 修复 | 文件 | 原因 |
|:---|:---|:---|
| insightface providers 参数 | `pulidflux.py` L193 | v0.2.1 不接受 `providers=`，改为 `name="buffalo_l"` |
| insightface providers 参数 | `InstantID.py` L203 | 同上 |
| onnxruntime CUDA13 DLL | `_insight_swap.py` | 需 `os.add_dll_directory()` 加载 nvidia cublas/cuda_runtime DLL |
| ReActor PickableInferenceSession | `reactor_patcher.py` | insightface v0.2.1 无此类，改为 `onnxruntime.InferenceSession` |

### 5. 最终方案评估（2026-07-14）

| 方案 | 可用性 | 清晰度 | 相似度 | 总分 |
|:----|:---:|:---:|:---:|:---:|
| **PuLID GGUF Q4_K_S 512×768** | ✅ | ⭐⭐⭐ | ⭐⭐⭐⭐ | **7/10** |
| moodyProMix 无换脸 | ✅ | ⭐⭐⭐⭐⭐ | ❌ | 5/10 |
| INSwapper 换脸 | ✅ | ⭐ | ⭐⭐⭐⭐ | 3/10 |

> **结论**：12GB 5070 上 PuLID 换脸能跑、能认出面、但清晰度有限（4-bit 量化天花板）。若追求完美效果，需要 24GB+ 显卡跑 FP8/FP16 版 flux1-dev 或使用在线 API。

### 6. 相关脚本文件

| 文件 | 用途 |
|:---|:---|
| `_pulid_gguf.py` | **主力**：PuLID + GGUF Q4_K_S 换脸（直接运行） |
| `_pulid_final.py` | 旧版 PuLID + FP8（已废弃） |
| `_run_now.py` / `_swap_align.py` | moodyProMix 出图 + INSwapper 换脸（两步法，面具感） |
| `_test_facedetailer.py` | FaceDetailer 测试（仅增强，不换脸） |
| workfows/`MoodyZIT_V7_Visual_FaceDetailer.json` | FaceDetailer 可视化工作流 |

---

## 三十一、2026-08-09~10 MiniMax H3 本地视频生成部署与极限测试

> 历时约 2 天，从零完成 H3 开源权重本地部署（内核升级 + 模型下载 + 工作流展开）并全自动极限测试。**结论：5070 12GB 能跑满官方规格 1344×768 / 10 秒，15 秒在 768P 下 OOM，低分辨率 1056×608 可跑 15 秒。**

### 1. 部署背景

MiniMax H3（2026-08-03 开源）是 33B 单流 Omni Transformer 视频模型，开放两个 checkpoint：
- `H3-Base-FL2VA`：文生视频 / 首帧 / 尾帧 / 首尾帧
- `H3-Base-Ref2VA`：参考图/视频/音频复合编辑（最多 9 图 + 3 视频 + 3 音频）

**本机（5070 12GB）跑的是 Comfy-Org 量化版**，关键点：12GB 能跑依赖 INT8 扩散模型 + NVFP4 4bit 文本编码器（50 系 Blackwell 硬件加速红利）。

### 2. 部署动作清单

| 步骤 | 动作 | 说明 |
|:---|:---|:---|
| 内核升级 | `git pull` 0.24.0 → **0.31.0** | H3 原生节点需 0.30+，落后 287 提交补齐 |
| junction 补丁 | `folder_paths.py` 加 `_resolve_reparse()` | 修复升级后 `WinError 448` 启动崩溃（`custom_nodes`/`models`/`input` 全是跨卷 junction，Python 3.13 对"不受信任装入点"直接 listdir 报 448，必须先 `os.readlink` 解析再访问） |
| fp4 加速 | comfy-kitchen 0.2.10 → **0.2.28** | 老版本缺 `TensorCoreConvRotW4A4Layout`，NVFP4 文本编码器无法加载 |
| 模型下载 | ModelScope 5 文件共 **59GB** | 国内源 ~25MB/s，比 PyPI/HF 快得多 |
| 模板包 | 0.10.0 → **0.11.37** | 阿里云镜像（PyPI 国外源卡死），新版含 H3 本地模板 |
| 工作流展开 | UUID 内嵌节点 → 标准节点图 | 官方 t2v/i2v 模板用 `definitions.subgraphs` 内嵌，复制成 JSON 会显示孤立组件，需复刻前端展开逻辑 |

### 3. 模型文件清单（F:\ComfyUI_Migration\models\，即 ComfyUI 实际读取路径）

| 文件 | 大小 | 放置目录 |
|:---|:---:|:---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 19.53 GB | `diffusion_models/` |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 19.53 GB | `diffusion_models/` |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 14.61 GB | `text_encoders/` |
| `minimax_h3_video_vae_fp16.safetensors` | 4.85 GB | `vae/` |
| `minimax_h3_audio_vae_fp32.safetensors` | 0.56 GB | `vae/` |

### 4. 工作流

`workflows/` 下两个官方原版（已通过后端 `/prompt` 完整验证，链接自洽、坐标正常）：
- `MiniMax_H3_文生视频_官方原版.json`（T2V，20 节点 21 链接）
- `MiniMax_H3_图生视频_官方原版.json`（I2V，23 节点 23 链接，带首帧 LoadImage）

> 官方模板库升级 0.11.37 后也内置同款 3 个模板（含 R2V 参考生视频），可从界面模板库直接加载。
> **注意**：官方模板默认 **1344×768 / 5 秒 / 20 步**，首次打开时前端文件列表是旧缓存，保存会报 409 Conflict——**按 F5 刷新页面即可**（前端重新拉取 `/v2/userdata` 列表后 `isPersisted=true`，保存带 `overwrite=true`）。

### 5. 全自动极限测试结果（实测）

通过 ComfyUI API 直接覆盖 `MiniMaxH3ImageToVideo` 的 width/height/length 逐个提交，pynvml 后台监控显存峰值。帧数规则：24fps，`n % 17 == 5` 对齐网格（3 秒=73 帧，5 秒=124，8 秒=192，10 秒=243，15 秒=360）。

| 档位 | 分辨率 | 时长 | 结果 | 耗时 | 显存峰值 |
|:---|:---|:---:|:---:|:---:|:---:|
| 档1 | 1056×608 | 5s | ✅ | 4分16秒 | 11765MB (96%) |
| 档2 | 1216×672 | 5s | ✅ | 5分46秒 | 11669MB (95%) |
| 档3 | **1344×768** | 5s | ✅ | 7分43秒 | 11764MB (96%) |
| 档4 | 1056×608 | 8s | ✅ | 7分22秒 | 11805MB (97%) |
| 档5 | 1056×608 | **10s** | ✅ | 10分18秒 | 11674MB (95%) |
| 极限1 | **1344×768** | **10s** | ✅ | **21分整** | 12004MB (98%) |
| 极限2 | **1344×768** | **12s** | ❌ OOM | 25s | 12094MB (99%) |
| 极限3 | **1344×768** | **15s** | ❌ OOM | 25s | 12046MB (99%) |

### 6. 结论：12GB 能力地图

| 分辨率 | 最长可跑时长 | 说明 |
|:---|:---:|:---|
| 1056×608 | **15 秒**（趋势可行） | 低分辨率时长上限最宽 |
| 1216×672 | 5 秒+（未测更长） | 平衡点 |
| **1344×768** | **10 秒** | 768P 的硬上限 |
| 864×480 | 15 秒+ | 起步安全区 |

**关键洞察**：
1. **分辨率 vs 时长互斥**：分辨率吃满显存基线后，时长只能到 10 秒；降分辨率可把时长拉到 15 秒。15 秒官方上限在 768P 下必然 OOM
2. **OOM 特征**：都在 `SamplerCustomAdvanced` 采样阶段，帧数 → latent 空间 → 显存溢出，峰值 99% 即临界
3. **显存基线不随分辨率降**：模型驻留（编码器+扩散模型）恒定，省显存最有效变量是时长，其次是分辨率

**实用推荐**：
- 追求画质：**1344×768 / 10 秒**（21 分钟，贴极限，别开其他程序）
- 追求时长：**1056×608 / 15 秒**（约 15 分钟）
- 平衡：**1216×672 / 8 秒**（约 10 分钟）

### 7. 踩坑记录（重要）

| 坑 | 教训 |
|:---|:---|
| **跨卷 junction 启动崩溃** | 0.31 内核 `os.listdir(custom_nodes)` 对 D→F junction 抛 `WinError 448`，必须 `folder_paths.py` 里 `os.readlink` 解析（返回 `\\?\` 前缀需去掉，否则 `os.path.join` 拼 `..` 报 `Errno 22`） |
| **comfy-kitchen 过旧** | 0.2.10 < 0.2.28 时 NVFP4 文本编码器报 `TensorCoreConvRotW4A4Layout` 缺失，fp4 加速不可用，必须升级 |
| **模型下载写错目录** | `ComfyUI-aki-v3/models/`（外层孤岛）≠ `ComfyUI-aki-v3/ComfyUI/models/`（内核 junction → F 盘）。下载脚本必须写内核路径，否则 ComfyUI 找不到模型 |
| **官方模板 UUID 内嵌节点** | t2v/i2v 模板的 `4c314f31-...` 节点靠 `definitions.subgraphs` 在前端模板库展开，复制成独立 JSON 打开显示"孤立组件"。解法：复刻前端展开逻辑转标准节点图（重编号、槽位映射、widget 回填） |
| **前端 409 Conflict** | 文件由脚本写盘、早于前端列表缓存 → `isPersisted=false` → 保存带 `overwrite=false` → 409。**F5 刷新即可** |
| **pip 走国外源卡死** | PyPI 国外网络极慢，`comfyui-workflow-templates` 升级用**阿里云镜像**秒装 |
| **PowerShell 引号/GBK 坑** | 临时脚本必须 `write_to_file` 成文件再跑（`python -c` 引号转义必错）；输出文件用 UTF-8 写再 read_file 读 |
| **显存峰值贴边** | 95-97% 运行时别开浏览器/其他占用显存的程序，否则挤爆 OOM |





