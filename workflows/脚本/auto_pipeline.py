"""
一键自动管线：ZIT 场景 + Qwen 文字层 + PIL 合成
用法：python _auto_pipeline.py
"""
import urllib.request, json, os, time, glob, sys
from PIL import Image, ImageChops

COMFY_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = r"D:\Entertainment\ComfyUI-aki-v2\ComfyUI\output"

# ============================================================
# 1. 通用工具
# ============================================================
def submit_prompt(wf):
    data = json.dumps({"prompt": wf}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read())["prompt_id"]


def get_existing_files():
    return set(glob.glob(os.path.join(OUTPUT_DIR, "*.png")))


def wait_for_new_file(prefix, existing, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        current = set(glob.glob(os.path.join(OUTPUT_DIR, "*.png")))
        new = current - existing
        for f in sorted(new, key=lambda x: os.path.getmtime(x), reverse=True):
            if prefix in os.path.basename(f):
                return f
    return None


# ============================================================
# 2. ZIT V7 快速预览工作流 (640x960 -> 1088x1632)
# ============================================================
def make_zit_wf(prompt, negative, seed, prefix, glass_reflection=False):
    if glass_reflection:
        prompt += (
            "\n\nglass reflection, specular highlights, mirrored surface, "
            "environmental reflection, clear glass refraction, wet surface reflection, "
            "ray tracing, physically accurate lighting, visible reflection on floor"
        )
    return {
        "1": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"},
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "3": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "moodyRealMix_zitV7GlobalFP8.safetensors", "weight_dtype": "default"},
        },
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": negative}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": 640, "height": 960, "batch_size": 1}},
        "7": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["3", 0], "lora_name": "momoka-zib-v2_clean.safetensors", "strength_model": 1.0},
        },
        "8": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["7", 0], "lora_name": "zit_sda_v1.safetensors", "strength_model": 0.69},
        },
        "9": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["8", 0], "shift": 3.0}},
        "10": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["9", 0],
                "add_noise": "enable",
                "noise_seed": seed,
                "steps": 9,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde_gpu",
                "scheduler": "beta",
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
                "start_at_step": 0,
                "end_at_step": 9,
                "return_with_leftover_noise": "enable",
            },
        },
        "11": {
            "class_type": "LatentUpscaleBy",
            "inputs": {"samples": ["10", 0], "upscale_method": "bislerp", "scale_by": 1.7},
        },
        "12": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["9", 0],
                "add_noise": "enable",
                "noise_seed": seed + 1,
                "steps": 9,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde_gpu",
                "scheduler": "sgm_uniform",
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["11", 0],
                "start_at_step": 4,
                "end_at_step": 9,
                "return_with_leftover_noise": "disable",
            },
        },
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["2", 0]}},
        "14": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["13", 0]}},
    }


# ============================================================
# 3. Qwen 文字层工作流 (1024x1024)
# ============================================================
def make_qwen_wf(text, style, seed, prefix):
    if style == "neon":
        prompt = (
            f"Neon sign, glowing bright Chinese characters '{text}' on pure black background, "
            f"cyberpunk style, clean typography, no other objects, high contrast, 4K"
        )
        neg = "white background, people, scene, objects, blurry text, distorted characters"
    elif style == "print":
        prompt = (
            f"Minimalist graphic design, bold black Chinese text '{text}' on pure white background, "
            f"clean modern typography, no other elements, flat design, 4K"
        )
        neg = "colorful, scene, people, blurry, distorted, decorative"
    elif style == "screen":
        prompt = (
            f"Smartphone screen close-up, glowing white Chinese text '{text}' on pure black OLED screen, "
            f"dark mode UI, clean sans-serif font, no phone frame, no background, 4K"
        )
        neg = "colorful background, scene, people, blurry, decorative"
    else:
        prompt = text
        neg = "low quality, blurry, distorted"

    return {
        "1": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors", "type": "qwen_image", "device": "default"},
        },
        "2": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "3": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "qwen-image-2512-Q4_K_M.gguf"},
        },
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": neg}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["3", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
                "seed": seed,
                "steps": 30,
                "cfg": 4.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["2", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": prefix, "images": ["8", 0]}},
    }


