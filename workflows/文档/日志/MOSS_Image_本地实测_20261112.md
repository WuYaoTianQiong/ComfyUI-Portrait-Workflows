# MOSS-Image 本地实测（2026-11-12，含 ComfyUI 0.41.3 → 0.45.2 升级记录）

> 起因：catlover1937 的「Moody 微调」已做到 MOSS Image 线（`Moody Moss Mix V4.1`，11-04，16k 下载），
> 而 MOSS 需要 ComfyUI ≥ 0.42.2。本次升级内核并在 12G 上跑通，记录全流程与效果。

---

## 一、内核升级记录（0.41.3 → 0.45.2）

| 项 | 升级前 | 升级后 |
|---|---|---|
| ComfyUI | **v0.41.3**（`8713616fc`，2026-10-17） | **v0.45.2**（`6e8488ef9`，2026-11-11） |
| 前端包 | 1.55.17 | **1.58.5** |
| workflow-templates | 0.11.87 | 0.11.106 |
| embedded-docs | 0.5.14 | 0.5.16 |
| comfy-aimdo | 0.5.6 | **0.6.0** |
| comfy-kitchen | 0.2.37 | 0.2.41 |
| torch / transformers | 2.9.0+cu130 / 4.57.6 | **未动** |

**关键动作**：
1. 升级前把 `folder_paths.py` 的跨卷 junction 补丁导出为 `F:\ComfyUI_Migration\_patch_folder_paths_0413.diff` + `folder_paths.py.bak_0413`；
2. `git stash` → `git checkout v0.45.2` → 安装上述 5 个包（阿里云镜像）→ `git stash pop`，**补丁 6 处自动恢复成功**，`py_compile` 通过；
3. 启动验证：`/system_stats` 返回 `0.45.2 / frontend 1.58.5`，日志无 IMPORT FAILED / Traceback（仅 SeedVR2 的 Flash Attention 历史提示）。

**新增能力确认**：`CLIPLoader` 的 `type` 现包含 **`moss_image`**、`flux3`、`fibo2`、`yue2`、`joyimage` 等。

**回滚方法（三选一）**：
```powershell
cd D:\...\ComfyUI
git checkout v0.41.3
D:\...\python\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ `
  comfyui-frontend-package==1.55.17 comfyui-workflow-templates==0.11.87 `
  comfyui-embedded-docs==0.5.14 comfy-aimdo==0.5.6 comfy-kitchen==0.2.37
# 若 folder_paths.py 冲突，直接用 F:\ComfyUI_Migration\folder_paths.py.bak_0413 覆盖
```

---

## 二、MOSS 权重清单（全部校验通过）

| 文件 | 目录 | 体积 | 来源 |
|---|---|---|:--:|
| `Moody-Moss-Mix-V4.1_int8.safetensors` | `models/diffusion_models/` | 5.09 GB（4.74 GiB） | Civitai ver 3449754 / fileId 3349516，SHA256 `FA307E27…` ✅ |
| `qwen3.5_9b_w4a8_gptq.safetensors` | `models/text_encoders/` | 7.34 GB | ModelScope `Comfy-Org/MOSS-Image`，90 MB/s |
| `flux2-vae_small.safetensors` | `models/vae/` | 0.25 GB | 同上 |

加载：`UNETLoader` + `CLIPLoader(type=moss_image)` + `VAELoader(flux2-vae_small)`；采样 **25 步 / CFG 3 / euler + simple**（作者标注）。

**显存**：12G 全程无 OOM（TE 7.34 GB 自动 offload，峰值约 9~10 GB）。

---

## 三、三组实测（RTX 5070 12G / ComfyUI 0.45.2）

| 任务 | 分辨率 | 耗时 | 结果 |
|---|---|:--:|---|
| 英文写实人像 | 1024×1536 | **51.8 s** | ✅ **人像观感目前最好的一档**：韩系精致脸、皮肤细腻、眼神有戏；白衬衫褶皱与深灰裤质感优于 FLUX3 与 Krea2 官方 |
| 图内多字（便利店价签） | 1024×1536 | **28.2 s** | ✅ **「冰镇乌龙茶 / 500毫升 / 特价6元」三行全对、零错字**，黑体排版整齐，亚克力卡套 + 玻璃水汽质感真实 |
| 中文长提示词（库 id=1171，1941 字） | 1024×1536 | 34.5 s | ✅ 构图要素全中（人物占 3/5、单脚站、举掌、抬膝、紫缎带、白柱、花丛、窗户）；⚠️ 服装理解偏「暴露」（把「紫缎缠绕」理解成缎带内衣），人体结构完整但手指略乱 |

**横向对比（同题/同尺寸）**：

| 维度 | MOSS + Moody V4.1 | FLUX3 裸 | FLUX3 + Asian Mix | Qwen-Image 2.1 | Krea2 + Moody V8 |
|---|---|---|---|---|---|
| 亚洲脸好看度 | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 图内多字 | **⭐⭐⭐⭐⭐（3/3 零错）** | ⭐⭐（1/3） | — | ⭐⭐⭐⭐（3/3） | ⭐⭐ |
| 中文长提示词结构 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | — | ⭐⭐（人体崩） | — |
| 速度（1.5MP） | 28~52 s | 11~18 s | — | 36~42 s | 18~23 s |

