
## ResolutionSizer 的输入（2026-11-22 改版：倍率语义）

| 输入 | 含义 | 取值 |
|---|---|---|
| aspect_ratio | 宽高比 | 8 个比例 |
| base_megapixels | **原生像素量**（该工作流基准，MiP） | 1.0 / 1.25 / 1.5 / 1.8 / 2.16 / 2.34 / 2.4 / 3.0 / 4.0 |
| quality | **画质倍率**，与 Atelier 的档位同名同义 | 0.25x / 0.5x / 0.75x / 1.0x / 1.25x / 1.5x / 2.0x |
| multiple | 宽高取整倍数 | 默认 8 |

**面积 = 原生像素量 × 倍率²**（1.5x 是 2.25 倍面积，不是 1.5 倍）。
与 Atelier 完全对齐：`quality` 直接就是 `QUALITY_SCALES` 的键，注入时原样写入，不需要吸附/回退。

> 上一版是「单一下拉选绝对像素量（0.4~4.0 MiP）」，因下拉上限 4.0 会把 1.5x/2.0x 压小、
> 且语义与 Atelier 的倍率对不上，已废弃。

## Atelier 契约

- `_latent_info` 认 `base_megapixels + quality` → `mode=resolver`、`scale_driven=True`，`megapixels = base × scale²`；
- `_inject_resolution` 对 `scale_driven` 只写 `aspect_ratio` + `quality`（离散档位，1:1 映射），
  不再走「吸附档位 / 超差退回字面量」那条老路；
- 工作流 JSON 中 `base_megapixels` 的声明类型必须是 **FLOAT**（数值），`quality` 是 **COMBO**（字符串）；
  `_nodes_to_api` 对 COMBO 只认字符串，声明错会把值丢掉并静默退回默认值。

## 中文界面（locales/）

`locales/zh/nodeDefs.json` 把节点和参数名翻成中文：

| 原名 | 中文 |
|---|---|
| ResolutionSizer | 画幅与倍率（下拉） |
| aspect_ratio | 宽高比 |
| megapixels | 像素量(MiP) |
| multiple | 取整倍数 |

⚠️ **ComfyUI 的界面语言必须是中文才会生效**：设置（齿轮） → 语言 / Language → 中文（简体），
或改 `ComfyUI/user/default/comfy.settings.json` 里的 `"Comfy.Locale": "zh"`。
语言是英文时，widget 名照旧显示 `aspect_ratio` / `megapixels`（这是前端全局行为，
自定义节点无法只对自己生效）。

改完 locales 需重启 ComfyUI；验证：`GET /i18n` 返回的 `zh.nodeDefs.ResolutionSizer` 非空。

## 前端扩展（web/size_label.js）

在节点底部实时画出「当前下拉会出的像素」，如 `→ 1192 × 2112`。
标题里的像素是静态文字（改下拉不会变），所以标题不写具体数值，以底部这行为准。

挂载位置：`/extensions/comfyui_resolution_preset_picker/size_label.js`
（`WEB_DIRECTORY = "./web"`，重启后可在 `GET /extensions` 列表里看到）。
