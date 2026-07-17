# FaceDetailer 换脸/面部增强操作指南

> 基于已验证的 `MoodyZIT_V7_Visual` 工作流 + ComfyUI Impact-Pack FaceDetailer

---

## 前提

ComfyUI 已在 `http://localhost:8188` 运行，Impact-Pack 已安装。

---

## 步骤一：打开基础工作流

1. 打开 ComfyUI 浏览器 → 右上角 Load → 选择：
   ```
   workflows/MoodyZIT_V7_Visual_文生图_双程采样_快速预览_文字渲染.json
   ```
2. 点 Queue 跑一次，确认 1.3MB 高质量出图正常（你已经验证过）

---

## 步骤二：添加 4 个新节点

在画布上空白处双击，搜索并添加以下节点：

### 节点 A：人脸检测
搜索 `UltralyticsDetectorProvider`
- 添加后，在 widget 下拉框选择：`bbox/face_yolov8m.pt`
- 这个节点会输出 `BBOX_DETECTOR` 类型

### 节点 B：SAM 分割（可选，但推荐）
搜索 `SAMLoader`
- 在 widget 选中：`sam_vit_b_01ec64.pth`
- 这个节点会输出 `SAM_MODEL` 类型

### 节点 C：面部正面提示词
搜索 `CLIPTextEncode`（添加两个）
- 正面词：`high quality Asian female portrait face, sharp facial details, clear eyes, beautiful skin texture, professional photography`
- 负面词：`blurry, ugly, deformed, bad anatomy, distorted face`

### 节点 D：核心——FaceDetailer
搜索 `FaceDetailer` 添加

---

## 步骤三：连线

FaceDetailer 的连线如下：

| FaceDetailer 输入端口 | 从哪个节点连过来 |
|:---|:---|
| `image` | 从原来的 `VAEDecode`(Node 12) 的输出 |
| `model` | 从 `ModelSamplingAuraFlow`(Node 5) 的输出 |
| `clip` | 从 `CLIPLoader`(Node 2) 的输出 |
| `vae` | 从 `VAELoader`(Node 3) 的输出 |
| `positive` | 从新增的"面部正面提示词"CLIPTextEncode |
| `negative` | 从新增的"面部负面提示词"CLIPTextEncode |
| `bbox_detector` | 从 `UltralyticsDetectorProvider` 的输出 |
| `sam_model_opt` | 从 `SAMLoader` 的输出 |

---

## 步骤四：FaceDetailer 参数设置

右键 FaceDetailer 节点 → 设置以下值：

| 参数 | 值 | 说明 |
|:---|:---|:---|
| `guide_size` | 512 | 面部重绘分辨率 |
| `max_size` | 1024 | 最大处理尺寸 |
| `steps` | 15 | 步数 |
| `cfg` | 1.5 | CFG（面部不需要太高） |
| `sampler_name` | euler | 采样器 |
| `scheduler` | simple | 调度器 |
| **`denoise`** | **0.45** | ⭐ 关键！控制换脸强度 |
| `feather` | 20 | 边缘羽化 |
| `noise_mask` | True | 启用量子噪声遮罩 |
| `force_inpaint` | True | 强制局部重绘 |
| `bbox_dilation` | 30 | 检测框扩大像素 |
| `bbox_crop_factor` | 3.0 | 裁剪倍数 |
| `sam_detection_hint` | center-1 | 检测中心人脸 |
| `sam_dilation` | 6 | SAM 膨胀 |
| `sam_threshold` | 0.93 | SAM 阈值 |
| `drop_size` | 10 | 丢弃太小的人脸 |

---

## 步骤五：修改输出

- 把原来 `SaveImage`(Node 13) 的输入断开
- FaceDetailer 的 `IMAGE` 输出 → 连到 `SaveImage` 的 `images` 输入
- 或新建一个 SaveImage 节点

---

## 步骤六：Queue 测试

点 Queue 运行！整个过程：
1. moodyProMix 生成基础全身/半身图（~60秒）
2. FaceDetailer 检测人脸 → SAM 精确分割 → KSampler 局部重绘面部（~30秒）
3. 输出高清面部增强图

---

## 调参技巧

| 效果 | denoise | CFG | 说明 |
|:---|:---:|:---:|:---|
| 轻量增强 | 0.25 | 1.0 | 只增强细节，不改变身份 |
| 中等换脸 | **0.45** | 1.5 | ⭐ 推荐起始值 |
| 强力重绘 | 0.65 | 2.0 | 面部重塑，可能改变身份 |

---

## 如果要换特定人脸（如东北雨姐）

FaceDetailer 本身不改变身份。要换脸的话：
1. 先用 moodyProMix 出高质量基础图
2. 用之前写好的 `_swap_align.py` 脚本（inswapper_128）做像素级换脸
3. 换完后用 FaceDetailer 对面部做高清增强

两步串联效果 = 身份正确 + 画质天花板
