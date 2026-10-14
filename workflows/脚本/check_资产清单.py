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
import os
import re
import sys
import io

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
    # 反向兜底：若从 F: 真实路径运行，comfy_root 可能不对，则向上找带 models 的目录
    if not os.path.isdir(os.path.join(comfy_root, "models")):
        alt = find_dir_by_name(workflows_root, "models")
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
    hist = os.path.join(workflows_root, "历史工作流")
    disk_wf = scan_dir_jsons(wf_root, hist)

    # ---- 清单登记 ----
    # 逐行解析：明确标注"已归档 / 已删除 / 找不到"的行不算"在用登记"（清单里就是这么写的）
    # 注意：不能只匹配 "❌"——工作流速查表里"骨骼控图"列的取值就是 ❌，会误伤整行。
    SKIP_LINE = re.compile(r"已归档|未找到|已无此文件|已废弃|勿照抄|❌\s*`|历史工作流|workflows_local_bak")
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
    cur = scan_dir_jsons(wf_root)
    hist_disk = scan_dir_jsons(hist)
    wf_cur = {k: v for k, v in cur.items() if os.path.dirname(v) == wf_root}
    report("工作流", reg_wf, wf_cur, hist_disk, title="（对照的是 workflows 根目录，不含 历史工作流\\）")

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
