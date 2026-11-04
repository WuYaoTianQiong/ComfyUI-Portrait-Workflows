# 图库专用工作流（参考图库 · AI 合成台）

本目录放**只服务于「AI 参考图库 → 合成台」**的工作流：都是「三图合成」结构
（图1 人像 + 图2 服装 + 图3 姿势 → 提示词 → 出图），模型名与本机 ComfyUI 的实际下拉一致。

> 与库根那批 `*_文生图_*` / `*_换衣_*` / `*_超分_*` 工作流不是一类：那些没有参考图槽位，
> 在合成台里会被自动过滤掉，不会出现在下拉框中。

## 什么时候由谁读这些文件

`/api/workflows?scope=studio`（后端 `app/services/workflow_catalog.py` 的 `studio_dirs()`）
会扫描本目录 + `我的工作流/` + 上游 `ai-pose-gallery-zh/src/workflows/` + 库根，
只保留「有 `LoadImage*` 槽位 **且** 有文本编码节点」的工作流。
**新增工作流**：把 `.api.json` 丢进本目录（或 `我的工作流/`），刷新页面即可出现，不用重建前端。

## 清单

| 文件 | 模型栈 | 步数 | 槽位 | 适用场景 | 实测 |
|---|---|---:|---:|---|---|
| `图库专用_QwenEdit_GGUF-Q5KM_三图_4步_标准.api.json` | `Qwen_Image_Edit-Q5_K_M.gguf` + `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16` LoRA，CLIP `qwen_2.5_vl_7b_fp8_scaled`，VAE `qwen_image_vae` | 4 | 3 | **默认**。脸/衣服/姿势一致性最稳，`ReferenceLatent×4` 四路参考 | ✅ 2026-11-04 真出图 880×1184，约 130s / 160s 两次 |
| `图库专用_QwenEdit_GGUF-Q5KM_三图_4步_全身构图.api.json` | 同上（20 节点，参考 latent 2 路） | 4 | 3 | 人像只作「脸/发型语义参考」，不继承原图构图；人像参考是半身/大头照时用它更容易出全身 | 结构校验通过（节点/模型齐全），未单独真出图 |
| `图库专用_QwenEdit_GGUF-Q5KM_三图_4步_全身构图_自动裁切.api.json` | 同上 + AutoCrop 预处理 | 4 | 3 | 服装图/人像图不是全身时先裁到主体，避免把半身服装硬拉成全身；比标准版略慢 | 结构校验通过，未单独真出图 |
| `图库专用_QwenEdit_Nunchaku-fp4_三图_4步_低显存.api.json` | Nunchaku `svdq-fp4_r32-qwen-image-edit-lightningv1.0-4steps`，CLIP/VAE 同上 | 4 | 3 | 显存最省、出图最快，适合批量试稿；换脸/文字/织物细节不如 GGUF Q5_K_M | 结构校验通过，未单独真出图 |

「结构校验通过」= 14 个节点类全部已装 + 4 个模型文件都在 ComfyUI 的候选列表里（2026-11-04 实测）。

## 与上游「参考库专用」的关系

上游开源项目自带一份 `qwen_image_edit_2509_3img.api.json`
（在 `ai-pose-gallery-zh/src/workflows/`，下拉里显示为「上游原版」），
它引用 `qwen_image_edit_2509_fp8_e4m3fn.safetensors` —— **本机没有这个模型**，
直接选中会报「工作流与本机不匹配」。本目录这 4 份就是它在**本机 GGUF / Nunchaku 栈**上的等价改版。

要做成"完全替代"，二选一：

1. 补 `qwen_image_edit_2509_fp8_e4m3fn`（约 20GB）到 `F:\ComfyUI_Migration\models\diffusion_models`；
2. 把上游那份的 `UNETLoader` 换成 `UnetLoaderGGUF` + 本目录的 GGUF 名称（即本目录"标准"版的模型段）。

## 改动工作流时的注意事项

- 保留 3 个 `LoadImage` 的**标题**（`图1：人像参考 (Portrait)` / `图2：服装参考 (Costume)` / `图3：姿势参考 (Pose)`）——
  前端靠标题自动识别槽位，标题变了也能识别，但会退化成按节点顺序猜。
- `SaveImage.filename_prefix` 统一用 `pose_studio/result`，出图会落到 `output/pose_studio/`。
- 文件名前缀 `图库专用_` 是给下拉框"一眼看出是专用"用的，别去掉。
