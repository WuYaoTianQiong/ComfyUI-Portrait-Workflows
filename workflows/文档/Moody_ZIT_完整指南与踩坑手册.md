# ComfyUI 12G 显存姿势控制踩坑手册

> 2026年6月26日更新（Nunchaku/GGUF/AnyPose 折腾全记录），基于 ComfyUI 2026-06-16 版本

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

| 工作流 | 用途 | 模型 | 骨骼控图 |
|---|---|---|---|
| `Work-Fisher_Qwen-AIO_DWPose提取_图生图_API.json` | DWPose拍照提取骨骼→图生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ DWPose自动 |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_图生图_API.json` | VNCCS 3D手动摆姿→图生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_文生图_API.json` | VNCCS 3D手动摆姿→文生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D |
| `灵犀控骨_VNCCS骨骼控图_16x9画幅一键横竖切换_图生图_Visual.json` | ⭐ **VNCCS图生图+自动横竖切换** | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D |
| `千面绘形_DWPose姿态编辑_16x9画幅一键横竖切换_图生图.json` | ⭐ **DWPose图生图+自动横竖切换** | Qwen-Rapid-AIO-NSFW-v18 | ✅ DWPose自动 |
| `灵犀控骨_VNCCS骨骼控图_16x9画幅一键横竖切换_图生图_API.json` | VNCCS横竖切换(API版) | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D |
| `MoodyZIT_V7_API_文生图_双程采样_快速预览_文字渲染.json` | 高质量双程文生图 | moodyProMix_zitV13FP8 | ❌ |
| `MoodyZIT_V7_API_图生图_Inpaint手动遮罩_SeedVR2超分.json` | 图生图/局部重绘+超分 | moodyProMix_zitV13FP8 | ❌ |
| `MoodyZIT_V7_API_文生图_双程采样_SeedVR2_4K超分_文字渲染.json` | 文生图+双程+4K超分 | moodyProMix_zitV13FP8 | ❌ |
| `FLUX2_Klein9B_双程采样_快速预览.json` | Flux2 Klein 双程文生图 | flux-2-klein 系列 | ❌ |

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

## 三、已下载的重要模型

| 模型 | 路径 | 大小 | 用途 |
|---|---|---|---|
| Qwen-Rapid-AIO-NSFW-v18 | `checkpoints/QWEN/` | 26.5G | Work-Fisher姿势编辑 |
| Qwen-Image-ControlNet-Union | `controlnet/Qwen-Image-ControlNet-Union/` | 3.5G | Qwen的ControlNet（当前12G无法有效使用） |
| FLUX.2-dev-Fun-Controlnet-Union | `controlnet/FLUX.2-dev-Fun-Controlnet-Union/` | 7.7G | Flux2 dev专用，不与klein兼容 |
| flux_union_controlnet | `controlnet/` | 6.2G | Flux1 ControlNet |
| qwen-image-2512-Q4_K_M.gguf | `unet/` | 13.2G | Qwen 2512 GGUF量化 |

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

1. **Qwen-Rapid-AIO 文生图骨骼控图偏动画风格**：实测 Qwen-Rapid 在文生图模式下出图偏二次元/动画质感，写实度不如 MoodyZIT。如需写实画风，建议用 Qwen-Rapid 图生图（输入写实照片做参考），或走 Work-Fisher→MoodyZIT 两级串联方案。

2. **CheckpointLoaderSimple vs UNETLoader**：Checkpoint 打包了模型+CLIP+VAE，CLIP 和模型绑定正确不会维度报错。UNETLoader 分离加载，手动配错 CLIP 会炸（如 qwen_2.5_vl_7b(3584维) ≠ qwen_3_4b(2560维) → LayerNorm 报错）

3. **MoodyZIT 不能做骨骼控图**：它的原生 CLIP（qwen_3_4b）是纯文本模型，TextEncodeQwenImageEditPlus 需要 VL CLIP 才能把骨骼图编码进 conditioning。唯一的骨骼控图路径是 ControlNet，但需额外装插件。

4. **Qwen-Rapid-AIO 是骨骼控图最优解**：Checkpoint 内置 VL CLIP，支持文生图和图生图两种骨骼控图模式。


1. **CheckpointLoaderSimple vs UNETLoader**：Checkpoint 打包了模型+CLIP+VAE，CLIP 和模型绑定正确不会维度报错。UNETLoader 分离加载，手动配错 CLIP 会炸（如 qwen_2.5_vl_7b(3584维) ≠ qwen_3_4b(2560维) → LayerNorm 报错）

2. **MoodyZIT 不能做骨骼控图**：它的原生 CLIP（qwen_3_4b）是纯文本模型，TextEncodeQwenImageEditPlus 需要 VL CLIP 才能把骨骼图编码进 conditioning。唯一的骨骼控图路径是 ControlNet，但需额外装插件。

3. **Qwen-Rapid-AIO 是骨骼控图最优解**：Checkpoint 内置 VL CLIP，支持文生图和图生图两种骨骼控图模式。

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

## 八、后续可探索方向

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

### 已找到但未下载的亚洲优化 LoRA

| LoRA | 触发词 | 权重 | 平台 |
|------|--------|------|------|
| F.2-klein亚洲美女 | `ns80` | 0.8-1.0 | RunningHub（需登录） |
| Asian Mix Lokr | `asian woman` | 默认 | RunningHub（需登录） |
| TinFlux 逼真感人像（完整模型替换） | - | - | LiblibAI（需登录） |

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

