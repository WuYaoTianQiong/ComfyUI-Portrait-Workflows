# Moody ZIT V7 写实人像 — 完整指南与踩坑手册

> 最后更新: 2026-06-14
> 适用环境: ComfyUI-aki-v2 + RTX 5070 12GB (或同等显卡)
> 模型: moodyRealMix_zitV7GlobalFP8.safetensors
> 工作流: MoodyZIT_V7_写实人像_小图放大超分_4K级竖屏.json
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
| ComfyUI | 最新版 | — | v0.24.0 |

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
| 基底生成 | 640×960 | KSampler 7步 | 低分辨率草图 |
| Latent 放大 | 1088×1632 | 1.7x bislerp |  latent 空间放大 |
| Refine 重绘 | 1088×1632 | KSampler 4→9步 | 细节填充 |
| UltimateSDUpscale | **2720×4080** | 2.5x AI 重绘 | **最终输出** |

> 总像素：约 1100 万（4K 级竖屏）

### 关键参数速查

| 参数 | 值 |
|------|-----|
| 采样器 | dpmpp_2m_sde |
| 调度器 | beta (阶段1) / sgm_uniform (阶段2) |
| CFG | 1.0 |
| 阶段1 步数 | 7 (0→7) |
| 阶段2 步数 | 4→9 (sgm_uniform) |
| 超分 denoise | 0.23 |
| 超分模型 | 4xNomos8kDAT |
| 显存占用 | ~9GB |
| 单图耗时 | 3-5 分钟 (RTX 5070) |

---

## 二、模型依赖

以下 6 个文件必须全部下载并放入指定目录，总大小约 25GB。

