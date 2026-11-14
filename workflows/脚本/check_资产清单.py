# -*- coding: utf-8 -*-
r"""
资产清单 ↔ 磁盘 对照校验（防腐工具）

用途
    把 `文档\资产清单.md` 里登记的文件（模型权重、工作流 JSON）与磁盘实际情况对照，
    输出两个方向的漂移：
      A. 清单登记了但磁盘上没有（多半是已卸载／已挪进 历史工作流\ ）
      B. 磁盘上有但清单没登记（新装/新加的工作流容易漏记）

用法
    python check_资产清单.py                  # 打印报告
    python check_资产清单.py --full           # B 方向不限条数全部打印
    python check_资产清单.py --report out.txt # 同时写文件

路径约定（重要）
    本脚本放在 `workflows\脚本\` 下：
      workflows_root = 脚本目录的上一级（＝ ComfyUI\user\default\workflows，junction → F:）
      comfy_root     = workflows_root 上溯 3 级（＝ ComfyUI\，其下才有 models\）
    若你的 ComfyUI 主目录不在默认位置，可用 --models-root 显式指定。

设计原则：只读不写。校验结果由人工确认后才改 `资产清单.md`（清单里「用途」列是人工知识，不可自动覆盖）。
"""
import argparse
import io
import json
import os
import re
import sys

ASSET_EXTS = {".safetensors", ".gguf", ".ckpt", ".pth", ".pt", ".onnx", ".bin"}
SKIP_DIRS = {"_tmp", ".git", "__pycache__"}


def find_dir_by_name(start, name, max_up=6):
    """从 start 向上逐级找同名子目录（用于定位 models / 文档）。"""
    cur = os.path.abspath(start)
    for _ in range(max_up):
        cand = os.path.join(cur, name)
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _looks_like_models_dir(p):
    """判断是不是真正的 ComfyUI models 目录。

    只认含 diffusion_models / checkpoints / vae / text_encoders / unet 之一的目录，
    防止从 F: 真实路径运行时被上层仓库里那种"只挂了两个 lora 的空壳 models"骗过去，
    导致把 ComfyUI 实际模型全部误报成"清单有、磁盘无"。
    """
    if not os.path.isdir(p):
        return False
    return any(os.path.isdir(os.path.join(p, d))
               for d in ("diffusion_models", "checkpoints", "vae", "text_encoders", "unet"))


