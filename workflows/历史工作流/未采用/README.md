# 未采用 / 已下线工作流（归档区）

本目录存放**曾经可用或曾经试过、但已判定不应出现在合成台下拉**的工作流。
文件保留是为了可回溯、可修复后回收，**不会被任何扫描目录读到**：

- `/api/workflows?scope=studio` 的 `studio_dirs()` 只扫 `图库专用工作流/`、`我的工作流/`、
  上游 `ai-pose-gallery-zh/src/workflows/`、`历史工作流/画廊旧版/`、库根；
- `/api/workflows`（通用列表）的 `search_dirs()` 只扫库根与 `通用工作流/`。

所以放进这里 = 从 UI 消失，但 JSON 还在，方便复查或修好后拿回去。

## 归档规则

1. **能崩服务、能稳定 400、跑不出图的** → 归档到这里，并在下表登记原因与证据；
2. 只是"效果不如另一个"的 → 不要归档，留在原目录，由 `README` 的「适用场景」说明取舍；
3. 归档时**必须**同步更新 `图库专用工作流/README.md` 与 `脚本/atelier/tests/test_workflow_catalog.py`
   里的 `STUDIO_ROLE_WORKFLOWS` 基线（否则测试会红）。

## 清单

| 文件 | 归档日期 | 原因 | 证据 |
|---|---|---|---|
| `图库专用_QwenEdit_Nunchaku-fp4_三图_4步_低显存.api.json` | 2026-11-06 | 连续出图会把整个 ComfyUI 进程打崩（原生 abort，非 Python 异常），服务消失后任务全部失败 | 单图 `pose` 成功（16s），第 2 组 `portrait+pose` 执行中 `dequantize_blocks_Q6_K` → `Fatal Python error: Aborted`（退出码 3），后续组 `WinError 10061` 连接拒绝。两轮独立复现 |
| `PornMaster_Flux2Klein9B_三图角色合成_6步_自动尺寸.api.json` | 2026-11-06 | 视觉质量不合格：姿势几乎不复现、服装配色漂、腿部结构错位 | 三图齐全 40s 出图（`output/trim-matrix/fs241`）：参考姿势是坐地单膝立起，出图是站立抬腿且膝关节错位（A2）；参考粉色牛仔裙出成蓝色（C3）；姿势还原 1.5/5。同 seed 的 Flux 四图版（`fs242`）一模一样 |
| `PornMaster_Flux2Klein9B_四图参考_6步_自动尺寸.api.json` | 2026-11-06 | 同上，且第 4 张 extra 实测没有额外约束效果 | `output/trim-matrix/fs242`：与三图版出图几乎一致（第二张 extra 是同一张服装图副本） |
| `图库专用_QwenEdit_GGUF-Q5KM_三图_4步_全身构图.api.json` | 2026-11-06 | 与「标准」版同模型同 seed 出图几乎一致（同质冗余），保留只会让下拉多一个无法区分的选项 | `output/trim-matrix/fs250` 与 `output/trim-matrix-b3/fs245`（标准版仅姿势）**逐像素级相同**；三图组合 `fs251/fs253` 与标准版 `b3/fs246`、`b3/fs248` 质量同级（C5/P1、脸 2–2.5） |
| `图库专用_QwenEdit_GGUF-Q5KM_三图_4步_全身构图_自动裁切.api.json` | 2026-11-06 | 同上 + 人像+姿势组合出废图（画面被半透明横纹割裂、手指融合） | `output/trim-matrix-b2/fs241`：人脸被一条半透明胶带状横纹切开，右手多指融合，可用性报废（A1.5/E2）；其余组合与标准版同级 |
| `图库专用_QwenEdit_GGUF-Q5KM_三图_4步_标准.api.json` | 2026-11-06 | 2509 版：脸 2 分、加服装后脸崩、仅姿势多腿/脚趾糊（曾是 2511 的上一代） | `output/trim-matrix-b3/fs245`（多腿）、`b3/fs248`（脸 2） |
| `图库专用_QwenEdit-2511_三图_4步_标准.api.json` | 2026-11-06 | 抢救后（Q5_0 基座）F4.5 / C4 / **P2.5–3** / A4.5：姿势仍不做，4→8 步无效、叠 VNCCS 姿势 LoRA 会抹掉人物；各项被 Qwen21 压制，只快约 1 分钟 → 用户拍板只留 Qwen21 | `output/studio-opt-qwenedit-v3`（F4.5/P3）、`output/studio-matrix-qe2511`（4 组合）；对比见 `文档/…实测矩阵_20261106.md` §4.4 |

> 归档不等于删除：修好（换模型 / 改进节点接线 / 加 ControlNet 姿势控制）后可以直接搬回
> `图库专用工作流/`，同时把 `tests/test_workflow_catalog.py` 的 `STUDIO_ROLE_WORKFLOWS` 加回去。
