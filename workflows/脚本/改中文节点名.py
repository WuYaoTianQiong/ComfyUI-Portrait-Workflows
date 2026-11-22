# -*- coding: utf-8 -*-
"""把「通用工作流/」里没有标题的节点补成中文名。

原则：
  - **只补空标题**，已有标题（尤其是带序号的人工标题）一律不动；
  - LoadImage 只给「载入图片」这类中性名 —— Atelier 靠标题里的「人像/服装/姿势/附加」
    判定槽位角色，中性名不引入关键词，行为与"无标题"一致；
  - 子图实例（类型是 UUID）跳过，标题由子图自己决定。

用法： python 改中文节点名.py [--check]
"""
import argparse
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(HERE, "..", "通用工作流")

TITLES = {
    "UNETLoader": "加载底模",
    "CLIPLoader": "加载文本编码器",
    "VAELoader": "加载 VAE",
    "LoraLoaderModelOnly": "加载 LoRA",
    "VAEDecode": "图像解码",
    "VAEEncode": "图像编码",
    "VAEEncodeForInpaint": "局部重绘编码",
    "VAEDecodeAudio": "音频解码",
    "SaveImage": "保存图片",
    "SaveImageFromSource": "按源图名保存",
    "SaveVideo": "保存视频",
    "LoadImage": "载入图片",
    "CLIPTextEncode": "提示词编码",
    "TextEncodeQwenImage21": "Qwen 提示词编码",
    "TextEncodeMOSSImageEdit": "MOSS 编辑指令",
    "ConditioningZeroOut": "负向提示词清零",
    "EmptyLatentImage": "空白画布",
    "EmptyFlux2LatentImage": "空白画布（Flux2）",
    "EmptyImage": "空白图片",
    "ResolutionSizer": "画幅（比例 + 像素量）",
    "ResolutionSelector": "画幅（比例 + 像素量）",
    "KSampler": "采样器",
    "KSamplerAdvanced": "采样器（高级）",
    "KSamplerSelect": "采样器选择",
    "RandomNoise": "随机种子",
    "SamplerCustomAdvanced": "高级采样",
    "BasicGuider": "基础引导",
    "CFGGuider": "CFG 引导",
    "BasicScheduler": "步数计划",
    "Flux2Scheduler": "步数计划（Flux2）",
    "LatentUpscaleBy": "潜空间放大",
    "ReferenceLatent": "注入参考图",
    "ImageResizeKJ": "参考图等比缩放",
    "ImageScale": "缩放图片",
    "ImageScaleToTotalPixels": "缩放到目标像素",
    "GetImageSize": "读取图片尺寸",
    "ImageCompositeMasked": "遮罩合成",
    "ImageToMask": "图片转遮罩",
    "MaskToImage": "遮罩转图片",
    "ThresholdMask": "阈值遮罩",
    "InvertMask": "反相遮罩",
    "Image Comparer (rgthree)": "前后对比",
    "PlaySound|pysssss": "完成提示音",
    "easy cleanGpuUsed": "释放显存",
    "PrimitiveFloat": "数值",
    "ComfyMathExpression": "数学表达式",
    "CreateVideo": "合成视频",
    "MiniMaxH3ImageToVideo": "图生视频",
    "SeedVR2LoadDiTModel": "加载超分模型",
    "SeedVR2LoadVAEModel": "加载超分 VAE",
    "ResolutionPickerPlus": "超分档位",
    "SeedVR2VideoUpscaler": "视频超分",
    "FaceRestoreModelLoader": "加载人脸修复模型",
    "FaceRestoreCFWithModel": "人脸修复",
    "LazySwitchKJ": "开关（人脸修复）",
    "Note": "说明",
    "MarkdownNote": "说明",
}


def is_subgraph_type(t: str) -> bool:
    return len(t) == 36 and t.count("-") == 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    for path in sorted(glob.glob(os.path.join(WF_DIR, "*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        changed, unknown = [], set()
        for n in d.get("nodes", []):
            t = n.get("type", "")
            if is_subgraph_type(t):
                continue
            if (n.get("title") or "").strip():
                continue
            cn = TITLES.get(t)
            if cn:
                changed.append((n.get("id"), t, cn))
                if not args.check:
                    n["title"] = cn
            else:
                unknown.add(t)
        if changed:
            total += len(changed)
            print("%-42s +%d 个中文标题" % (os.path.basename(path), len(changed)))
        if unknown:
            print("%-42s 未收录类型: %s" % (os.path.basename(path), ", ".join(sorted(unknown))))
        if changed and not args.check:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    print("\n合计补标题 %d 个%s" % (total, "（--check 未写盘）" if args.check else ""))


if __name__ == "__main__":
    main()
