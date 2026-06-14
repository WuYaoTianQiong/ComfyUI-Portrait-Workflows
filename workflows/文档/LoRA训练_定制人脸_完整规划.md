# LoRA 训练定制人脸 — 完整规划

> 目标: 训练自己的真人脸 LoRA，在现有 Moody 写实工作流中替换 momoka-zib-v2
> 环境: RTX 5070 12GB / Windows / ComfyUI-aki-v2
> 基座模型: Realistic Vision V5.1 (SD1.5 写实)
> 工具: kohya_ss GUI

---

## 一、你需要提供的东西（清单）

### 1.1 照片素材

| 项目 | 要求 | 说明 |
|------|------|------|
| 数量 | **20-30 张** | 少于15张容易过拟合，多于40张边际收益递减 |
| 分辨率 | 每张 ≥ 512px（长边） | kohya 会自动裁切，但源图不能太小 |
| 格式 | JPG / PNG | 不要用 HEIC/WebP，先转成 JPG |
| 人脸占比 | 人脸占画面 **30%-60%** | 半身照/肩上照最佳，全身照人脸太小不推荐 |
| 背景 | **多样化** | 室内/室外/不同场景，避免全是同一面墙前 |
| 光线 | **多样化** | 自然光/暖光/冷光/侧光，避免全是同一光源 |
| 角度 | **多样化** | 正面为主(60%)，侧面(30%)，仰视/俯视(10%) |
| 表情 | **多样化** | 微笑/严肃/张嘴/闭嘴，避免全是同一种表情 |
| 服装 | **多样化** | 不同衣服/配饰，避免全是同一套 |
| 眼镜/帽子 | 最好有少量戴/不戴的对比 | 让 LoRA 学到"脸"而非"配饰" |

### 1.2 照片筛选标准（你只有现有照片，务必严格筛选）

**[OK] 保留:**
- 清晰、对焦准确
- 光线均匀、面部无严重阴影
- 不同日期/场合拍的
- 不同服装/妆容

**[NO] 淘汰:**
- 模糊、失焦、运动模糊
- 强滤镜/美颜过度（磨皮到无毛孔）
- 多人合照（除非能裁出单人且画质够）
- 面部被遮挡 >30%（口罩/大墨镜/手挡脸）
- 逆光导致面部全黑
- 极度夸张的表情（鬼脸/大笑变形）
- 同一场景连拍的（选1张即可，不要5张几乎一样的）

### 1.3 触发词（Trigger Word）

你需要给这个 LoRA 起一个**唯一的触发词**，训练时写入每张图的标注。

| 要求 | 说明 |
|------|------|
| 格式 | 小写英文，无空格，如 `xyzperson` |
| 唯一性 | 不能是常见英文单词（如 `girl` `woman`），否则和大模型概念冲突 |
| 长度 | 3-12 个字符 |
| 示例 | `hw074face` / `myface01` / `zhangsan` |

**你需要在训练前确定这个触发词，训练后无法更改。**

### 1.4 硬件确认

| 项目 | 你的配置 | 最低要求 |
|------|---------|---------|
| GPU | RTX 5070 12GB | GTX 1060 6GB（极慢但能跑） |
| 硬盘空间 | — | 训练过程临时文件约 5-10GB |
| 内存 | — | 建议 ≥ 16GB |

12GB 显存足够跑 SD1.5 LoRA 训练，batch_size=1 无压力。

---

## 二、kohya_ss 安装方案

### 2.1 推荐方案：独立安装（与 ComfyUI 隔离）

**理由:**
- ComfyUI-aki-v2 自带 Python 环境（`python/`），kohya_ss 依赖版本可能冲突
- 独立安装互不干扰，ComfyUI 升级不会影响训练环境
- 训练出的 LoRA 是标准 `.safetensors` 格式，**任何平台通用**（ComfyUI / WebUI / SD.Next / DrawThings 等）

### 2.2 安装步骤

```
步骤1: 克隆仓库
  git clone https://github.com/bmaltais/kohya_ss.git
  建议克隆到 D:\Entertainment\kohya_ss（与 ComfyUI 同级，不放在 ComfyUI 内）

步骤2: 运行安装脚本
  cd D:\Entertainment\kohya_ss
  setup.bat
  （首次运行会自动创建 venv、安装依赖，约 10-20 分钟）

步骤3: 启动 GUI
  kohya_ss_gui.bat
  或: gui.bat --inbrowser
  浏览器打开 http://127.0.0.1:7860

步骤4: 验证 CUDA
  在 kohya_ss GUI 的 Utilities → Verify CUDA 检查
  应显示你的 RTX 5070 和 CUDA 版本
```

### 2.3 可能遇到的问题

