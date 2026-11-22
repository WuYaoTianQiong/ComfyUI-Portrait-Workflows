# comfyui_resolution_preset_picker（仓库副本）

本目录是**版本留档**，实际生效的是 `F:/ComfyUI_Migration/custom_nodes/comfyui_resolution_preset_picker/`。
ComfyUI 启动时只读 custom_nodes，改这里不会生效——改完要同步复制过去并重启。

## 两个节点

| 节点 | 类型名 | 用途 |
|---|---|---|
| 分辨率预设选择器 | `ResolutionPresetPicker` | 8 个固定尺寸 preset（ZIT 工作流在用），输出 width/height/filename_prefix |
| **画幅与倍率（下拉）** | `ResolutionSizer` | **替代 ComfyUI 原生 `ResolutionSelector`**：比例、像素量都是下拉，输出 width/height |

## 为什么加 ResolutionSizer

原生 `ResolutionSelector` 的 `megapixels` 是浮点输入框，要手填 2.4 并自己心算会出多大，
单位还是 MiP（1024×1024）不是 100 万像素。`ResolutionSizer` 把它换成 12 档下拉：

    0.4 / 0.55 / 0.75 / 1.0 / 1.25 / 1.5 / 1.8 / 2.16 / 2.34 / 2.4 / 3.0 / 4.0

像素计算与原生节点**逐像素一致**（已用 1192×2112 / 1280×1920 / 1024×1536 / 1128×2008 复核）。

## 与 Atelier 的契约

- API 里输入名保持 `aspect_ratio` / `megapixels` / `multiple`，`_latent_info` 仍判为 `mode=resolver`；
- 工作流 JSON 中 `megapixels` 的声明类型写成 **FLOAT**（值仍是下拉里的浮点数），
  否则 `_nodes_to_api` 按 COMBO 只认字符串会把值丢掉、退回默认 2.4；
- 档位是有限集合，Atelier 按画质档算出的 4.86 这类值要在写入前吸附
  （`workflow_parser._snap_to_combo`），预览同样吸附，否则标签比真实出图虚高。

## 安装

1. 把 `__init__.py` 复制到 `F:/ComfyUI_Migration/custom_nodes/comfyui_resolution_preset_picker/`
2. 重启 ComfyUI
3. 验收：`GET /object_info/ResolutionSizer` 能返回，且 `megapixels` 选项是浮点数组
