# -*- coding: utf-8 -*-
"""给工作流补「怎么改出图尺寸」的说明卡 + 把尺寸节点标题改成带实际像素。

背景：ComfyUI 里改尺寸只有 ResolutionSelector（比例 + 像素量 MiP）两个控件，
宽高被连线锁在 EmptyLatentImage 上，改不动也看不出会出多大。本脚本：
  1. 把 ResolutionSelector 的标题重建成 `④ 画幅｜9:16 · 2.4 → 1192×2112`；
  2. 在工作流里插入/更新一张 MarkdownNote（MiP → 实际像素速查 + 改法 + 坑）；
  3. 对字面量尺寸的编辑类工作流，把 EmptyLatentImage 标题标成「输出尺寸，直接改」。

用法： python 补尺寸说明.py            # 全部按内置清单处理
      python 补尺寸说明.py --check    # 只报当前状态，不写文件
"""
import argparse
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(HERE, "..", "通用工作流")

RATIOS = [("1:1", 1, 1), ("2:3", 2, 3), ("3:2", 3, 2), ("3:4", 3, 4),
          ("4:3", 4, 3), ("9:16", 9, 16), ("16:9", 16, 9), ("21:9", 21, 9)]
UNIT = 1024 * 1024  # ResolutionSelector 的 megapixels 单位是 MiP


def pixels(a, b, mp, mult=8):
    w = math.sqrt(mp * UNIT * a / b)
    h = w * b / a
    return max(mult, int(round(w / mult)) * mult), max(mult, int(round(h / mult)) * mult)


def ratio_from_option(opt):
    """'9:16 (Portrait Widescreen)' -> (9,16,'9:16')"""
    tag = opt.split("(")[0].strip()
    if ":" not in tag:
        return None
    a, b = tag.split(":")
    return int(a), int(b), tag


def table_md(mps, current_mp, current_ratio):
    cols = [("2:3", 2, 3), ("3:4", 3, 4), ("9:16", 9, 16), ("1:1", 1, 1), ("16:9", 16, 9)]
    head = "| 像素量 | " + " | ".join(c[0] + " 竖" if c[2] > c[1] else c[0] for c in cols) + " |"
    sep = "|---|" + "---|" * len(cols)
    lines = [head, sep]
    for mp in mps:
        cells = []
        for name, a, b in cols:
            w, h = pixels(a, b, mp)
            mark = " **← 当前**" if abs(mp - current_mp) < 1e-6 and name == current_ratio else ""
            cells.append("%d×%d%s" % (w, h, mark))
        lines.append("| %s | %s |" % (mp, " | ".join(cells)))
    return "\n".join(lines)


def note_t2i(name, ratio, mp, w, h):
    mps = sorted({0.55, 1.0, 1.5, float(mp), 2.16, 2.4})
    return """## 改出图尺寸：只动「画幅」这一个节点

左边那个 **分辨率** 节点只有两个控件：

- **aspect_ratio**：比例下拉（1:1 / 2:3 / 3:4 / 9:16 / 3:2 / 4:3 / 16:9 / 21:9）
- **megapixels**：总像素量。**单位是 MiP＝1024×1024**，不是 100 万像素——
  填 2.4 实际约 2.52 MP，所以数字和出图尺寸不是直觉换算。

%s

**当前：%s · %s → %d×%d**

### 三个常改方向

- 想快（草稿/试构图）：`megapixels` 改 **0.55**，约 7~8 s/张
- 想稳出大图：保持 **2.16 ~ 2.4**（本机 12G 下 2.4 峰值约 11 GB）
- 只换比例（尺寸不变）：只动 `aspect_ratio`，`megapixels` 不用碰

### 两个坑

1. **别去改下面的「空 latent」宽高** —— 它的 width/height 被连线锁住（灰色），
   改了不生效，实际尺寸永远由画幅节点决定。
2. **本工作流没有 9:21（竖长图）**：`21:9` 出的是横图。真要 9:21，只能把空 latent 的
   width/height 右键 **「转换为输入」** 断开设画幅的连线，再手填 1024×2400 之类；
   或直接在 Atelier 里选 9:21（那边会用字面量下发）。
""" % (table_md(mps, mp, ratio), ratio, mp, w, h)


def note_literal(name, w, h):
    return """## 改出图尺寸：直接改「输出尺寸」那两个数

这是个**编辑类**工作流：尺寸不走画幅节点，而是固定 latent。找到标题写着
**「输出尺寸（直接改）」** 的 `EmptyLatentImage`，把 width / height 改成你要的即可
（保持 16 的倍数）。

- 当前：**%d×%d**
- 常见竖图：832×1216 · 896×1344 · 1024×1536 · 1088×1632
- 改大很吃显存：12G 上 1024×1536 已是舒适上限，1536×2304 会明显变慢甚至 OOM
- 编辑类的**构图**由参考图决定，改尺寸只改输出画布，不会把人物放大
""" % (w, h)


