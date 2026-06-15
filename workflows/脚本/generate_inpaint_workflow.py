import json
import argparse
import os
import sys
import shutil

# 模板路径：脚本位于 workflows/脚本/，模板在上一级目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS_DIR = os.path.dirname(SCRIPT_DIR)
TEMPLATE_NAME = "MoodyZIT_V7_Inpaint_图生图_自动遮罩.json"
TEMPLATE_PATH = os.path.join(WORKFLOWS_DIR, TEMPLATE_NAME)


def main():
    parser = argparse.ArgumentParser(
        description="根据模板生成 Inpaint 工作流 JSON。\n"
                    "遮罩目标通过 PowerPrimitive 统一输入，同时控制 GroundingDINO 分割和负向提示词。"
    )
    parser.add_argument(
        "--target",
        default="短裤",
        help="遮罩目标（支持中文！如 短裤 / 长发 / 红色的裙子 / 手表）",
    )
    parser.add_argument(
        "--positive",
        default="long apricot yellow skirt",
        help="正向提示词：要在遮罩区域生成的内容（建议英文）",
    )
    parser.add_argument(
        "--output",
        default="",
        help="输出文件路径，留空则覆盖原模板并自动备份",
    )
    args = parser.parse_args()

    if not os.path.exists(TEMPLATE_PATH):
        print(f"[错误] 找不到模板文件: {TEMPLATE_PATH}")
        sys.exit(1)

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    # 新节点结构：
    #   节点 37 (RgthreePowerPrimitive) — 统一字符串输入
    #     → 节点 36 (GroundingDinoSAMSegment) prompt  — 遮罩分割目标
    #     → 节点 12 (CLIPTextEncode) text             — 负向提示词
    #   节点 10 (CLIPTextEncode) text                  — 正向提示词（独立）
    workflow["37"]["inputs"]["value"] = args.target
    workflow["10"]["inputs"]["text"] = args.positive

    # 输出处理
    if args.output:
        out_path = args.output
    else:
        backup_path = TEMPLATE_PATH + ".backup"
        if not os.path.exists(backup_path):
            shutil.copy2(TEMPLATE_PATH, backup_path)
            print(f"[备份] 原文件已备份到: {backup_path}")
        out_path = TEMPLATE_PATH

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(workflow, f, ensure_ascii=False, indent=2)

    print(f"[成功] 工作流已保存到: {out_path}")
    print(f"  - 遮罩目标 (PowerPrimitive → GroundingDINO + 负向提示): {args.target}")
    print(f"  - 正向提示 (KSampler+):                              {args.positive}")
    print("\n提示：遮罩目标支持中文！PowerPrimitive 同时控制分割目标和负向提示词。")


if __name__ == "__main__":
    main()
