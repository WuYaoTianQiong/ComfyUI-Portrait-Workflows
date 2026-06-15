# 工作流使用说明

> 最后更新: 2026-06-15
> 当前保留 3 个工作流 + 1 个脚本工具，旧版已归入 `废弃工作流/`

---

## 快速选型

| 需求 | 用哪个 |
|------|--------|
| 写实人像，从提示词到4K出图一步到位 | **工作流一** |
| 已有图片想修改后超分到4K | **工作流二** |
| 已有图片只想超分到4K，不改内容 | **工作流三** |

---

## 工作流一：Moody ZIT V7 SeedVR2 全流程（主推）

**一句话**：输入提示词 → 自动生成 → 超分 → 面部增强 → 输出4K图，一步到位。

### 第一步：安装插件

打开 ComfyUI Manager → Install Missing Custom Nodes，搜索并安装：

| 插件 | 搜索关键词 |
|------|-----------|
| ComfyUI-SeedVR2_VideoUpscaler | `SeedVR2` |
| facerestore_cf | `facerestore` |

安装后**重启 ComfyUI**。

> 如果搜索不到 `facerestore_cf`，可能是因为目录名不同。确认 `ComfyUI/custom_nodes/facerestore_cf/` 目录存在即可。

### 第二步：下载模型

将以下模型文件放到 ComfyUI 对应目录：

| 文件 | 放置路径 | 大小 | 来源 |
|------|---------|------|------|
| moodyRealMix_zitV7GlobalFP8.safetensors | models/diffusion_models/ | ~8GB | HuggingFace |
| seedvr2_ema_3b_fp8_e4m3fn.safetensors | models/diffusion_models/ | ~6GB | HuggingFace |
| qwen_3_4b.safetensors | models/text_encoders/ | ~4GB | HuggingFace |
| ema_vae_fp16.safetensors | models/vae/ | ~300MB | HuggingFace |
| ae.safetensors | models/vae/ | — | HuggingFace |
| momoka-zib-v2_clean.safetensors | models/loras/ | — | HuggingFace/Civitai |
| zit_sda_v1.safetensors | models/loras/ | — | HuggingFace/Civitai |
| codeformer.pth | models/facerestore_models/ | ~376MB | 首次运行自动下载 |

> **提示**：所有路径都是相对于 `ComfyUI/` 根目录的。例如 `models/diffusion_models/` 实际是 `ComfyUI/models/diffusion_models/`。

### 第三步：加载工作流

1. 打开 ComfyUI 界面
2. 将 `MoodyZIT_V7_写实人像_SeedVR2超分_CodeFormer面部增强.json` 拖入浏览器窗口
3. 检查所有节点是否有**红色边框**（红色 = 缺插件或模型）

### 第四步：填写提示词

| 节点 | 用途 | 说明 |
|------|------|------|
| 节点 8（CLIPTextEncode） | **积极提示词** | 描述你想生成的画面 |
| 节点 19（CLIPTextEncode） | **消极提示词** | 描述你不想出现的内容，留空也行 |

### 第五步：运行

点击 **Queue Prompt**，等待出图。全程约 3-4 分钟（RTX 5070 12GB 参考）。

输出文件：`ComfyUI/output/V7_SeedVR2_CF_00001_.png`

### 管线结构

```
提示词 → KSampler(9步) → VAEDecode → SeedVR2超分 → CodeFormer面部增强 → 保存
```

### 关键参数调节

| 参数 | 默认值 | 调节建议 |
|------|--------|---------|
| EmptyLatentImage | 1024×576（16:9横图） | 可改为 640×960（竖图）等任意比例 |
| KSampler steps | 9 | 降低到 7-8 可加速，质量略降 |
| KSampler seed | 0 | 改为 random 随机出图 |
| SeedVR2 resolution | 2560 | 目标最短边，越大越清晰但越慢 |
| SeedVR2 color_correction | lab | 色偏严重可试 `wavelet` |
| CodeFormer fidelity | 0.5 | **0.7-0.8**=轻修保留原貌，**0.2-0.3**=强修磨皮感重 |
| CodeFormer facedetection | retinaface_resnet50 | 检测不到脸可换 `YOLOv5l` |

### 显存说明

| 阶段 | 占用 |
|------|------|
| 生成（KSampler） | ~8GB |
| 超分（SeedVR2） | ~9GB |
| 面部增强（CodeFormer） | 极轻 |

各阶段**依次执行**，不会同时占用。12GB 显卡够用，ComfyUI 自动在阶段间卸载模型。

### 常见问题

**Q: 节点显示红色？**
A: 红色边框 = 缺少对应插件。打开 Manager → Install Missing Custom Nodes，搜索安装后重启。