| # | 文件 | 放置路径 | 大小 | 来源 |
|---|------|---------|------|------|
| 1 | moodyRealMix_zitV7GlobalFP8.safetensors | models/diffusion_models/ | ~16GB | [HuggingFace](https://huggingface.co/Aitrepreneur/moodyRealMix_Zit_V7) |
| 2 | qwen_3_4b.safetensors | models/text_encoders/ | ~7.6GB | 同上 |
| 3 | ae.safetensors | models/vae/ | ~300MB | 同上 |
| 4 | momoka-zib-v2_clean.safetensors | models/loras/ | ~150MB | HF/Civitai 搜索 "momoka zib v2" |
| 5 | zit_sda_v1.safetensors | models/loras/ | ~150MB | 同上 HuggingFace |
| 6 | 4xNomos8kDAT.safetensors | models/upscale_models/ | ~150MB | [openmodeldb](https://openmodeldb.info/models/4x-Nomos8kDAT) |

### 插件依赖
- **ComfyUI_UltimateSDUpscale**（Manager 搜索安装）
- ComfyUI-Manager（管理其他插件）

---

## 三、使用步骤

### 1. 环境确认
- NVIDIA 显卡，显存 >= 8GB（推荐 12GB+）
- 硬盘剩余 >= 50GB
- ComfyUI 本体已安装并运行

### 2. 安装插件
打开 ComfyUI → Manager → 搜索 `UltimateSDUpscale` → 安装 → Restart

### 3. 放置模型
按上表将 6 个模型文件放入对应目录。

### 4. 加载工作流
将 `MoodyZIT_V7_写实人像_小图放大超分_4K级竖屏.json` 拖入 ComfyUI 画布。

### 5. 修改 Prompt
双击节点 8（CLIPTextEncode，绿色文本框），修改中文场景描述。

**保留开头**：`Moody Photography,`
**保留风格词**：`韩风冷色调网红美白滤镜，极致冷白皮，通体雪白`
**保留质量词**：`高清现实主义风格，细节丰富，动态光影，8K超清`

**可修改部分**：中间的场景描述、人物动作、服装、环境。

### 6. 生成
点击 **Queue Prompt**，等待 3-5 分钟。

---

## 四、Prompt 工程指南

### 内置优化关键词（已植入工作流）

以下关键词已自动追加到正提示词末尾，**不需要手动重复**：

- `glass reflection, specular highlights, mirrored surface, environmental reflection` — 增强玻璃/镜面反射
- `脚趾自然舒展，真实脚部结构` — 抑制脚趾蜷缩粘连

### 负面词策略

本工作流**不使用传统负面词**，而是采用 `ConditioningZeroOut` 技术将正提示词的反向置零。这意味着：
- 不需要写 `low quality, bad hands` 等负面词
- 也不需要加载额外的负面 embedding
- 如果效果不佳，优先优化**正提示词**的描述精度

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

## 五、可选：启用 FaceDetailer

### 为什么要用？
UltimateSDUpscale 后人物面部可能略显平滑，FaceDetailer 对面部区域做局部重绘，恢复眼神光、皮肤毛孔、唇纹等细节。

### 前提条件
安装插件：`ComfyUI's ControlNet Auxiliary Preprocessors`
- Manager 中搜索安装
- 安装后重启 ComfyUI

### 操作步骤
1. 在工作流中找到 **SaveImage** 节点（节点 18）
2. 将其输入端的连线从节点 15（UltimateSDUpscale）拔下
3. 插入到节点 17（FaceDetailer）的输出端
4. 重新 Queue Prompt

### 代价
- 额外耗时：30-60 秒
- 显存增加：约 500MB-1GB
- 12GB 显卡可承受，但接近上限

---

## 六、常见问题与踩坑

### Q1: 红色节点报错？
**原因**：缺少插件或模型文件未找到。

**排查**：
1. 记录红色节点的名称（如 `UltimateSDUpscale`）
2. Manager 中搜索并安装对应插件
3. 重启 ComfyUI
4. 检查模型路径是否显示为红色（文件名不匹配或目录错误）

### Q2: 生成结果和预期差距大？
**排查清单**：
- [ ] 6 个模型文件全部正确放置（特别是 LoRA）
- [ ] 节点 4/5 的 LoRA 路径未显示红色
- [ ] prompt 保留了 `Moody Photography` 开头
- [ ] 未在负面词节点输入内容（本工作流不需要）

### Q3: 显存不足 (OOM) 或闪退？
**原因**：UltimateSDUpscale 阶段显存峰值高。

**解决**：
1. 关闭其他占用显存的程序
2. 重启 ComfyUI（确保之前模型的显存缓存已释放）
3. 降低 UltimateSDUpscale 的 `tile_width` 和 `tile_height`（默认 512，可降到 256）
4. 如果仍爆，考虑使用 GGUF 量化版模型（需自行寻找）

### Q4: 面部模糊/眼神空洞？
**方案 A**：启用 FaceDetailer（见第五节）
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
| 更快出图 | 阶段1 步数 | 5（默认 7） |
| 更稳构图 | 阶段1 步数 | 9（默认 7） |
| 更锐细节 | 超分 denoise | 0.28（默认 0.23） |
| 更柔细节 | 超分 denoise | 0.18（默认 0.23） |
| 更大胆创意 | CFG | 1.2-1.5（默认 1.0） |
| 更保守还原 | CFG | 0.8-1.0（默认 1.0） |

> **注意**：CFG > 1.5 可能导致色彩过饱和或伪影。ZIT 系列推荐 CFG=1.0。

---

## 八、与其他工作流的对比

| 维度 | Moody ZIT V7 | Hunyuan 2.1 | QwenImage | Anima v10 |
|------|-------------|------------|-----------|-----------|
| 核心用途 | 写实人像 | 中文场景/文字 | 文字招牌 | Anime 图生图 |
| 模型大小 | ~16GB | ~8GB (Q3) | ~8GB | ~5GB |
| 最佳分辨率 | 2720×4080 | 1024×1024 | 1024×1024 | 1536×2048 |
| 中文理解 | 一般 | **优秀** | 一般 | 一般 |
| 文字渲染 | 差 | **好** | **优秀** | 差 |
| 出图速度 | 3-5min | 2-3min | 2-3min | 1-2min |
| 写实质量 | **最高** | 高 | 中 | 不适用 |

---

## 九、版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-14 | 升级至 ZIT V7 FP8，删除全部 V6 旧工作流，重写本文档 |
| 2026-06-13 | 创建 V6 参考对齐版指南（已归档） |