| 问题 | 解决 |
|------|------|
| `bitsandbytes` 安装失败 | kohya_ss 最新版已支持 Windows，如仍失败可跳过（仅影响 8bit Adam 优化器，用标准 Adam 即可） |
| CUDA 版本不匹配 | 确认 `nvidia-smi` 显示的 CUDA 版本，kohya_ss 安装时会自动匹配 |
| Python 版本 | kohya_ss 自带 venv，不依赖系统 Python。要求 Python 3.10 |

---

## 三、素材预处理

### 3.1 目录结构

```
D:\Entertainment\lora_training\
  image\                          ← 原始照片放这里
    10_hw074face.jpg              ← 命名规则: 序号_触发词.jpg
    11_hw074face.jpg
    ...
  log\                            ← 训练日志（自动生成）
  output\                         ← 训练输出（自动生成）
```

**命名规则很重要:** `序号_触发词.扩展名`，序号从 10 开始（避免个位数排序问题）。

### 3.2 裁切与调整

如果原始照片人脸占比太小（全身照），需要手动裁切：

```
要求:
  - 裁切后人脸占画面 30%-60%
  - 裁切后长边 ≥ 512px
  - 保持原始宽高比（不要拉伸变形）
  - 不要过度裁切到只剩脸，保留肩膀和部分身体
```

### 3.3 自动标注（kohya_ss 内置）

kohya_ss GUI 自带 **WD14 Captioner** 和 **BLIP Captioner**，可自动为每张图生成描述文件。

```
操作路径: kohya_ss GUI → Utilities → Captioning

推荐方案: WD14 Captioner
  - 生成 .txt 标注文件，与图片同名
  - 标注内容为英文标签，如: "1girl, black hair, brown eyes, smile, ..."
  - 你需要在每条标注最前面加上触发词: "hw074face, 1girl, black hair, ..."
```

### 3.4 标注修正（关键步骤，必须手动做）

自动标注不会知道"这是谁"，你需要：

```
1. 打开每个 .txt 文件
2. 确认最前面有你的触发词（如 hw074face）
3. 删除与"身份"无关但可能"绑定"的标签:
   - [删] 具体服装描述: "white t-shirt" → 换成 "shirt"（否则 LoRA 会把白T恤焊死在你脸上）
   - [删] 具体场景描述: "outdoors, sky, building" → 保留但简化
   - [删] 具体配饰: "glasses, earrings" → 如果不是每张都戴，删掉
   - [保留] 通用特征: "1girl, brown eyes, black hair, realistic, ..."
4. 保存
```

**核心原则:** 你想让 LoRA 学到的东西（脸），标注要精确；不想绑定的东西（衣服/场景/配饰），标注要模糊或删除。

---

## 四、训练参数配置

### 4.1 基础参数（kohya_ss GUI → LoRA 选项卡）

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| Pretrained model | `Realistic_Vision_V5.1_fp16-no-ema.safetensors` | 你已有的写实基座 |
| Image folder | `D:\Entertainment\lora_training\image` | 素材目录 |
| Output folder | `D:\Entertainment\lora_training\output` | 输出目录 |
| Model output name | `hw074face_v1` | 输出文件名 |
| Save model as | `safetensors` | 标准格式，跨平台通用 |
| Train batch size | **1** | 12GB 显存安全值 |
| Epoch | **15-20** | 起始值，需观察 loss 曲线调整 |
| Save every N epochs | **5** | 每5个epoch保存一次，方便挑最好的 |
| Mixed precision | **fp16** | 节省显存，SD1.5 训练标准配置 |
| Save precision | **fp16** | 与训练精度一致 |
| Seed | **42** | 固定种子，方便复现 |

### 4.2 网络参数（关键）

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| Network DIM (Rank) | **32** | 人脸 LoRA 标准值，16 偏欠拟合，64 偏过拟合 |
| Network Alpha | **16** | 通常设为 DIM 的一半，控制学习强度 |
| Network module | **networks.lora** | 标准 LoRA，不用 LoCon/LoHa |
| Network args | — | 留空 |

### 4.3 学习率（最敏感的参数）

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| Learning rate | **1e-4** (0.0001) | SD1.5 写实人脸起始值 |
| Text Encoder LR | **5e-5** (0.00005) | 文本编码器学习率，通常为主 LR 的一半 |
| Unet LR | **1e-4** (0.0001) | 与主 LR 一致 |
| LR Scheduler | **cosine** | 余弦退火，训练后期自动降低学习率 |
| Warmup ratio | **0.05** | 前 5% 步数做学习率预热 |

