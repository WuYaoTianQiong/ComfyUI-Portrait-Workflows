# 编辑时守卫：硬编码颜色 / 巨型文件冻结 / 混合行尾。
#
# 双层用法（守卫口径单一实现，pre-commit 与 CI 共用本脚本）：
#   --staged          pre-commit：只查暂存区内容（秒级）
#   --all             CI / 手动全量：扫描守卫范围
#   --write-baseline  重新冻结体量基线（拆分文件后维护用）
#
# 三道检查：
#   1) 颜色  .vue <style> 块内十六进制色值必须为 0（与 ci.ps1 原逻辑同口径：只看 <style>，
#      <script> 里的色值可能是写库的数据色板）。新色值走 styles/tokens.css + var(--token)。
#   2) 体量  范围内 >= LIMIT 行的文件逐个冻结在 file_size_baseline.txt：只减不增，
#      不在基线的新巨型文件直接拦。拆分是正路，人工豁免 = 同 commit 更新基线并注明理由。
#   3) 行尾  单个文件内 \r\n 与裸 \n 混存 = 被脚本批量替换改坏（README 约定：匹配要用 \r?\n）。
#      暂存模式下代码扩展名 BLOCK，文档类（.md 等）只 WARN；全量模式只扫守卫范围。
#
# 退出码：0 = PASS；1 = FAIL（有 BLOCK 项）。

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ATELIER_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
).stdout.strip())

LIMIT = 1500  # 巨型文件阈值（行）
BASELINE = ATELIER_ROOT / "tools" / "file_size_baseline.txt"

# 体量检查范围（相对 atelier 根）：.vue / 非 spec 非 d.ts 的 .ts / app 下 .py
SCOPE = [
    (ATELIER_ROOT / "frontend/src", {".vue"}),
    (ATELIER_ROOT / "frontend/src", {".ts"}),
    (ATELIER_ROOT / "app", {".py"}),
]
SIZE_EXCLUDE_SUFFIX = (".spec.ts", ".d.ts")
SIZE_EXCLUDE_PART = "__pycache__"

# 暂存模式下混合行尾 BLOCK 的扩展名（其余文本文件只 WARN，避免卡用户文档提交）
CRLF_BLOCK_SUFFIX = (
    ".py", ".ts", ".tsx", ".vue", ".js", ".jsx", ".mjs", ".cjs",
    ".css", ".scss", ".html", ".json", ".ps1", ".psm1", ".bat", ".cmd", ".sh",
)
CRLF_BINARY_SUFFIX = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".heic",
    ".pdf", ".zip", ".gz", ".7z", ".db", ".sqlite", ".wav", ".mp4", ".mov",
)

STYLE_BLOCK_RE = r"(?s)<style[^>]*>(.*?)</style>"
COLOR_RE = r"#[0-9a-fA-F]{3,8}\b"


def fail(msg: str) -> None:
    print(f"  [X] {msg}")


def warn(msg: str) -> None:
    print(f"  [!] {msg}")


# ---------- 暂存区 ----------

def staged_files() -> list[str]:
    """暂存区新增/修改的文件（仓库根相对路径，\\0 分隔避免中文转义问题）。"""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT"],
        capture_output=True, check=True,
    )
    return [p.decode("utf-8") for p in out.stdout.split(b"\0") if p]


def staged_content(rel: str) -> str | None:
    """读暂存文件的工作区内容。行尾检查必须在 git 归一化前的字节上做：
    autocrlf=true 时 index 里的 blob 已统一成 LF，从 index 读看不出混合行尾。"""
    p = REPO_ROOT / rel
    if p.is_file():
        return p.read_bytes().decode("utf-8", errors="replace")
    out = subprocess.run(["git", "show", f":{rel}"], capture_output=True, check=False)
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", errors="replace")


# ---------- 检查 1：硬编码颜色 ----------

def count_colors(text: str) -> int:
    import re
    total = 0
    for block in re.findall(STYLE_BLOCK_RE, text):
        total += len(re.findall(COLOR_RE, block))
    return total