def note_follow_input(name):
    return """## 输出尺寸跟着输入图走

这个工作流不设固定画幅：主图用 `ImageResizeKJ` 保持原尺寸（对齐 16 的倍数），
第二张参考图用 `ImageScaleToTotalPixels` 缩到 **1.5 MiP**。

想改输出大小：

- **换输入图的分辨率**最直接（输出 ≈ 主图原尺寸）
- 或改 `ImageScaleToTotalPixels.megapixels`（只影响参考图，不直接改输出画布）
- 想强制某个成品尺寸：在 `VAEDecode` 后接 `ImageScale`/`ImageResizeKJ`，
  或在 `EmptyFlux2LatentImage`（若有）里手填宽高
"""


SECTION_MARK = "改出图尺寸：只动"


def append_note(d, text, near_pos):
    """把尺寸说明**追加**到工作流原有说明卡末尾（绝不覆盖原内容）。"""
    for n in d["nodes"]:
        if n.get("type") in ("MarkdownNote", "Note"):
            cur = (n.get("widgets_values") or [""])[0]
            if SECTION_MARK in cur:
                cur = cur.split("\n\n---\n\n" + text.split("\n")[0])[0]
            n["widgets_values"] = [cur.rstrip() + "\n\n---\n\n" + text]
            w, h = (n.get("size") or [520, 600])[:2]
            n["size"] = [max(w, 520), max(h, 620)]
            return n["id"], False
    nid = d.get("last_node_id", 0) + 1
    d["last_node_id"] = nid
    d["nodes"].append({
        "id": nid, "type": "MarkdownNote",
        "pos": [near_pos[0], near_pos[1] + 200], "size": [560, 700],
        "flags": {}, "order": len(d["nodes"]), "mode": 0,
        "inputs": [], "outputs": [],
        "properties": {"Node name for S&R": "MarkdownNote", "cnr_id": "comfy-core"},
        "widgets_values": [text],
    })
    return nid, True


TARGETS = [
    "PornMaster_Krea2V4_T2I_INT8_1Pass.json",
    "MoodyKrea2_V8SE_T2I_FP8_1Pass.json",
    "Qwen21_T2I_INT8_1Pass.json",
    "Flux3Klein_T2I_INT8_1Pass.json",
    "MossMixV41_T2I_INT8_1Pass.json",
]
LITERAL = {
    "Flux3Klein_Edit_INT8_1Pass.json": None,
    "MossMixV41_Edit_INT8_1Pass.json": None,
}
FOLLOW = [
    "PornMaster_Flux2Klein9B_Edit_FP8_1Pass.json",
    "PornMaster_Flux2Klein9B_Ref2_FP8_1Pass.json",
    "PornMaster_Flux2Klein9B_Ref3_FP8_1Pass.json",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    for name in TARGETS + list(LITERAL) + FOLLOW:
        path = os.path.join(WF_DIR, name)
        if not os.path.isfile(path):
            print("[跳过] 不存在:", name)
            continue
        d = json.load(open(path, encoding="utf-8"))
        sel = next((n for n in d["nodes"] if n.get("type") == "ResolutionSelector"), None)
        lat = next((n for n in d["nodes"] if n.get("type") in
                    ("EmptyLatentImage", "EmptyFlux2LatentImage")), None)

        if name in TARGETS and sel:
            opt, mp, mult = sel["widgets_values"][0], float(sel["widgets_values"][1]), int(sel["widgets_values"][2])
            info = ratio_from_option(opt)
            if not info:
                print("[警告] 比例无法解析:", name, opt)
                continue
            a, b, tag = info
            w, h = pixels(a, b, mp, mult)
            old_title = sel.get("title") or ""
            prefix = old_title.split("画幅")[0] if "画幅" in old_title else ""
            new_title = "%s画幅｜%s · %s → %d×%d" % (prefix, tag, mp, w, h)
            print("%-46s %s -> %d×%d  (title: %s)" % (name, opt, w, h, new_title))
            if args.check:
                continue
            sel["title"] = new_title
            append_note(d, note_t2i(name, tag, mp, w, h), sel.get("pos") or [0, 0])

        elif name in LITERAL and lat:
            w, h = lat["widgets_values"][0], lat["widgets_values"][1]
            print("%-46s 字面量 %d×%d" % (name, w, h))
            if args.check:
                continue
            lat["title"] = "输出尺寸（直接改这两个数）"
            append_note(d, note_literal(name, w, h), lat.get("pos") or [0, 0])

        elif name in FOLLOW:
            print("%-46s 跟随输入图" % name)
            if args.check:
                continue
            append_note(d, note_follow_input(name), [100, 100])

        else:
            print("[跳过] 结构不符:", name)
            continue

        if not args.check:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