---

## 四、结论

1. **升级本身是值的**：0.45.2 平稳落地，junction 补丁零改动即恢复，torch 未动，回滚成本低（git + 5 个包版本）。
2. **MOSS + Moody Moss Mix 是这台机器目前「脸最好 + 中文文字最强」的组合**，一次把两个短板补上：
   - 脸：韩系精致向，优于 FLUX3 裸版和 FLUX3+Asian Mix，与 Moody Krea2 V8 同级；
   - 图内中文：三行小字零错，比 Qwen21 更接近真实价签排版（也远好于 FLUX3 的 1/3）。
3. **代价**：速度 28~52 s/张（比 FLUX3 慢 2~3 倍，与 Qwen21 同档），且中文长提示词对「服装尺度」的理解偏松。
4. **主力线暂不动**：Krea2 V8（脸）+ Qwen21（文字）仍是最稳的双主力；MOSS 作为「要文字排版 + 要好看脸」时的首选备选，等社区再出几版微调可考虑升为主力。

---

## 五、工作流已固化（2026-11-12）

`通用工作流/MOSS_MossMixV41_文生图_25步CFG3_1024x1536.json`（10 节点）：UNETLoader + CLIPLoader(`moss_image`) + VAELoader(`flux2-vae_small`) + CLIPTextEncode + ConditioningZeroOut + EmptyLatentImage(1024×1536) + **KSampler(25 步 / CFG 3.0 / euler / simple)** + VAEDecode + SaveImage + MarkdownNote（含参数表、TE offload 说明、中文优势与提示词建议）。

**验证方式**：结构自检（连线双向一致、输出 links 一一对应）+ **真实浏览器加载**（playwright + chromium，`app.loadGraphData`）—— 10 节点全部就位，`KSampler.widgets_values = [seed, "randomize", 25, 3, "euler", "simple", 1]` 与实测一致。同法同时验证了两个 FLUX3 工作流（14 / 17 节点）。

## 六、图生图 / 指令编辑（2026-11-12 实测通过）

**MOSS 不只是文生图**，内核里有三个 MOSS 专用节点：

| 节点 | 作用 |
|---|---|
| **`TextEncodeMOSSImageEdit`** | 指令编辑：把 1~10 张参考图喂给文本编码器，输出 CONDITIONING（需配 edit LoRA） |
| `MOSSImageLayoutPrompt` | JSON 布局提示词（bbox 级排版控制） |
| `MOSSImageControl` | 颜色/深度控制（需 `moss_image_color_depth_control`） |
| `ModelMergeMOSSImage` | 模型合并 |

**编辑必需的 LoRA**：`moss_image_edit_lora_rank_64_bf16.safetensors`（0.30 GB，ModelScope `Comfy-Org/MOSS-Image/loras/`）→ 用 `LoraLoaderModelOnly` 挂在 UNET 之后。

**`TextEncodeMOSSImageEdit` 参数**：
- `prompt`：编辑指令
- `edit_format`：`Moss-Image-Edit`（官方 Comfy-Org 这个 LoRA 用这个）/ `ai-toolkit` / `ai-toolkit (kv_cache off)` —— 选错会"返回图但身份/构图漂移"
- `images`：1~10 张（autogrow），配 `vae` 时会编成 reference latents
- `image_strength`：默认 1.0，>1 强调参考图

**实测**：源图 1024×1536（F3K 人像）+ 中文指令「把白衬衫换成黑色皮夹克，内搭白 T，其余不变」，25 步 / CFG 3 / euler+simple：

| 项 | 结果 |
|---|---|
| 耗时 | **58.3 s** |
| 换装 | ✅ 黑色皮夹克（拉链/铆钉/肩章/口袋俱全）+ 白 T 恤 |
| 脸 / 姿势 / 机位 | ✅ 完全保留 |
| 背景 | ✅ 雨后街道与暖色路灯保留 |
| 偏差 | 裤子由深灰变浅灰（轻微漂移） |

对比 FLUX3 的单图编辑（24.2 s）：MOSS 慢 2.4 倍，但**皮革材质细节更足、脸的一致性更好**。

**关键坑（API 调用）**：`images` 是 `COMFY_AUTOGROW_V3`，在 `/prompt` 的 API JSON 里**不能用嵌套写法**，必须用点号前缀的**顶层键**：
```json
"6": {"class_type": "TextEncodeMOSSImageEdit",
      "inputs": {"clip": ["2",0], "prompt": "...", "edit_format": "Moss-Image-Edit",
                 "images.image_0": ["5",0], "image_strength": 1.0, "vae": ["3",0]}}
```
写成 `"images": [["5",0]]` 或 `"images": {"image_0": [...]}` 都报 `Required input is missing: image_0`。

## 七、待办
- [ ] `moss_image_edit_lora_rank_64`（0.3 GB）+ 颜色/深度控制（0.31 GB）未下，编辑链路未测
- [ ] MOSS 的 4KHD 工作流（作者 10-23 发）未测
- [ ] MOSS 图生图 / 局部重绘
- [ ] 高分辨率（2MP）显存与耗时
