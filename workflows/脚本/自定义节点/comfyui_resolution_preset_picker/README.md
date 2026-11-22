
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