# ============================================================
# 4. PIL 合成
# ============================================================
def composite(scene_path, text_path, output_path, position="top-center", style="neon", scale=0.6):
    scene = Image.open(scene_path).convert("RGBA")
    text_img = Image.open(text_path).convert("RGBA")

    # 文字层缩放到场景宽度的比例
    target_w = int(scene.width * scale)
    text_ratio = text_img.width / text_img.height
    new_w = target_w
    new_h = int(new_w / text_ratio)
    text_img = text_img.resize((new_w, new_h), Image.LANCZOS)

    # 基于风格生成蒙版
    r, g, b, a = text_img.split()
    gray = Image.merge("RGB", (r, g, b)).convert("L")

    if style in ("neon", "screen"):
        # 黑底 = 透明，亮色 = 保留（霓虹/屏幕风格）
        mask = gray.point(lambda x: 0 if x < 35 else min(255, x + 80))
    else:  # print - 白底 = 透明，黑字 = 保留
        mask = gray.point(lambda x: 0 if x > 230 else 255 - x)

    text_img.putalpha(mask)

    # 计算粘贴位置
    if position == "top-center":
        x = (scene.width - new_w) // 2
        y = int(scene.height * 0.05)
    elif position == "top-left":
        x = int(scene.width * 0.05)
        y = int(scene.height * 0.05)
    elif position == "center":
        x = (scene.width - new_w) // 2
        y = (scene.height - new_h) // 2
    elif position == "bottom-center":
        x = (scene.width - new_w) // 2
        y = int(scene.height * 0.78)
    elif position == "bottom-left":
        x = int(scene.width * 0.08)
        y = int(scene.height * 0.75)
    elif isinstance(position, (tuple, list)) and len(position) == 2:
        x, y = position
    else:
        x, y = 0, 0

    scene.paste(text_img, (x, y), text_img)
    scene.save(output_path)
    print(f"  -> 合成图已保存: {output_path}")
    return output_path


# ============================================================
# 5. 主控流程
# ============================================================
def run_pipeline(
    scene_prompt,
    scene_neg,
    text_content,
    text_style="neon",
    text_position="top-center",
    text_scale=0.6,
    seed=42,
    output_name="AutoComposite",
    glass_reflection=False,
):
    print("=" * 60)
    print("Phase 1: ZIT 场景生成 (V7 快速预览)")
    print("=" * 60)
    existing = get_existing_files()
    zit_wf = make_zit_wf(scene_prompt, scene_neg, seed, "AutoScene", glass_reflection)
    pid = submit_prompt(zit_wf)
    print(f"  已提交 prompt_id: {pid}")
    scene_file = wait_for_new_file("AutoScene", existing, timeout=300)
    if not scene_file:
        print("ERROR: ZIT 场景生成超时")
        return None
    print(f"  -> 场景图: {scene_file}")

    print("\n" + "=" * 60)
    print("Phase 2: Qwen 文字层生成")
    print("=" * 60)
    existing2 = get_existing_files()
    qwen_wf = make_qwen_wf(text_content, text_style, seed + 10000, "AutoText")
    pid2 = submit_prompt(qwen_wf)
    print(f"  已提交 prompt_id: {pid2}")
    text_file = wait_for_new_file("AutoText", existing2, timeout=300)
    if not text_file:
        print("ERROR: Qwen 文字层生成超时")
        return None
    print(f"  -> 文字层: {text_file}")

    print("\n" + "=" * 60)
    print("Phase 3: PIL 合成")
    print("=" * 60)
    out_path = os.path.join(OUTPUT_DIR, f"{output_name}_{seed}.png")
    composite(scene_file, text_file, out_path, position=text_position, style=text_style, scale=text_scale)
    return out_path


# ============================================================
# 6. 示例运行
# ============================================================
if __name__ == "__main__":
    # 示例：雨后便利店 + 霓虹招牌
    SCENE = (
        "Moody Photography, 20岁中国清纯可爱女孩，精致韩式妆容，韩风冷色调网红美白滤镜，极致冷白皮，通体雪白。\n\n"
        "雨后便利店前的霓虹诱惑\n"
        "午夜时分，她站在便利店玻璃门前，地面有大片积水形成镜面反射。"
        "黑色紧身短袖T恤，灰色百褶短裙。透明PVC高跟凉鞋，脚趾涂鲜艳玫红甲油。"
        "便利店暖黄色灯光从玻璃门透出，在她身上形成冷暖对比。"
        "背景有模糊的街道霓虹灯，在积水表面拉出长长的彩色光条。"
        "她侧脸看向镜头，表情慵懒。"
    )
    NEG = (
        "low quality, blurry, distorted, bad hands, text, watermark, "
        "abstract ground texture, ugly, deformed, extra limbs"
    )

    result = run_pipeline(
        scene_prompt=SCENE,
        scene_neg=NEG,
        text_content="24小时营业",
        text_style="neon",           # neon / print / screen
        text_position="top-center",  # top-center / center / bottom-center / (x,y)
        text_scale=0.55,
        seed=2024,
        output_name="Pipeline_Demo_Neon",
        glass_reflection=True,
    )

    if result:
        print(f"\n全部完成！最终文件: {result}")