def check_color(vue_paths: list[str], contents: dict[str, str]) -> list[str]:
    offenders = []
    for rel in vue_paths:
        n = count_colors(contents[rel])
        if n:
            offenders.append(f"{rel}({n})")
    return offenders


# ---------- 检查 2：巨型文件冻结 ----------

def in_size_scope(rel_path: Path) -> bool:
    for root, exts in SCOPE:
        try:
            rel_path.relative_to(root)
        except ValueError:
            continue
        if rel_path.suffix in exts and not rel_path.name.endswith(SIZE_EXCLUDE_SUFFIX):
            if SIZE_EXCLUDE_PART not in rel_path.parts:
                return True
    return False


def read_baseline() -> dict[str, int]:
    if not BASELINE.is_file():
        return {}
    entries = {}
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rel, _, num = line.partition("\t")
        entries[rel] = int(num)
    return entries


def check_size(items: list[tuple[str, int]], baseline: dict[str, int]) -> tuple[list[str], list[str]]:
    """items: (atelier 相对路径, 行数)。返回 (blockers, prunable)。"""
    blockers, prunable = [], []
    for rel, lines in items:
        frozen = baseline.get(rel)
        if frozen is None:
            if lines >= LIMIT:
                blockers.append(f"{rel} 新增巨型文件 {lines} 行（阈值 {LIMIT}），不在冻结基线")
        elif lines > frozen:
            blockers.append(f"{rel} 已冻结 {frozen} 行，当前 {lines} 行（+{lines - frozen}）——先拆分，或同 commit 更新基线并注明理由")
        elif lines < frozen:
            prunable.append(f"{rel} {frozen} → {lines} 行，可 --write-baseline 收紧基线")
    return blockers, prunable


def scan_all_size() -> list[tuple[str, int]]:
    items = []
    for root, exts in SCOPE:
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in exts:
                continue
            if p.name.endswith(SIZE_EXCLUDE_SUFFIX) or SIZE_EXCLUDE_PART in p.parts:
                continue
            text = p.read_bytes().decode("utf-8", errors="replace")
            items.append((p.relative_to(ATELIER_ROOT).as_posix(), text.count("\n")))
    return sorted(items)


# ---------- 检查 3：混合行尾 ----------

def mixed_endings(text: str) -> bool:
    crlf = text.count("\r\n")
    bare_lf = text.count("\n") - crlf
    return crlf > 0 and bare_lf > 0


# ---------- 主流程 ----------

