# 2026-11-03 OCR 与红印章检测复测

## 先纠正上一轮的错误

上一轮“自动红章/OCR 需要换可靠模型”的表述不准确：

- 当时自动红章用的是 **OpenCV HSV 红色阈值**，不是 OCR；
- `rapidocr-onnxruntime` 只是可选依赖，生产 Python 没装，审计时**没有参与**；
- 所以 2225 个框 / 0 命中是 **HSV 失败**，不是 OCR 失败。

本轮用真实模型重测。

## 环境

- RTX 5070 12GB（CC 12.0）
- 生产 Python 3.12：torch 2.8.0+cu128、transformers 5.12.1、ultralytics 8.4.66
- 全局 Python 3.12：rapidocr-onnxruntime（PP-OCR ONNX）
- 数据：`output/PK_20261103/` 30 张真实图；3 个已知印章框：
  - ZIT s03：`(246,822)-(272,852)`
  - ZIT s04：`(278,616)-(302,642)`
  - Porn s04：`(271,799)-(304,837)`

## 1. 文字 OCR：RapidOCR / PP-OCR

30 张、CPU：

| 指标 | 结果 |
|---|---|
| 平均耗时 | **0.51s / 张** |
| C 组四字“静水流深” | **8/10 正确**（Krea2/Porn/Qwen/ZIT 全对；Flux 2/2 错） |
| B 组店招 | Qwen/ZIT 识别出“便利店 / 营业中”；Krea2/Porn/Flux 错字 |
| 印章 | **不识别**；印章是图形，不是文字 |

关键限制：C 组 OCR 把整列四字识别成一个大框，印章常常落在这个框内；因此 OCR 框可以用于“清掉所有文字”，但不能用来“只去印章、保留四字”。

原始结果：`rapidocr_30.json`、`ocr_texts_utf8.txt`。

## 2. 红印章检测：Grounding DINO tiny + CLIP

### 提示词

- “a red Chinese seal.”：3 个已知印章 **0/3** 命中（不可用）；
- **“a red stamp.”**：3 个已知印章 **3/3** 命中（关键）。

### 过滤器

- DINO 分数 ≥ 0.12
- 红色像素占比 ≥ 0.25
- 框面积 20–3500 px²
- 宽高比 0.25–4
- NMS IoU 0.4

### 30 张批量结果

| 指标 | 结果 |
|---|---|
| 已知 3 个印章 | **3/3 命中**（至少一个框与已知框重叠） |
| 候选框总数 | **35**（30 张，单图最多 3） |
| 热态耗时 | **0.176s / 张**（首次加载约 18s） |
| 显存 | **1.95GB** |
| A/B 组误检 | 红色包装、红招牌、红嘴唇等仍会出框 |

然后把 35 个候选框用 **CLIP large zero-shot** 分类（seal / packaging / sign / lips / clothing / red object）：

| 指标 | 结果 |
|---|---|
| CLIP 保留“印章”候选 | **16 / 35** |
| 已知 3 个印章 | **3/3** 至少一个保留框命中 |
| A/B 组误检 | 从 18 个降到 **2 个** |
| C 组候选 | 17 个中保留 14 个（其余嘴唇/红物被过滤） |

证据：
- `dino_boxes_all.jpg`：DINO 35 个候选的裁剪总表；
- `dino_overlay_A_zit04.jpg`：A 组纯人像仍把红包装/红招牌框出来；
- `dino_overlay_C_zit04.jpg`：C 组命中真印章；
- `clip_accepted.jpg`：CLIP 过滤后的 16 个候选；
- `dino_clip_overlay_C_zit04.jpg`：C 组保留框。

## 3. 结论

1. **OCR 不是瓶颈**：RapidOCR/PP-OCR 0.5s/张能正确读中文；生产可用 PaddleOCR PP-OCRv5/v6，5070 上更宽裕。
2. **红章检测不能只靠 OCR**：印章是非文字图形；HSV 完全不可用。
3. **DINO + CLIP 是可行的“候选生成”方案**：3/3 已知印章、0.18s/张、2GB 显存；但仍有 A/B 组红物误检，不能自动擦，必须预览确认。
4. **要自动擦，建议二阶段**：
   - 短期：DINO 出候选 + CLIP 过滤 + 用户确认；
   - 中期：用 Chinese-Seal / Roboflow 306 图 + 我们 PK 样本，标 200–500 张，微调 **YOLO11-seg**；5070 12GB 足够训练与推理。
5. 大面积文字/印章仍建议生成式 inpaint；OpenCV 只做小面积兜底。

## 复现

- DINO：`IDEA-Research/grounding-dino-tiny`，prompt `a red stamp.`，`box_threshold=0.08` 后按上述过滤；
- CLIP：`AI-ModelScope/clip-vit-large-patch14`，zero-shot 分类；
- OCR：`rapidocr-onnxruntime==1.3.24`。