def find_models_root(start, max_up=6):
    """从 start 向上逐级找"像样"的 models 目录（跳过空壳）。"""
    cur = os.path.abspath(start)
    for _ in range(max_up):
        cand = os.path.join(cur, "models")
        if _looks_like_models_dir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def scan_models(models_root):
    """返回 {basename_lower: 绝对路径}"""
    found = {}
    for dirpath, dirnames, filenames in os.walk(models_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in ASSET_EXTS:
                found.setdefault(fn.lower(), os.path.join(dirpath, fn))
    return found


def scan_dir_jsons(*dirs):
    """扫描若干目录（含一层子目录）里的工作流 JSON。"""
    # 索引/清单类 JSON 不是工作流，不计入磁盘实际
    IGNORE = {"工作流清单.json"}
    found = {}
    for root in dirs:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth >= 2:
                dirnames[:] = []
                continue
            for fn in filenames:
                # 跳过隐藏文件（.merkle-snapshot.json 这类索引/快照，不是工作流）
                if fn.startswith(".") or fn in IGNORE:
                    continue
                if fn.lower().endswith(".json"):
                    found.setdefault(fn.lower(), os.path.join(dirpath, fn))
    return found


def backticked(text):
    return re.findall(r"`([^`\n]+)`", text)


def classify_token(tok):
    """把反引号里的 token 归一成 (类型, 文件名)，非资产返回 None。"""
    tok = tok.strip().strip("`")
    if not tok or "\n" in tok:
        return None
    if " " in tok or tok.startswith("-") or tok.startswith("--"):
        return None
    if "{" in tok or "}" in tok or "<" in tok:   # 命名模板占位符，不是真实文件
        return None
    base = re.split(r"[\\/]", tok)[-1]          # 去掉路径前缀
    base = base.split("（")[0].split("(")[0].strip()
    ext = os.path.splitext(base)[1].lower()
    if ext in ASSET_EXTS:
        return ("模型", base)
    if ext == ".json" and re.search(r"[\u4e00-\u9fff]|_", base):
        return ("工作流", base)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-root", default=None, help="ComfyUI\\models 绝对路径")
    ap.add_argument("--full", action="store_true", help="B 方向全部打印")
    ap.add_argument("--report", default=None, help="把报告同时写入该文件")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    workflows_root = os.path.dirname(here)
    comfy_root = os.path.dirname(os.path.dirname(os.path.dirname(workflows_root)))
    # 反向兜底：若从 F: 真实路径运行，comfy_root 可能不对，则向上找"像样"的 models 目录
    # （空壳 models 只含 loras 之类，会被 _looks_like_models_dir 跳过）
    if not _looks_like_models_dir(os.path.join(comfy_root, "models")):
        alt = find_models_root(workflows_root)
        if alt:
            comfy_root = os.path.dirname(alt)
    models_root = args.models_root or os.path.join(comfy_root, "models")
    doc_dir = os.path.join(workflows_root, "文档")

    o = io.StringIO()
    o.write(f"workflows_root = {workflows_root}\ncomfy_root     = {comfy_root}\nmodels_root    = {models_root}\n")

    manifest_path = os.path.join(doc_dir, "资产清单.md")
    if not os.path.isfile(manifest_path):
        sys.exit(f"找不到清单：{manifest_path}")
    text = open(manifest_path, encoding="utf-8").read()
    o.write(f"清单           = {manifest_path}\n")

    # ---- 磁盘实际 ----
    disk_models = scan_models(models_root) if os.path.isdir(models_root) else {}
    wf_root = workflows_root
    # 2026-11-06 起工作流已迁到「通用工作流/」，2026-11-11 起本脚本把这两个子目录一并算作“当前在用”
    cur_dirs = [
        wf_root,
        os.path.join(workflows_root, "通用工作流"),
        os.path.join(workflows_root, "图库专用工作流"),
    ]
    hist = os.path.join(workflows_root, "历史工作流")
    disk_wf = scan_dir_jsons(*cur_dirs, hist)

    # ---- 清单登记 ----
    # 逐行解析：明确标注"已归档 / 已删除 / 找不到"的行不算"在用登记"（清单里就是这么写的）
    # 注意：不能只匹配 "❌"——工作流速查表里"骨骼控图"列的取值就是 ❌，会误伤整行。
    # 2026-11-11 修：原来要求行内不出现「历史工作流 / 已归档」，导致 1.1 里带
    # “实验数据已归档至 `_cleanup/…`”的说明行被整行跳过（等于没登记）。
    # 现在只认“明确指向归档位置的写法”（`历史工作流\` 在反引号内）与 ❌ 前缀。
    SKIP_LINE = re.compile(r"未找到|已无此文件|已废弃|勿照抄|❌\s*`|`历史工作流[\\/]|`workflows_local_bak")
    reg_models, reg_wf, skipped = {}, {}, []
    for line in text.splitlines():
        if SKIP_LINE.search(line):
            skipped.append(line.strip()[:80])
            continue
        for tok in backticked(line):
            c = classify_token(tok)
            if not c:
                continue
            kind, base = c
            (reg_models if kind == "模型" else reg_wf)[base.lower()] = base
    o.write(f"（按行跳过的“已归档/已缺失”行：{len(skipped)} 行）\n")

    def report(kind, reg, disk, extra_disk=None, title=""):
        miss = sorted(v for k, v in reg.items() if k not in disk)
        unreg = sorted(((k, os.path.basename(v)) for k, v in disk.items() if k not in reg),
                       key=lambda kv: kv[1].lower())
        o.write(f"\n=== {kind}{title} ===\n")
        o.write(f"清单登记 {len(reg)} 项 ／ 磁盘实际 {len(disk)} 项\n")
        o.write(f"\n[A] 清单有、磁盘无（{len(miss)} 项）\n")
        for m in miss:
            hint = ""
            if extra_disk and m.lower() in extra_disk:
                hint = f"   ← 实际在 {extra_disk[m.lower()]}"
            o.write(f"  ✗ {m}{hint}\n")
        o.write(f"\n[B] 磁盘有、清单未登记（{len(unreg)} 项）\n")
        shown = unreg if args.full else unreg[:25]
        for k, name in shown:
            o.write(f"  + {name}   ({os.path.relpath(disk[k], comfy_root)})\n")
        if len(shown) < len(unreg):
            o.write(f"  … 其余 {len(unreg) - len(shown)} 项略（--full 看全部）\n")
        return miss, unreg

    # 模型：磁盘另一处（外层 ComfyUI-aki-v3\models）作为“挪走了”的提示来源
    outer_models = os.path.join(os.path.dirname(comfy_root), "models")
    outer_disk = scan_models(outer_models) if os.path.isdir(outer_models) else {}
    report("模型资产", reg_models, disk_models, outer_disk)

    # 工作流：区分“当前在用”与“历史工作流”
    cur = scan_dir_jsons(*cur_dirs)

    def scan_all_jsons(root):
        """递归扫全部层级（历史工作流里的子目录也要能提示“实际在哪”）。"""
        found = {}
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.startswith(".") or fn in {"工作流清单.json"}:
                    continue
                if fn.lower().endswith(".json"):
                    found.setdefault(fn.lower(), os.path.join(dirpath, fn))
        return found

    hist_disk = scan_all_jsons(hist)
    wf_cur = {k: v for k, v in cur.items() if os.path.dirname(v) in cur_dirs}
    report("工作流", reg_wf, wf_cur, hist_disk,
           title="（对照 根目录 + 通用工作流\\ + 图库专用工作流\\，不含 历史工作流\\）")

    # ---------- 交叉校验：工作流清单.json（Atelier 机器视图） ↔ 资产清单 1.1/1.2（人读视图） ----------
    # 两套记录并存是对的（一份给程序认身份、一份给人讲用法），但必须能自动比对，否则会漂。
    # 清单是 Atelier 的运行数据，默认在 脚本\atelier\data\；库根旧位置只作兼容回退
    # （库根 = ComfyUI\user\default\workflows，放根目录会被它的工作流列表列出来、点开报错）。
    def atelier_manifest_path():
        explicit = os.environ.get("ATELIER_DATA_DIR")
        candidates = []
        if explicit:
            candidates.append(os.path.join(explicit, "工作流清单.json"))
        candidates.append(os.path.join(workflows_root, "脚本", "atelier", "data", "工作流清单.json"))
        candidates.append(os.path.join(workflows_root, "工作流清单.json"))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return candidates[0]

    manifest_path = atelier_manifest_path()
    sec11, sec12, section = {}, {}, None
    for line in text.splitlines():
        if line.startswith("### 1.1"):
            section = "1.1"
            continue
        if line.startswith("### 1.2"):
            section = "1.2"
            continue
        if line.startswith("### 1.3") or line.startswith("## "):
            section = None
            continue
        if section is None or SKIP_LINE.search(line):
            continue
        for tok in backticked(line):
            c = classify_token(tok)
            if c and c[0] == "工作流":
                (sec11 if section == "1.1" else sec12)[c[1].lower()] = c[1]

    o.write("\n=== 交叉校验（工作流清单.json ↔ 资产清单 1.1/1.2） ===\n")
    if not os.path.isfile(manifest_path):
        o.write("  工作流清单.json 不存在，跳过（可跑 脚本/atelier/tools/gen_workflow_manifest.py 生成）\n")
    else:
        try:
            mf = json.loads(open(manifest_path, encoding="utf-8").read())
        except ValueError as exc:
            mf = {}
            o.write(f"  工作流清单.json 解析失败：{exc}\n")
        mfw = mf.get("workflows", []) if isinstance(mf, dict) else []
        active = {w["name"].lower(): w for w in mfw if w.get("status") == "active"}
        archived = {w["name"].lower(): w for w in mfw if w.get("status") != "active"}
        drift = []
        for k, w in sorted(active.items()):
            if k not in sec11:
                drift.append(f"  ✗ 清单 active 但不在 1.1：{w['name']}（清单 file={w.get('file')}）")
        for k, w in sorted(archived.items()):
            if k in sec11:
                drift.append(f"  ✗ 已归档但仍在 1.1：{w['name']}（清单 file={w.get('file')}）")
        manifest_names = {w["name"].lower() for w in mfw}
        for k in sorted({os.path.basename(v).lower() for v in wf_cur.values()} - manifest_names):
            drift.append(f"  ✗ 磁盘有但清单未收录：{k}（重跑 gen_workflow_manifest.py）")
        o.write(f"  清单 active={len(active)} / archived={len(archived)}；"
                f"资产清单 1.1={len(sec11)} 项、1.2={len(sec12)} 项\n")
        if drift:
            o.write(f"  发现 {len(drift)} 处漂移（改任一侧后都要同步另一侧）：\n")
            for d in drift:
                o.write(d + "\n")
        else:
            o.write("  ✅ 两侧一致\n")

    out = o.getvalue()
    try:  # Windows 控制台默认 GBK，遇到符号会崩
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(out)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[报告已写入] {args.report}")


if __name__ == "__main__":
    main()