### 4.4 数据参数

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| Resolution | **512,512** | SD1.5 标准分辨率 |
| Enable buckets | **开启** | 多分辨率分桶，不同宽高比的图都能用 |
| Min bucket resolution | **256** | |
| Max bucket resolution | **1024** | |
| Caption extension | **.txt** | 标注文件格式 |
| Shuffle caption | **开启** | 每轮随机打乱标签顺序，防止位置偏差 |
| Keep token | **1** | 保留第一个标签（你的触发词）不被打乱 |
| Max token length | **75** | SD1.5 标准值 |
| Color augmentation | **关闭** | 写实人脸不要开，会改变肤色 |
| Flip augmentation | **关闭** | 人脸不对称，翻转会学出奇怪的脸 |

### 4.5 高级参数

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| Optimizer | **AdamW8bit** | 省显存，12GB 推荐使用；如安装失败用 AdamW |
| Gradient accumulation | **1** | batch_size=1 时不需要 |
| Gradient checkpointing | **开启** | 省约 2GB 显存，速度慢 10-20% |
| Xformers | **开启** | 注意力机制优化，省显存+加速 |
| Full fp16 training | **关闭** | 容易 NaN，用混合精度即可 |
| Clip skip | **1** | Realistic Vision V5.1 推荐值 |
| VAE | **留空或选 ae.safetensors** | 用基座模型自带的 VAE 即可 |

### 4.6 正则化图像（可选但推荐）

正则化图像用于防止过拟合——让 LoRA 不会"记住"某张特定照片。

```
方案A（简单）: 不用正则化图，靠控制 epoch 数和学习率避免过拟合
  - 适合: 素材 20-30 张，场景/服装已经足够多样

方案B（进阶）: 用 AI 生成的同类图像做正则化
  - 用 Realistic Vision 生成 20-30 张不同女性的写实人像
  - 放入 reg/ 目录，标注不带你的触发词
  - 作用: 让模型知道"不是所有写实人像都是你"
```

**建议: 第一次训练先用方案A，如果出现过拟合（每次生成都是同一个姿势/服装），再加正则化。**

---

## 五、训练流程

### 5.1 完整步骤

```
1. 准备素材
   ├─ 收集 20-30 张照片
   ├─ 筛选（按 1.2 标准淘汰不合格的）
   ├─ 裁切（人脸占比 30%-60%，长边 ≥ 512px）
   ├─ 重命名（10_hw074face.jpg, 11_hw074face.jpg, ...）
   └─ 放入 image/ 目录

2. 生成标注
   ├─ kohya_ss GUI → Utilities → WD14 Captioner
   ├─ 输入 image/ 目录路径
   ├─ 运行，生成同名 .txt 文件
   └─ 手动修正每个 .txt（加触发词，删绑定标签）

3. 配置训练参数
   ├─ 按第四节参数表填写 kohya_ss GUI
   ├─ 确认 Pretrained model 路径指向 Realistic Vision V5.1
   └─ 确认 Output folder 路径正确

4. 开始训练
   ├─ 点击 "Start training"
   ├─ 观察控制台输出，确认无报错
   ├─ 观察 loss 曲线（GUI 内可查看）
   │   ├─ 正常: loss 从 ~0.3 逐渐下降到 ~0.05-0.1
   │   ├─ 过拟合: loss 降到极低 (<0.01) 但生成质量变差
   │   └─ 欠拟合: loss 停在 0.2 以上不降
   └─ 训练时间预估: RTX 5070 约 30-60 分钟（20张图 x 20 epoch）

5. 挑选最佳 epoch
   ├─ 每 5 个 epoch 保存一个模型
   ├─ 将每个 epoch 的 .safetensors 复制到 ComfyUI 的 models/loras/
   ├─ 在 ComfyUI 中逐个测试，对比哪个最像你、泛化最好
   └─ 通常最佳 epoch 在 10-15 之间

6. 集成到工作流
   ├─ 将最佳 .safetensors 放入 ComfyUI/models/loras/
   ├─ 在工作流中替换 momoka-zib-v2 LoRA
   ├─ 触发词替换: 提示词中的角色描述改为你的触发词
   └─ 调整 LoRA 权重: 从 0.8 开始试，0.6-1.0 之间找最佳值
```

### 5.2 训练时间预估

| 素材数 | Epoch | RTX 5070 预估时间 |
|--------|-------|-------------------|
| 15 张 | 20 | ~25 分钟 |
| 25 张 | 20 | ~40 分钟 |
| 40 张 | 20 | ~65 分钟 |

---

## 六、训练后验证

### 6.1 快速验证清单

```
测试1: 基础相似度
  提示词: "hw074face, 1girl, realistic, portrait, simple background"
  LoRA 权重: 1.0
  → 生成的脸是否像你？

测试2: 泛化能力
  提示词: "hw074face, 1girl, realistic, wearing suit, office, professional"
  提示词: "hw074face, 1girl, realistic, wearing dress, beach, sunset"
  → 换场景/服装后脸还是你吗？

测试3: 过拟合检测
  提示词: "hw074face, 1girl, realistic, standing in a garden"
  → 是否每次生成的姿势/角度/表情都一样？
  → 如果是，说明过拟合，换更早的 epoch 或降低 epoch 数

测试4: 权重范围
  LoRA 权重: 0.5 / 0.7 / 0.8 / 1.0 / 1.2
  → 哪个权重最像你且不崩坏？
```