**Q: 模型下拉框是空的？**
A: 模型文件没放对位置，或文件名不一致。对照上方模型表检查路径和文件名。

**Q: 跑着跑着闪退/OOM？**
A: 关闭其他占显存的程序（浏览器标签页、其他AI工具），重启 ComfyUI 再试。

**Q: 首次运行很慢？**
A: CodeFormer 模型 `codeformer.pth`（376MB）首次运行会自动下载，等 1-2 分钟。

---

## 工作流二：Moody ZIT V7 图生图 + SeedVR2 超分 + CodeFormer 面部增强

**一句话**：输入已有图片 + 提示词 → 修改画面 → 超分 → 面部增强 → 输出4K图。

### 为什么不能直接对4K图做图生图？

4K 图编码到潜空间后有 ~153K 个 token，注意力计算是平方级复杂度，12GB 显存会爆。因此采用**先缩小、再生成、再超分**的策略：

```
原图(任意尺寸) → 等比缩小到~1024级 → img2img修改 → SeedVR2超分回4K → CodeFormer面部增强
```

### 使用步骤

1. 确认插件和模型已就绪（同工作流一）
2. 将 `MoodyZIT_V7_写实人像_图生图_SeedVR2超分_CodeFormer面部增强.json` 拖入 ComfyUI
3. 在 **LoadImage 节点（节点7）** 选择要修改的图片
4. 在积极/消极提示词节点填入修改方向
5. 点击 Queue Prompt

### 关键参数

| 参数 | 默认值 | 调节建议 |
|------|--------|---------|
| KSampler **denoise** | **0.6** | **核心参数！** 0.3=微调光影，0.5=改细节，0.6=换服装/背景，0.7+=大幅重绘 |
| ImageScaleBy scale_by | **0.27** | 等比缩放，保留原图比例。0.27≈4K图缩到1024级。如输入已是小图可改为0.5或1.0 |
| 其他参数 | 同工作流一 | 同工作流一 |

> **denoise 调参技巧**：
> - 0.2-0.3：只改颜色/光影，构图几乎不变
> - 0.4-0.5：改背景细节/小饰品
> - **0.5-0.6：换服装/改表情**（默认 0.6，适合大部分修改）
> - 0.7-0.8：大幅修改构图，可能偏离原图
> - 0.9+：基本等于重新生成

输出文件：`ComfyUI/output/V7_i2i_SeedVR2_CF_00001_.png`

---

## 工作流三：SeedVR2 单图超分

**一句话**：把已有图片拖进来，超分到 4K，无需提示词。

### 使用步骤

1. 确认 SeedVR2 插件已安装、模型已下载（同工作流一的模型表前两行）
2. 将 `SeedVR2_3B_FP8_单图超分_4K级竖屏.json` 拖入 ComfyUI
3. 在 LoadImage 节点选择要超分的图片
4. 点击 Queue Prompt

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| resolution | 2560 | 目标最短边 |
| blocks_to_swap | 36 | CPU offload，12GB显存必须开 |
| color_correction | lab | 色彩校正 |

输出文件：`ComfyUI/output/SeedVR2_Upscale_00001_.png`

---

## 脚本工具

### `脚本/auto_pipeline.py`

自动化批量出图脚本，配合提示词数据库使用。详见脚本内注释。

---

## 废弃工作流

以下工作流已归入 `废弃工作流/` 目录，仅供参考，不建议使用：

| 文件 | 废弃原因 |
|------|---------|
| MoodyZIT_V7_写实人像_小图放大超分_4K级竖屏.json | 已被全流程工作流替代，有水渍问题 |
| SeedVR2_*_GFPGAN* | GFPGAN 已弃用，选定了 CodeFormer |
| SeedVR2_*_CodeFormer面部增强* | 单独超分+面部增强已被全流程工作流包含 |
| 混元2.1_Q3_竖屏两阶段超分精修_4K级人像.json | 写实人像效果差，不到 V7 一半水平 |
| QwenImage_文字生成_1024x1024.json | 纯文字生成场景极少使用 |
| Anima_v10_图生图_批量处理.json | Anime 风格场景极少使用 |

---

## 通用常见问题

### Q: 加载工作流出现红色节点？
A: 记录红色节点的名称，在 Manager 中搜索安装对应插件后重启 ComfyUI。

### Q: 模型路径显示红色？
A: 确认模型文件已放入文档中指定的目录，文件名完全一致（含大小写）。

### Q: 显存不足 (OOM)？
A: 关闭其他占用显存的程序，重启 ComfyUI 确保显存释放。
