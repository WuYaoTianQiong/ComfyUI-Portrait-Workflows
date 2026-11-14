"""UI 事实守护（unslop 体检批次 4，2026-11-14）：只量可核对的事实，不打分好不好看。

红灯（回归 set，体检批次 1–4 修掉的东西不许回来）：
  1. 模板里的彩色 emoji（1F000-1FAFF / 2B00-2BFF / FE0F）；单色排版符号 ✓✕★☆♥✎☰ 等不算
  2. transition 简写（=all）或 transition-property: all
  3. font-size < 11px（令牌下限 --fs-xs）
  4. 圆角方言 18px / 20px / 9999px（全局刻度 4/6/8/10/14 + pill 999 + 50%）
  5. 令牌对比度对 < 4.5:1（明暗两套各自算）

用法：python tools/style_lint.py [--root <frontend src>]；有红灯 exit 1。
CI 里目前只作警告步（不阻断），升级门禁待拍板。
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent / "frontend" / "src"
if "--root" in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index("--root") + 1])

EMOJI = re.compile(r"[\U0001F000-\U0001FAFF⬀-⯿️]")
TRANSITION = re.compile(r"transition:\s*(?:all\b|[\d.]+m?s\s*;)|transition-property:\s*all")
FONTSIZE = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px")
RADIUS = re.compile(r"border-radius:\s*(18px|20px|9999px)\s*;")
COMMENT = re.compile(r"^\s*(\*|//|/\*)")

PAIRS = [
    ("--text", "--bg"),
    ("--muted", "--panel"),
    ("--on-primary", "--primary"),
    ("--accent-link", "--bg"),
    ("--text-faint", "--surface-raised"),
]


def lum(hexstr):
    v = int(hexstr.lstrip("#"), 16)
    chans = []
    for shift in (16, 8, 0):
        c = ((v >> shift) & 255) / 255
        chans.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def token_blocks(css_text):
    """返回 {theme: {var: hex}}，只收 hex 值（rgba 跳过）。"""
    blocks = {"dark": {}, "light": {}}
    theme = "dark"
    for line in css_text.splitlines():
        if line.startswith(":root[data-theme='light']"):
            theme = "light"
        elif line.startswith(":root"):
            theme = "dark"
        m = re.match(r"\s*(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", line)
        if m:
            blocks[theme][m.group(1)] = m.group(2)
    return blocks


def main():
    reds = []
    for path in sorted(ROOT.rglob("*.vue")):
        if path.name.endswith(".spec.ts"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if COMMENT.match(line):
                continue
            rel = path.relative_to(ROOT)
            if EMOJI.search(line):
                reds.append(f"emoji      {rel}:{n}  {line.strip()[:60]}")
            if TRANSITION.search(line):
                reds.append(f"transition {rel}:{n}  {line.strip()[:60]}")
            m = FONTSIZE.search(line)
            if m and float(m.group(1)) < 11:
                reds.append(f"font<11px  {rel}:{n}  {line.strip()[:60]}")
            if RADIUS.search(line):
                reds.append(f"radius方言 {rel}:{n}  {line.strip()[:60]}")
    for path in sorted(ROOT.rglob("*.css")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if TRANSITION.search(line):
                reds.append(f"transition {path.relative_to(ROOT)}:{n}  {line.strip()[:60]}")
    blocks = token_blocks((ROOT / "styles" / "tokens.css").read_text(encoding="utf-8"))
    for theme, vals in blocks.items():
        for fg, bg in PAIRS:
            if fg in vals and bg in vals:
                r = ratio(vals[fg], vals[bg])
                if r < 4.5:
                    reds.append(f"contrast   {theme} {fg}/{bg} = {r:.2f} (<4.5)")
    if reds:
        print(f"STYLE_LINT RED {len(reds)}")
        for r in reds:
            print("  " + r)
        return 1
    print("STYLE_LINT PASS 0 red (emoji/transition/font-floor/radius/contrast)")
    return 0


if __name__ == "__main__":
    sys.exit(main())