### 6.2 常见问题与调优

| 症状 | 原因 | 解决 |
|------|------|------|
| 不像你 | 欠拟合 | 增加 epoch 到 25-30，或提高 Learning rate 到 2e-4 |
| 像但每次都同一姿势 | 过拟合 | 用更早的 epoch，或降低 DIM 到 16 |
| 像但脸变形/不自然 | 学习率过高 | 降到 5e-5，增加 epoch |
| 像但颜色偏 | VAE 不匹配 | 确认训练和推理用同一个 VAE |
| 换场景后不像了 | 标注绑定了场景 | 重新修正标注，删除场景相关标签 |
| 戴眼镜焊死 | 标注绑定了配饰 | 删除 "glasses" 标签，或补充不戴眼镜的照片 |

---

## 七、集成到现有工作流

### 7.1 Moody 写实工作流集成

你的现有工作流使用 `moodyRealMix_zitV6R1DPO` + `momoka-zib-v2` LoRA。

**重要区别:** 你训练的 LoRA 基于 **Realistic Vision V5.1 (SD1.5)**，而 Moody 工作流用的是 **ZIT 系列（非标准 SD1.5）**。

这有两种策略：

```
策略A: 直接在 Moody 工作流中替换 LoRA（可能效果打折）
  - ZIT 模型的架构与标准 SD1.5 有差异（用了 ModelSamplingAuraFlow 等）
  - LoRA 可能部分兼容，但相似度可能不如在 Realistic Vision 上
  - 试试看，权重从 0.8 开始调

策略B: 用 Realistic Vision 工作流 + 你的 LoRA（推荐先试这个）
  - 你已有 Realistic_Vision_V5.1_fp16-no-ema.safetensors
  - 已有 RealisticVision_双阶段_4x超分.json 工作流
  - 先在这个工作流上验证 LoRA 效果
  - 确认 LoRA 质量后，再尝试迁移到 Moody 工作流
```

### 7.2 提示词调整

```
原工作流提示词:
  "Moody Photography, 20岁可爱中国女生，..."

替换为:
  "Moody Photography, hw074face, 20岁可爱中国女生，..."
                      ^^^^^^^^^
                      你的触发词插在这里

或者（如果不用 Moody 风格）:
  "hw074face, 1girl, realistic, photography, detailed face, ..."
```

### 7.3 LoRA 权重建议

| 工作流 | 建议权重 | 说明 |
|--------|---------|------|
| Realistic Vision 工作流 | **0.7-0.9** | 原生基座，效果最好 |
| Moody ZIT 工作流 | **0.6-0.8** | 跨基座使用，权重略低更稳定 |

---

## 八、完整时间线

| 阶段 | 任务 | 预估耗时 |
|------|------|---------|
| Day 1 | 收集照片、筛选、裁切、重命名 | 1-2 小时 |
| Day 1 | 安装 kohya_ss | 20-30 分钟 |
| Day 1 | 生成标注 + 手动修正 | 1-2 小时 |
| Day 1 | 配置参数 + 第一次训练 | 1 小时 |
| Day 1-2 | 测试各 epoch，挑选最佳 | 1-2 小时 |
| Day 2 | 如需调优，修改参数重新训练 | 1-2 小时 |
| Day 2 | 集成到 ComfyUI 工作流 | 30 分钟 |

**总计: 1-2 天可以从零到出图。**

---

## 九、你需要确认的事项

在开始训练之前，请确认以下信息：

1. **触发词**: 你想用什么触发词？（如 `hw074face`）
2. **照片数量**: 筛选后你大概有多少张合格照片？
3. **照片特点**: 你的主要外貌特征（发色/发型/瞳色等），这影响标注修正策略
4. **kohya_ss 安装位置**: 是否同意安装到 `D:\Entertainment\kohya_ss`？

---

## 附录：文件路径速查

| 文件 | 你的路径 |
|------|---------|
| 基座模型 | `D:\Entertainment\ComfyUI-aki-v2\ComfyUI\models\checkpoints\Realistic_Vision_V5.1_fp16-no-ema.safetensors` |
| LoRA 输出位置 | 训练完成后复制到 `D:\Entertainment\ComfyUI-aki-v2\ComfyUI\models\loras\` |
| 素材目录（建议） | `D:\Entertainment\lora_training\image\` |
| kohya_ss（建议） | `D:\Entertainment\kohya_ss\` |