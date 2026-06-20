"""
JoyCaption Beta1 GGUF 图生提示词 自动化回归测试
====================================================
  1. 从数据库选取有产出图的 prompt 样本
  2. 逐张送入 JoyCaption 工作流反推提示词
  3. 对比原始 prompt 与反推结果（BLEU / Cosine）
  4. 输出量化评分报告

  依赖: pip install httpx scikit-learn
  前置: ComfyUI 必须已在 http://127.0.0.1:8188 运行
"""

import json
import sys
import time
import sqlite3
from pathlib import Path

import httpx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ─── 路径配置 ───────────────────────────────────────────
# ComfyUI-aki-v3 根目录 (不使用 __file__，避免符号链接追踪到旧环境)
COMFYUI_AKI_ROOT = Path(r"D:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3")
WORKFLOW_DIR   = COMFYUI_AKI_ROOT / "workflows"
DB_PATH        = WORKFLOW_DIR / "文档" / "提示词收藏.db"
JC_WORKFLOW    = WORKFLOW_DIR / "JoyCaption_Beta1_API_图生提示词.json"
SCRIPT_DIR     = WORKFLOW_DIR / "脚本"

# ComfyUI 安装目录（秋叶启动器结构: ComfyUI-aki-v3/ComfyUI/）
COMFYUI_ROOT    = COMFYUI_AKI_ROOT / "ComfyUI"
COMFYUI_OUTPUT  = COMFYUI_ROOT / "output"
COMFYUI_API     = "http://127.0.0.1:8188"
REPORT_PATH     = SCRIPT_DIR / "joycaption_test_report.json"
POLL_INTERVAL   = 3        # 轮询间隔（秒）
MAX_WAIT        = 180      # 单图最长等待（秒）
SAMPLE_COUNT    = 8        # 测试样本数

