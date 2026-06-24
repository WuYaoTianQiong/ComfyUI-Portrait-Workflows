# ComfyUI 12G 显存姿势控制踩坑手册

> 2026年6月30日更新，基于 ComfyUI 2026-06-16 版本，RTX 12G VRAM

---

## 一、可用工作流速查

| 工作流 | 用途 | 模型 | 骨骼控图 |
|---|---|---|---|
| `Work-Fisher_Qwen-AIO_DWPose提取_图生图_API.json` | DWPose拍照提取骨骼→图生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ DWPose自动 |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_图生图_API.json` | VNCCS 3D手动摆姿→图生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D |
| `Qwen-Rapid-AIO_VNCCS_骨骼控图_文生图_API.json` | VNCCS 3D手动摆姿→文生图 | Qwen-Rapid-AIO-NSFW-v18 | ✅ VNCCS 3D |
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