def run(staged: bool) -> int:
    baseline = read_baseline()
    blocked = 0

    if staged:
        rels = staged_files()
        contents: dict[str, str] = {}
        for rel in rels:
            text = staged_content(rel)
            if text is not None:
                contents[rel] = text

        # 1) 颜色：暂存的 .vue（工作区 .vue 只有 frontend/src，全查）
        vue = {rel: t for rel, t in contents.items() if rel.endswith(".vue")}
        offenders = check_color(list(vue), vue)
        if offenders:
            blocked += 1
            print("颜色守护（基线 0）：")
            for o in offenders:
                fail(f"{o} —— 在 styles/tokens.css 加令牌，页面写 var(--token)")
        # 2) 体量：暂存的范围内文件（rel 是仓库根相对路径，先拼绝对再转 atelier 相对）
        items = []
        for rel, t in contents.items():
            abs_p = REPO_ROOT / rel
            if in_size_scope(abs_p):
                items.append((abs_p.relative_to(ATELIER_ROOT).as_posix(), t.count("\n")))
        blockers, prunable = check_size(sorted(items), baseline)
        if blockers:
            blocked += 1
            print(f"体量冻结（阈值 {LIMIT} 行，基线 {BASELINE.name}）：")
            for b in blockers:
                fail(b)
        for m in prunable:
            warn(m)
        # 3) 行尾：暂存的所有文本文件
        mixed_block, mixed_warn = [], []
        for rel, t in contents.items():
            p = Path(rel)
            if p.suffix.lower() in CRLF_BINARY_SUFFIX or "\x00" in t:
                continue
            if mixed_endings(t):
                (mixed_block if p.suffix.lower() in CRLF_BLOCK_SUFFIX else mixed_warn).append(rel)
        if mixed_block or mixed_warn:
            print("混合行尾（\\r\\n 与裸 \\n 同文件混存 = 被脚本改坏，替换要用 \\r?\\n）：")
            for rel in mixed_block:
                blocked += 1
                fail(rel)
            for rel in mixed_warn:
                warn(f"{rel}（文档类，仅提醒不阻断）")
    else:
        # --all：CI / 手动全量
        size_items = scan_all_size()
        offenders = []
        for root, exts in SCOPE:
            if exts != {".vue"}:
                continue
            for p in root.rglob("*.vue"):
                text = p.read_bytes().decode("utf-8", errors="replace")
                n = count_colors(text)
                if n:
                    offenders.append(f"{p.relative_to(ATELIER_ROOT).as_posix()}({n})")
        blockers, prunable = check_size(size_items, baseline)
        mixed = []
        for root_s in sorted({str(r) for r, _ in SCOPE}):  # SCOPE 里 frontend/src 出现两次，去重
            for p in Path(root_s).rglob("*"):
                if not p.is_file() or p.suffix.lower() in CRLF_BINARY_SUFFIX:
                    continue
                if SIZE_EXCLUDE_PART in p.parts:
                    continue
                t = p.read_bytes()
                if b"\x00" in t:
                    continue
                if mixed_endings(t.decode("utf-8", errors="replace")):
                    mixed.append(p.relative_to(ATELIER_ROOT).as_posix())
        if offenders:
            blocked += 1
            print("颜色守护（基线 0）：")
            for o in offenders:
                fail(f"{o} —— 在 styles/tokens.css 加令牌，页面写 var(--token)")
        if blockers:
            blocked += 1
            print(f"体量冻结（阈值 {LIMIT} 行）：")
            for b in blockers:
                fail(b)
        for m in prunable:
            warn(m)
        if mixed:
            blocked += 1
            print("混合行尾（\\r\\n 与裸 \\n 同文件混存 = 被脚本改坏，替换要用 \\r?\\n）：")
            for rel in mixed:
                fail(rel)

    n_size = len(baseline)
    total = "FAIL" if blocked else "PASS"
    print(f"GUARD {total}（颜色 / 体量基线 {n_size} 个 / 行尾）")
    return 1 if blocked else 0


def write_baseline() -> None:
    items = scan_all_size()
    big = [(rel, n) for rel, n in items if n >= LIMIT]
    lines = [
        "# 巨型文件冻结基线 —— tools/guard_limits.py 的判据",
        f"# 规则：范围(frontend/src + app)内 >= {LIMIT} 行的文件逐个冻结，行数只减不增；",
        "#       新增超阈值文件会被拦。拆分后跑 --write-baseline 重新冻结。",
        "#       人工豁免：同 commit 更新本文件并在下面注明理由与日期。",
        "# 排除：*.spec.ts / *.d.ts（生成物）/ __pycache__；.py 仅 app/。",
        "# 冻结日期：2026-11-21（首次冻结；历史回潮见状态文档 §1.4 守卫小节）",
        "",
    ]
    lines += [f"{rel}\t{n}" for rel, n in big]
    BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写入 {BASELINE.relative_to(REPO_ROOT)}：{len(big)} 个文件 >= {LIMIT} 行")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="编辑时守卫：颜色/体量/行尾")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="只查暂存区（pre-commit）")
    g.add_argument("--all", action="store_true", help="全量扫描守卫范围（CI）")
    g.add_argument("--write-baseline", action="store_true", help="重新冻结体量基线")
    args = ap.parse_args()
    if args.write_baseline:
        write_baseline()
        return 0
    return run(staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