# ─── 1. 从数据库选取样本 ────────────────────────────────
def load_samples(n: int = SAMPLE_COUNT) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, p.name, p.prompt, p.negative_prompt,
               h.filename, h.subfolder
        FROM gen_history h
        JOIN prompts p ON h.prompt_id = p.id
        WHERE h.img_type = 'output'
          AND p.prompt IS NOT NULL
          AND p.prompt != ''
        GROUP BY p.id
        ORDER BY p.id
        LIMIT ?
    """, (n,))
    rows = cur.fetchall()
    conn.close()

    samples = []
    for r in rows:
        filename = r[4]
        # DB 中 subfolder 可能是旧环境的绝对路径，只取文件名在当前 output 目录查找
        img_path = COMFYUI_OUTPUT / filename
        if not img_path.is_file():
            # fallback: 去掉旧路径前缀，用纯文件名查找
            clean_name = Path(filename).name
            img_path = COMFYUI_OUTPUT / clean_name
        if not img_path.is_file():
            print(f"  [WARN] 图片不存在: {filename} (checked: {img_path})，跳过")
            continue
        samples.append({
            "prompt_id": r[0],
            "name": r[1],
            "original_prompt": r[2],
            "negative_prompt": r[3] or "",
            "image_path": str(img_path),
        })
    print(f"  有效样本: {len(samples)} / {n} 条")
    return samples


# ─── 2. ComfyUI API 封装 ────────────────────────────────
def comfyui_alive() -> bool:
    try:
        r = httpx.get(f"{COMFYUI_API}/system_stats", timeout=3)
        return r.is_success
    except Exception:
        return False


def push_workflow(api_workflow: dict) -> str:
    """提交工作流，返回 prompt_id"""
    body = json.dumps({"prompt": api_workflow}).encode("utf-8")
    r = httpx.post(
        f"{COMFYUI_API}/prompt",
        content=body,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    if not r.is_success:
        detail = r.text[:500] if r.text else "no body"
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    data = r.json()
    pid = data.get("prompt_id")
    if not pid:
        raise RuntimeError(f"ComfyUI 未返回 prompt_id: {data}")
    return pid


def get_history(prompt_id: str) -> dict | None:
    try:
        r = httpx.get(f"{COMFYUI_API}/history/{prompt_id}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def cancel_queue():
    try:
        httpx.post(f"{COMFYUI_API}/interrupt", timeout=3)
        httpx.post(f"{COMFYUI_API}/queue", content=b'{"clear": true}',
                   headers={"Content-Type": "application/json"}, timeout=3)
    except Exception:
        pass


def wait_for_result(prompt_id: str, timeout: int = MAX_WAIT) -> dict | None:
    """轮询直到任务完成或超时"""
    elapsed = 0
    while elapsed < timeout:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        hist = get_history(prompt_id)
        if hist and prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status", {})
            if status.get("completed", False):
                return entry
            if status.get("status_str") == "error":
                print(f"    ComfyUI 报错: {entry.get('exception', 'unknown')}")
                return None
    print(f"    [WARN] 超时 ({timeout}s)")
    return None


# ─── 3. 工作流注入 ──────────────────────────────────────
def load_jc_workflow() -> dict:
    with open(JC_WORKFLOW, "r", encoding="utf-8") as f:
        return json.load(f)


def inject_image(workflow: dict, image_path: str) -> dict:
    """将图片路径注入 LoadImage 节点（节点 id=1）"""
    wf = json.loads(json.dumps(workflow))  # deep copy
    wf["1"]["inputs"]["image"] = image_path
    return wf


def extract_text(result: dict, prompt_id: str) -> str | None:
    """从 ComfyUI 历史结果中提取 ShowText 节点输出"""
    entry = result.get(prompt_id, {})
    outputs = entry.get("outputs", {})
    # 节点 id=4 是 ShowText
    text_node = outputs.get("4", {})
    text = text_node.get("text", [])
    if isinstance(text, list) and len(text) > 0:
        return text[0]
    if isinstance(text, str):
        return text
    return None


# ─── 4. 相似度评估 ──────────────────────────────────────
def compute_similarity(original: str, generated: str) -> dict:
    """计算 BLEU-1 和 TF-IDF Cosine 相似度"""
    import re

    def tokenize(s: str) -> str:
        # 简单分词：中文按字、英文按空格+标点分离
        s = s.lower().strip()
        # 保留中英文和数字，标点转空格
        s = re.sub(r"[^\w\u4e00-\u9fff]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    orig_tok = tokenize(original)
    gen_tok  = tokenize(generated)

    if not orig_tok or not gen_tok:
        return {"bleu1": 0.0, "cosine": 0.0}

    # BLEU-1 (unigram precision)
    orig_words = orig_tok.split()
    gen_words  = gen_tok.split()
    if not orig_words or not gen_words:
        return {"bleu1": 0.0, "cosine": 0.0}
    match_count = sum(1 for w in gen_words if w in orig_words)
    bleu1 = match_count / len(gen_words) if gen_words else 0.0

    # TF-IDF Cosine
    try:
        vec = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b").fit([orig_tok, gen_tok])
        m = vec.transform([orig_tok, gen_tok])
        cosine = cosine_similarity(m[0:1], m[1:2])[0][0]
    except ValueError:
        cosine = 0.0

    return {"bleu1": round(bleu1, 4), "cosine": round(float(cosine), 4)}


# ─── 5. 主流程 ──────────────────────────────────────────
def main():
    print("=" * 70)
    print("  JoyCaption Beta1 GGUF 图生提示词 回归测试")
    print("=" * 70)

    # 5.1 连通性检查
    if not comfyui_alive():
        print("\n[FAIL] ComfyUI 未运行！请先启动 ComfyUI (http://127.0.0.1:8188)")
        sys.exit(1)
    print("[OK] ComfyUI 在线")

    # 5.2 加载样本
    samples = load_samples(SAMPLE_COUNT)
    if len(samples) < 3:
        print("[FAIL] 有效样本不足，无法测试")
        sys.exit(1)

    # 5.3 加载工作流
    jc_wf = load_jc_workflow()
    print(f"[OK] 工作流已加载: {JC_WORKFLOW.name}")

    # 5.4 逐样本测试
    results = []
    print(f"\n开始测试 {len(samples)} 个样本...\n")

    for i, s in enumerate(samples):
        name = s["name"]
        img  = s["image_path"]
        print(f"[{i+1}/{len(samples)}] {name}")
        print(f"    图片: {Path(img).name}")

        # 注入图片
        wf = inject_image(jc_wf, img)

        # 提交
        try:
            pid = push_workflow(wf)
        except Exception as e:
            print(f"    [FAIL] 提交失败: {e}")
            results.append({**s, "generated": None, "error": str(e)})
            continue

        # 等待完成
        print(f"    prompt_id={pid[:8]}... 等待中", end="", flush=True)
        result = wait_for_result(pid)
        if result is None:
            results.append({**s, "generated": None, "error": "timeout or error"})
            print(" [FAIL]")
            continue
        print(" [OK]")

        # 提取文本
        text = extract_text(result, pid)
        if text is None:
            results.append({**s, "generated": None, "error": "no text output"})
            print("    [FAIL] 未获取到文本输出")
            continue

        # 相似度
        sim = compute_similarity(s["original_prompt"], text)
        results.append({
            **s,
            "generated": text,
            "bleu1": sim["bleu1"],
            "cosine": sim["cosine"],
            "error": None,
        })
        print(f"    BLEU-1={sim['bleu1']:.3f}  Cosine={sim['cosine']:.3f}")
        print(f"    原始: {s['original_prompt'][:100]}...")
        print(f"    反推: {text[:100]}...")
        print()

    # 5.5 汇总报告
    success = [r for r in results if r["generated"] is not None]
    failed  = [r for r in results if r["generated"] is None]

    print("=" * 70)
    print("  测试汇总")
    print("=" * 70)
    print(f"  总样本: {len(results)}")
    print(f"  成功:   {len(success)}")
    print(f"  失败:   {len(failed)}")

    if success:
        bleus  = [r["bleu1"]  for r in success]
        cosines = [r["cosine"] for r in success]
        print(f"\n  BLEU-1  均值: {sum(bleus)/len(bleus):.4f}")
        print(f"  BLEU-1  范围: {min(bleus):.4f} ~ {max(bleus):.4f}")
        print(f"  Cosine  均值: {sum(cosines)/len(cosines):.4f}")
        print(f"  Cosine  范围: {min(cosines):.4f} ~ {max(cosines):.4f}")

    if failed:
        print(f"\n  失败详情:")
        for f in failed:
            print(f"    - {f['name']}: {f['error']}")

    # 5.6 保存详细报告
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "config": {
                "workflow": str(JC_WORKFLOW.name),
                "sample_count": len(samples),
                "success_count": len(success),
                "failed_count": len(failed),
            },
            "summary": {
                "bleu1_avg": sum(bleus)/len(bleus) if success else 0,
                "cosine_avg": sum(cosines)/len(cosines) if success else 0,
            } if success else {},
            "results": [
                {
                    "name": r["name"],
                    "original": r["original_prompt"],
                    "generated": r["generated"],
                    "bleu1": r.get("bleu1"),
                    "cosine": r.get("cosine"),
                    "error": r["error"],
                }
                for r in results
            ],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[REPORT] 详细报告已保存: {REPORT_PATH}")


if __name__ == "__main__":
    main()
