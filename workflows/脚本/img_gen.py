"""
图片生成工具：从提示词收藏.db读取提示词，提交ComfyUI V7工作流生成高清图片
用法：
  python img_gen.py --serve                # 启动API服务（含HTML前端）
  python img_gen.py --ids 1 2 3            # 指定ID生成
  python img_gen.py --all                   # 全部生成
  python img_gen.py --ids 1 --count 3      # ID:1 生成3张（不同seed）
"""
import urllib.request, json, os, time, glob, sys, sqlite3, io, random, argparse, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

COMFY_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = r"D:\Entertainment\ComfyUI-aki-v2\ComfyUI\output"
DB_PATH = r"D:\Entertainment\ComfyUI-aki-v2\workflows\文档\提示词收藏.db"
API_HOST = "0.0.0.0"
API_PORT = 8199

DEFAULT_NEG = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
    "fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, "
    "signature, watermark, username, blurry, artist name, "
    "background people, crowd, other people, multiple persons, "
    "cropped feet, missing feet, cut off feet, "
    "cropped head, cut off head, head out of frame, feet out of frame, "
    "close-up, portrait, tight crop, face only, upper body only, "
    "half body, cropped body, 人物被裁切, 头被切掉, 脚被切掉, "
    "extra toes, missing toes, fused toes, deformed feet, "
    "foot mutation, extra feet, 脚趾变形, 脚部涂鸦, "
    "chromatic aberration, light leak, lens flare, neon glow, "
    "colorful reflection, rainbow reflection, 光斑, 色散, 光污染, "
    "彩虹反光, 彩色光斑, "
    "(ground graffiti:1.5), (ground painting:1.4), (colored marks on ground:1.4), "
    "(neon reflection on ground:1.3), (colorful ground spots:1.3), "
    "ground doodle, ground scribble, painted asphalt, glowing floor"
)

GLASS_REFLECTION_SUFFIX = (
    "\n\ndark matte asphalt road, plain dark ground, no reflection, no glow, "
    "no colorful light on ground, no neon reflection, no light spots on floor, "
    "no shiny surface, no water sheen"
)

# 雨天场景中，正面提示词里容易触发地面涂鸦/彩色光斑的关键词 → 替换为安全描述
GROUND_GRAFFITI_REPLACEMENTS = {
    "地面有自然水渍反光": "地面是深色柏油",
    "路面有自然水渍反光": "路面颜色偏深",
    "水渍反光": "深色路面",
    "自然水渍": "干燥深色路面",
    "湿润深色柏油路面": "深色柏油路面",
    "湿润深色": "深色",
    "湿地面": "深色地面",
    "湿路面": "深色路面",
    "路面反光": "深色路面",
    "地面反光": "深色地面",
    "水洼反光": "深色路面",
    "积水反光": "深色路面",
    "diffused water sheen": "matte dark surface",
    "wet ground reflection": "dark matte ground",
    "puddle highlights": "dark flat surface",
    "wet surface": "matte surface",
}

COLD_WHITE_SUFFIX = (
    "\n\n韩风冷色调网红美白滤镜，极致冷白皮，白嫩幼，overexposure，通体雪白。"
    "高清现实主义风格，细节丰富，动态光影，脚趾自然舒展，真实脚部结构，8K超清。"
)

MATERIAL_NEG_SUFFIX = (
    ", leather pants, leather texture, leather clothing, shiny pants, vinyl, "
    "patent leather, glossy fabric, plastic texture, "
    "(leather material:1.5), (shiny leather:1.4), (glossy pants:1.3), "
    "faux leather, PU leather, wet look fabric"
)

MATERIAL_ENHANCEMENTS = {
    "牛仔": "（哑光棉质牛仔布，非皮革，非光泽材质，真实牛仔纹理）",
    "棉质": "（哑光棉质材质，非光泽，自然纹理）",
    "针织": "（柔软针织材质，哑光，非皮革）",
    "短裤": "（棉质或牛仔材质，哑光，非皮革，非光泽）",
    "裤子": "（棉质或牛仔材质，哑光，非皮革，非光泽）",
}

GLASS_KEYWORDS = ["便利店", "冰柜", "玻璃", "雨", "水洼", "积水"]
COLD_WHITE_KEYWORDS = ["Moody Photography", "冷白皮", "通体雪白"]

ASPECT_RATIOS = {
    "portrait_2_3": (768, 1152),
    "portrait_9_16": (768, 1344),
    "portrait_tall": (832, 1216),
    "portrait_hd": (1024, 1536),
    "portrait_wide": (1024, 1536),
}


def submit_prompt(wf):
    data = json.dumps({"prompt": wf}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def comfy_get(path):
    r = urllib.request.urlopen(f"{COMFY_URL}{path}", timeout=10)
    return json.loads(r.read())


def delete_old_files(prefix, max_retries=3, retry_delay=2):
    old_files = glob.glob(os.path.join(OUTPUT_DIR, f"{prefix}_*.png"))
    if not old_files:
        return True
    for f in old_files:
        for attempt in range(max_retries):
            try:
                os.remove(f)
                break
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise RuntimeError(f"无法删除文件（被占用）: {f}")
            except Exception as e:
                raise RuntimeError(f"删除文件失败: {f}, 错误: {e}")
    return True


def check_prompt_error(prompt_id):
    """检查ComfyUI执行是否出错，返回错误信息或None"""
    try:
        r = urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=5)
        history = json.loads(r.read())
        entry = history.get(prompt_id, {})
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            msgs = status.get("messages", [])
            for m in msgs:
                if len(m) >= 2 and m[0] == "execution_error":
                    err = m[1]
                    node = err.get("node_type", "?")
                    msg = err.get("exception_message", "unknown")[:200]
                    return f"ComfyUI执行错误 @ {node}: {msg}"
            return "ComfyUI执行错误(未知详情)"
    except Exception:
        pass
    return None


def wait_for_new_file(prefix, existing, timeout=600, prompt_id=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        # 检查ComfyUI执行错误
        if prompt_id:
            err = check_prompt_error(prompt_id)
            if err:
                raise RuntimeError(err)
        current = set(glob.glob(os.path.join(OUTPUT_DIR, "*.png")))
        new = current - existing
        for f in sorted(new, key=lambda x: os.path.getmtime(x), reverse=True):
            if prefix in os.path.basename(f):
                return f
    return None


def get_existing_files():
    return set(glob.glob(os.path.join(OUTPUT_DIR, "*.png")))


def make_v7_full_wf(
    prompt,
    negative,
    seed,
    prefix,
    width=1024,
    height=1536,
    moody_strength=0.50,
    base_steps=14,
    refine_steps=14,
    skip_usu=False,
    usu_upscale=1.3,
    usu_tile=1024,
    usu_denoise=0.15,
    usu_steps=2,
):
    base_end = max(1, int(base_steps * 0.70))
    refine_start = max(1, int(refine_steps * 0.45))

    wf = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "moodyRealMix_zitV7GlobalFP8.safetensors", "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "4": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["1", 0], "lora_name": "momoka-zib-v2_clean.safetensors", "strength_model": 1.0},
        },
        "5": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["4", 0], "lora_name": "zit_sda_v1.safetensors", "strength_model": moody_strength},
        },
        "6": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["5", 0], "shift": 3.0},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "8": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": prompt},
        },
        "9": {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["8", 0]},
        },
        "10": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["6", 0],
                "add_noise": "enable",
                "noise_seed": seed,
                "steps": base_steps,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "beta",
                "positive": ["8", 0],
                "negative": ["9", 0],
                "latent_image": ["7", 0],
                "start_at_step": 0,
                "end_at_step": base_end,
                "return_with_leftover_noise": "enable",
            },
        },
        "11": {
            "class_type": "LatentUpscaleBy",
            "inputs": {"samples": ["10", 0], "upscale_method": "bislerp", "scale_by": 1.5},
        },
        "12": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["6", 0],
                "add_noise": "enable",
                "noise_seed": seed + 1,
                "steps": refine_steps,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "sgm_uniform",
                "positive": ["8", 0],
                "negative": ["9", 0],
                "latent_image": ["11", 0],
                "start_at_step": refine_start,
                "end_at_step": 999,
                "return_with_leftover_noise": "disable",
            },
        },
        "13": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["12", 0], "vae": ["3", 0]},
        },
    }

    if skip_usu:
        wf["14"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix + "_base", "images": ["13", 0]}
        }
    else:
        wf["14"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": "4xNomos8k_atd_jpg.safetensors"},
        }
        wf["15"] = {
            "class_type": "UltimateSDUpscale",
            "inputs": {
                "image": ["13", 0],
                "model": ["6", 0],
                "positive": ["8", 0],
                "negative": ["9", 0],
                "vae": ["3", 0],
                "upscale_by": usu_upscale,
                "seed": seed + 2,
                "steps": usu_steps,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "sgm_uniform",
                "denoise": usu_denoise,
                "upscale_model": ["14", 0],
                "mode_type": "Linear",
                "tile_width": usu_tile,
                "tile_height": usu_tile,
                "mask_blur": 64,
                "tile_padding": 96,
                "seam_fix_mode": "None",
                "seam_fix_denoise": 1.0,
                "seam_fix_width": 64,
                "seam_fix_mask_blur": 8,
                "seam_fix_padding": 16,
                "force_uniform_tiles": True,
                "tiled_decode": False,
                "batch_size": 1,
            },
        }
    wf["16"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": prefix, "images": ["15", 0]}
    }
    return wf


def make_sdxl_wf(prompt, negative, seed, prefix, width=1024, height=1536, ckpt="Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"):
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": ckpt},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": prompt},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": negative},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": 30,
                "cfg": 7.0,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "denoise": 1.0,
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix + "_sdxl", "images": ["6", 0]},
        },
    }


def make_gguf_wf(prompt, negative, seed, prefix, width=1024, height=1536,
                  gguf_name="flux1-dev-Q8_0.gguf",
                  apply_loras=True, moody_strength=0.50,
                  base_steps=14, refine_steps=14,
                  skip_usu=False, usu_upscale=1.3, usu_tile=1024,
                  usu_denoise=0.15, usu_steps=2,
                  preview=False):
    """GGUF量化工作流（Q8_0/Q4_K_S通用）：UNET用UnetLoaderGGUF，CLIP用DualCLIPLoader（T5-XXL+CLIP-L）。
    注意：GGUF模型与LoRA不兼容（ForgeParams4bit detach()错误），apply_loras=True时会跳过LoRA。
    preview=True时：低分辨率(512x768)、4步单pass、无超分，用于快速验证。
    """
    is_preview = preview
    if is_preview:
        width, height = 512, 768
        base_steps = 4
        skip_usu = True

    # GGUF模型与LoRA不兼容，强制禁用
    if apply_loras:
        print("  [警告] GGUF模型与LoRA不兼容(ForgeParams4bit错误)，已自动禁用LoRA")
        apply_loras = False

    base_end = max(1, int(base_steps * 0.70))
    refine_start = max(1, int(refine_steps * 0.45))

    wf = {
        "1": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": gguf_name},
        },
        "2": {
            "class_type": "DualCLIPLoader",
            "inputs": {"clip_name1": "t5xxl_fp8_e4m3fn.safetensors", "clip_name2": "clip_l.safetensors", "type": "flux"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
    }

    model_ref = ["1", 0]

    wf["6"] = {
        "class_type": "ModelSamplingAuraFlow",
        "inputs": {"model": model_ref, "shift": 3.0},
    }
    wf["7"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": width, "height": height, "batch_size": 1},
    }
    wf["8"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": prompt},
    }
    wf["9"] = {
        "class_type": "ConditioningZeroOut",
        "inputs": {"conditioning": ["8", 0]},
    }

    if is_preview:
        # 快速预览：单pass KSampler，4步，直接出图
        wf["10"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["6", 0],
                "seed": seed,
                "steps": base_steps,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["8", 0],
                "negative": ["9", 0],
                "latent_image": ["7", 0],
                "denoise": 1.0,
            },
        }
        wf["11"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["10", 0], "vae": ["3", 0]},
        }
        wf["12"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix + "_preview", "images": ["11", 0]}
        }
    else:
        wf["10"] = {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["6", 0],
                "add_noise": "enable",
                "noise_seed": seed,
                "steps": base_steps,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "beta",
                "positive": ["8", 0],
                "negative": ["9", 0],
                "latent_image": ["7", 0],
                "start_at_step": 0,
                "end_at_step": base_end,
                "return_with_leftover_noise": "enable",
            },
        }
        wf["11"] = {
            "class_type": "LatentUpscaleBy",
            "inputs": {"samples": ["10", 0], "upscale_method": "bislerp", "scale_by": 1.5},
        }
        wf["12"] = {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["6", 0],
                "add_noise": "enable",
                "noise_seed": seed + 1,
                "steps": refine_steps,
                "cfg": 1.0,
                "sampler_name": "dpmpp_2m_sde",
                "scheduler": "sgm_uniform",
                "positive": ["8", 0],
                "negative": ["9", 0],
                "latent_image": ["11", 0],
                "start_at_step": refine_start,
                "end_at_step": 999,
                "return_with_leftover_noise": "disable",
            },
        }
        wf["13"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["12", 0], "vae": ["3", 0]},
        }

        if skip_usu:
            wf["14"] = {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": prefix + "_base", "images": ["13", 0]}
            }
        else:
            wf["14"] = {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": "4xNomos8k_atd_jpg.safetensors"},
            }
            wf["15"] = {
                "class_type": "UltimateSDUpscale",
                "inputs": {
                    "image": ["13", 0],
                    "model": ["6", 0],
                    "positive": ["8", 0],
                    "negative": ["9", 0],
                    "vae": ["3", 0],
                    "upscale_by": usu_upscale,
                    "seed": seed + 2,
                    "steps": usu_steps,
                    "cfg": 1.0,
                    "sampler_name": "dpmpp_2m_sde",
                    "scheduler": "sgm_uniform",
                    "denoise": usu_denoise,
                    "upscale_model": ["14", 0],
                    "mode_type": "Linear",
                    "tile_width": usu_tile,
                    "tile_height": usu_tile,
                    "mask_blur": 64,
                    "tile_padding": 96,
                    "seam_fix_mode": "None",
                    "seam_fix_denoise": 1.0,
                    "seam_fix_width": 64,
                    "seam_fix_mask_blur": 8,
                    "seam_fix_padding": 16,
                    "force_uniform_tiles": True,
                    "tiled_decode": False,
                    "batch_size": 1,
                },
            }
        wf["16"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["15", 0] if not skip_usu else ["13", 0]}
        }
    return wf


def load_prompts():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM prompts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_prompt_text(p):
    prompt_text = p["prompt"] or ""
    neg_text = DEFAULT_NEG
    needs_glass = any(kw in prompt_text for kw in GLASS_KEYWORDS)
    needs_cold = any(kw in prompt_text for kw in COLD_WHITE_KEYWORDS)
    if needs_glass:
        # 先替换正面提示词中容易触发地面涂鸦的危险词
        for old, new in GROUND_GRAFFITI_REPLACEMENTS.items():
            prompt_text = prompt_text.replace(old, new)
        prompt_text += GLASS_REFLECTION_SUFFIX
    if needs_cold:
        prompt_text += COLD_WHITE_SUFFIX
    neg_text += MATERIAL_NEG_SUFFIX
    for keyword, enhancement in MATERIAL_ENHANCEMENTS.items():
        if keyword in prompt_text:
            prompt_text += enhancement
            break
    return prompt_text, neg_text


def submit_and_wait(pid, prompt_text, neg_text, seed, prefix, width, height, skip_usu=False, use_sdxl=False, use_nf4=False):
    try:
        delete_old_files(prefix)
        if skip_usu and not use_sdxl and not use_nf4:
            delete_old_files(prefix + "_base")
        if use_sdxl:
            delete_old_files(prefix + "_sdxl")
        if use_nf4:
            delete_old_files(prefix + "_nf4")
    except RuntimeError as e:
        return {"id": pid, "status": "FAILED", "error": str(e)}

    existing = get_existing_files()
    if use_sdxl:
        wf = make_sdxl_wf(prompt_text, neg_text, seed, prefix, width, height)
    elif use_nf4:
        wf = make_nf4_wf(prompt_text, neg_text, seed, prefix, width, height)
    else:
        wf = make_v7_full_wf(prompt_text, neg_text, seed, prefix, width, height, skip_usu=skip_usu)

    try:
        prompt_id = submit_prompt(wf)
        print(f"  已提交 ID:{pid} prompt_id: {prompt_id}")
    except Exception as e:
        return {"id": pid, "status": "FAILED", "error": str(e)}

    result_file = wait_for_new_file(prefix, existing, timeout=600)
    if result_file:
        fsize = os.path.getsize(result_file) / 1024 / 1024
        fname = os.path.basename(result_file)
        print(f"  完成: {fname} ({fsize:.1f}MB)")
        return {"id": pid, "status": "OK", "file": fname, "size_mb": round(fsize, 1)}
    else:
        return {"id": pid, "status": "TIMEOUT"}


def generate_for_ids(ids, count=1, ratio="portrait_tall", skip_usu=False, use_sdxl=False, use_nf4=False, use_q8=False, use_q8_nolora=False, preview=False):
    w, h = ASPECT_RATIOS.get(ratio, ASPECT_RATIOS["portrait_tall"])
    all_prompts = load_prompts()
    selected = [p for p in all_prompts if p["id"] in ids]
    if not selected:
        return {"error": f"未找到ID={ids}的提示词"}

    jobs = []
    for p in selected:
        pid = p["id"]
        prompt_text, neg_text = build_prompt_text(p)
        base_seed = p["seed"] if p.get("seed") else random.randint(0, 2**63)
        for n in range(count):
            seed = base_seed + n * 1000
            suffix = f"_v{n+1}" if count > 1 else ""
            prefix = f"Gen_{pid:02d}{suffix}"
            jobs.append((pid, prompt_text, neg_text, seed, prefix, w, h))

    prompt_ids = []
    for i, (pid, prompt_text, neg_text, seed, prefix, ww, hh) in enumerate(jobs):
        try:
            delete_old_files(prefix)
            if skip_usu and not use_sdxl and not use_nf4:
                delete_old_files(prefix + "_base")
            if use_sdxl:
                delete_old_files(prefix + "_sdxl")
            if use_nf4:
                delete_old_files(prefix + "_nf4")
        except RuntimeError as e:
            print(f"[{i+1}/{len(jobs)}] ID:{pid} 删除旧文件失败: {e}")
            prompt_ids.append(None)
            continue
        if use_sdxl:
            wf = make_sdxl_wf(prompt_text, neg_text, seed, prefix, ww, hh)
        elif use_q8_nolora:
            wf = make_gguf_wf(prompt_text, neg_text, seed, prefix, ww, hh, apply_loras=False, skip_usu=skip_usu, preview=preview)
        elif use_q8:
            wf = make_gguf_wf(prompt_text, neg_text, seed, prefix, ww, hh, apply_loras=True, skip_usu=skip_usu, preview=preview)
        elif use_nf4:
            wf = make_gguf_wf(prompt_text, neg_text, seed, prefix, ww, hh, gguf_name="flux1-dev-Q4_K_S.gguf", apply_loras=False, skip_usu=True, preview=preview)
        else:
            wf = make_v7_full_wf(prompt_text, neg_text, seed, prefix, ww, hh, skip_usu=skip_usu)
        try:
            prompt_id = submit_prompt(wf)
            prompt_ids.append(prompt_id)
            print(f"[{i+1}/{len(jobs)}] ID:{pid} 已提交 prompt_id: {prompt_id}")
        except Exception as e:
            prompt_ids.append(None)
            print(f"[{i+1}/{len(jobs)}] ID:{pid} 提交失败: {e}")

    print(f"\n全部已提交，等待生成完成...")
    results = []
    for i, (pid, prompt_text, neg_text, seed, prefix, ww, hh) in enumerate(jobs):
        existing = set()
        try:
            result_file = wait_for_new_file(prefix, existing, timeout=600, prompt_id=prompt_ids[i] if i < len(prompt_ids) else None)
        except RuntimeError as e:
            print(f"  [{i+1}/{len(jobs)}] ID:{pid} 执行错误: {e}")
            results.append({"id": pid, "status": "ERROR", "error": str(e)})
            continue
        if result_file:
            fsize = os.path.getsize(result_file) / 1024 / 1024
            fname = os.path.basename(result_file)
            print(f"  [{i+1}/{len(jobs)}] ID:{pid} 完成: {fname} ({fsize:.1f}MB)")
            results.append({"id": pid, "status": "OK", "file": fname, "size_mb": round(fsize, 1)})
        else:
            print(f"  [{i+1}/{len(jobs)}] ID:{pid} 超时!")
            results.append({"id": pid, "status": "TIMEOUT"})

    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"\n完成: {ok}/{len(results)}")
    return {"results": results, "total": len(results), "ok": ok}


class TaskStore:
    def __init__(self):
        self.tasks = {}
        self.lock = threading.Lock()

    def create(self, task_id, ids, count, ratio):
        with self.lock:
            self.tasks[task_id] = {
                "id": task_id, "ids": ids, "count": count, "ratio": ratio,
                "status": "running", "results": [], "ok": 0, "total": 0,
            }

    def update(self, task_id, result):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id]["results"].append(result)
                if result["status"] == "OK":
                    self.tasks[task_id]["ok"] += 1
                self.tasks[task_id]["total"] += 1

    def finish(self, task_id, final):
        with self.lock:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = "done"
                self.tasks[task_id]["ok"] = final.get("ok", 0)
                self.tasks[task_id]["total"] = final.get("total", 0)

    def get(self, task_id):
        with self.lock:
            return self.tasks.get(task_id)

    def list_all(self):
        with self.lock:
            return list(self.tasks.values())


task_store = TaskStore()


def run_generate_task(task_id, ids, count, ratio):
    task_store.create(task_id, ids, count, ratio)
    try:
        w, h = ASPECT_RATIOS.get(ratio, ASPECT_RATIOS["portrait_tall"])
        all_prompts = load_prompts()
        selected = [p for p in all_prompts if p["id"] in ids]
        if not selected:
            task_store.finish(task_id, {"ok": 0, "total": 0})
            return

        jobs = []
        for p in selected:
            pid = p["id"]
            prompt_text, neg_text = build_prompt_text(p)
            base_seed = p["seed"] if p.get("seed") else random.randint(0, 2**63)
            for n in range(count):
                seed = base_seed + n * 1000
                suffix = f"_v{n+1}" if count > 1 else ""
                prefix = f"Gen_{pid:02d}{suffix}"
                jobs.append((pid, prompt_text, neg_text, seed, prefix, w, h))

        for i, (pid, prompt_text, neg_text, seed, prefix, ww, hh) in enumerate(jobs):
            try:
                delete_old_files(prefix)
            except RuntimeError:
                continue
            existing = get_existing_files()
            wf = make_v7_full_wf(prompt_text, neg_text, seed, prefix, ww, hh)
            try:
                prompt_id = submit_prompt(wf)
                print(f"[Task:{task_id[:6]}] [{i+1}/{len(jobs)}] ID:{pid} submitted")
            except Exception:
                continue

        for i, (pid, prompt_text, neg_text, seed, prefix, ww, hh) in enumerate(jobs):
            result_file = wait_for_new_file(prefix, set(), timeout=600)
            if result_file:
                fsize = os.path.getsize(result_file) / 1024 / 1024
                result = {"id": pid, "status": "OK", "file": os.path.basename(result_file), "size_mb": round(fsize, 1)}
            else:
                result = {"id": pid, "status": "TIMEOUT"}
            result["variant"] = (i % count) + 1
            task_store.update(task_id, result)

        task_store.finish(task_id, {"ok": task_store.get(task_id)["ok"], "total": task_store.get(task_id)["total"]})
    except Exception as e:
        print(f"Task error: {e}")
        t = task_store.get(task_id)
        if t:
            t["status"] = "error"
            t["error"] = str(e)


def run_custom_task(task_id, prompt_text, neg_text, count, ratio):
    task_store.create(task_id, [], count, ratio)
    try:
        w, h = ASPECT_RATIOS.get(ratio, ASPECT_RATIOS["portrait_tall"])
        base_seed = random.randint(0, 2**63)

        jobs = []
        for n in range(count):
            seed = base_seed + n * 1000
            suffix = f"_v{n+1}" if count > 1 else ""
            prefix = f"Custom_{task_id[:6]}{suffix}"
            jobs.append((seed, prefix))

        for seed, prefix in jobs:
            try:
                delete_old_files(prefix)
            except RuntimeError:
                continue
            existing = get_existing_files()
            wf = make_v7_full_wf(prompt_text, neg_text, seed, prefix, w, h)
            try:
                submit_prompt(wf)
            except Exception:
                continue

        for i, (seed, prefix) in enumerate(jobs):
            result_file = wait_for_new_file(prefix, set(), timeout=600)
            if result_file:
                fsize = os.path.getsize(result_file) / 1024 / 1024
                result = {"id": 0, "status": "OK", "file": os.path.basename(result_file), "size_mb": round(fsize, 1)}
            else:
                result = {"id": 0, "status": "TIMEOUT"}
            result["variant"] = i + 1
            task_store.update(task_id, result)

        task_store.finish(task_id, {"ok": task_store.get(task_id)["ok"], "total": task_store.get(task_id)["total"]})
    except Exception as e:
        print(f"Custom task error: {e}")
        t = task_store.get(task_id)
        if t:
            t["status"] = "error"
            t["error"] = str(e)


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ComfyUI 图片生成</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: "Microsoft YaHei", sans-serif; background: #1a1a2e; color: #e0e0e0; min-height: 100vh; }
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }
h1 { text-align: center; font-size: 24px; font-weight: 600; margin-bottom: 24px; color: #fff; }
.panel { background: #16213e; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.panel-title { font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #e94560; }
.tab-bar { display: flex; gap: 0; margin-bottom: 16px; }
.tab-btn { flex: 1; padding: 10px; text-align: center; background: #0f3460; color: #aaa; border: none; cursor: pointer; font-size: 14px; font-weight: 600; transition: all 0.2s; }
.tab-btn:first-child { border-radius: 6px 0 0 6px; }
.tab-btn:last-child { border-radius: 0 6px 6px 0; }
.tab-btn.active { background: #e94560; color: #fff; }
.tab-content { display: none; }
.tab-content.active { display: block; }
.prompt-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.prompt-card { background: #0f3460; border: 2px solid transparent; border-radius: 6px; padding: 12px; cursor: pointer; transition: all 0.2s; }
.prompt-card:hover { border-color: #e94560; }
.prompt-card.selected { border-color: #e94560; background: #1a1a4e; }
.prompt-card .id-tag { display: inline-block; background: #e94560; color: #fff; border-radius: 3px; padding: 1px 6px; font-size: 12px; margin-right: 6px; }
.prompt-card .tags { font-size: 13px; color: #aaa; margin-top: 4px; }
.prompt-card .note { font-size: 12px; color: #888; margin-top: 2px; }
.custom-input { width: 100%; }
.custom-input textarea { width: 100%; min-height: 120px; background: #0f3460; color: #e0e0e0; border: 1px solid #333; border-radius: 6px; padding: 12px; font-size: 14px; resize: vertical; font-family: inherit; }
.custom-input textarea:focus { outline: none; border-color: #e94560; }
.custom-input textarea::placeholder { color: #666; }
.custom-input label { display: block; font-size: 13px; color: #aaa; margin-bottom: 4px; margin-top: 10px; }
.options-row { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.option-group { display: flex; align-items: center; gap: 8px; }
.option-group label { font-size: 14px; white-space: nowrap; }
.btn-group { display: flex; gap: 4px; }
.btn-group button { padding: 6px 14px; border: 1px solid #555; background: #1a1a2e; color: #ccc; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-group button.active { background: #e94560; border-color: #e94560; color: #fff; }
.btn-primary { padding: 10px 32px; background: #e94560; color: #fff; border: none; border-radius: 6px; font-size: 15px; cursor: pointer; font-weight: 600; }
.btn-primary:hover { background: #c73652; }
.btn-primary:disabled { background: #555; cursor: not-allowed; }
.task-list { margin-top: 16px; }
.task-item { background: #0f3460; border-radius: 6px; padding: 12px; margin-bottom: 8px; }
.task-item .task-header { display: flex; justify-content: space-between; align-items: center; }
.task-item .task-id { font-size: 13px; color: #aaa; }
.task-item .task-status { font-size: 13px; padding: 2px 8px; border-radius: 3px; }
.task-item .task-status.running { background: #f39c12; color: #000; }
.task-item .task-status.done { background: #27ae60; color: #fff; }
.task-item .task-status.error { background: #e74c3c; color: #fff; }
.task-results { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.task-results img { max-height: 200px; border-radius: 4px; cursor: pointer; }
.task-results img:hover { opacity: 0.8; }
.select-all-row { margin-bottom: 10px; }
.select-all-row label { font-size: 13px; cursor: pointer; color: #aaa; }
.empty-msg { color: #666; font-size: 14px; text-align: center; padding: 20px; }
</style>
</head>
<body>
<div class="container">
<h1>ComfyUI 图片生成</h1>

<div class="panel">
<div class="panel-title">提示词来源</div>
<div class="tab-bar">
<button class="tab-btn active" data-tab="db">从数据库选择</button>
<button class="tab-btn" data-tab="custom">自定义填写</button>
</div>
<div class="tab-content active" id="tab-db">
<div class="select-all-row"><label><input type="checkbox" id="selectAll"> 全选/取消</label></div>
<div class="prompt-grid" id="promptGrid"></div>
</div>
<div class="tab-content" id="tab-custom">
<div class="custom-input">
<label>正向提示词</label>
<textarea id="customPrompt" placeholder="输入正向提示词，如：1girl, standing, full body, summer dress..."></textarea>
<label>反向提示词（可选，留空使用默认）</label>
<textarea id="customNeg" placeholder="留空使用内置默认反向提示词"></textarea>
</div>
</div>
</div>

<div class="panel">
<div class="panel-title">生成选项</div>
<div class="options-row">
<div class="option-group">
<label>出图数量:</label>
<div class="btn-group" id="countBtns">
<button class="active" data-val="1">1张</button>
<button data-val="3">3张</button>
<button data-val="5">5张</button>
</div>
</div>
<div class="option-group">
<label>画面比例:</label>
<div class="btn-group" id="ratioBtns">
<button class="active" data-val="portrait_tall">832x1216</button>
<button data-val="portrait_2_3">768x1152</button>
<button data-val="portrait_9_16">768x1344</button>
</div>
</div>
<button class="btn-primary" id="submitBtn" disabled>开始生成</button>
</div>
</div>

<div class="panel">
<div class="panel-title">生成任务</div>
<div class="task-list" id="taskList"><div class="empty-msg">暂无任务</div></div>
</div>
</div>

<script>
let prompts = [];
let selectedIds = new Set();
let count = 1;
let ratio = 'portrait_tall';
let currentTab = 'db';

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    currentTab = btn.dataset.tab;
    document.getElementById('tab-' + currentTab).classList.add('active');
    updateSubmitState();
  };
});

async function loadPrompts() {
  const r = await fetch('/api/prompts');
  prompts = await r.json();
  renderPrompts();
}

function renderPrompts() {
  const grid = document.getElementById('promptGrid');
  grid.innerHTML = prompts.map(p => `
    <div class="prompt-card ${selectedIds.has(p.id)?'selected':''}" data-id="${p.id}">
      <span class="id-tag">ID:${p.id}</span>
      <span>${(p.tags||'').split(',').slice(0,4).join(', ')}</span>
      <div class="tags">${(p.prompt||'').substring(0,60)}...</div>
      <div class="note">${p.note||''}</div>
    </div>
  `).join('');
  document.querySelectorAll('.prompt-card').forEach(el => {
    el.onclick = () => {
      const id = parseInt(el.dataset.id);
      if (selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
      el.classList.toggle('selected');
      updateSubmitState();
    };
  });
}

function updateSubmitState() {
  const btn = document.getElementById('submitBtn');
  if (currentTab === 'db') {
    btn.disabled = selectedIds.size === 0;
  } else {
    btn.disabled = !document.getElementById('customPrompt').value.trim();
  }
}

document.getElementById('customPrompt').addEventListener('input', updateSubmitState);

document.getElementById('selectAll').onchange = function() {
  if (this.checked) { prompts.forEach(p => selectedIds.add(p.id)); }
  else { selectedIds.clear(); }
  renderPrompts();
  updateSubmitState();
};

document.querySelectorAll('#countBtns button').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('#countBtns button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    count = parseInt(btn.dataset.val);
  };
});

document.querySelectorAll('#ratioBtns button').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('#ratioBtns button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    ratio = btn.dataset.val;
  };
});

document.getElementById('submitBtn').onclick = async () => {
  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.textContent = '提交中...';

  let r, data;
  if (currentTab === 'db') {
    const ids = Array.from(selectedIds);
    if (!ids.length) { btn.disabled = false; btn.textContent = '开始生成'; return; }
    r = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ids, count, ratio})
    });
  } else {
    const prompt = document.getElementById('customPrompt').value.trim();
    if (!prompt) { btn.disabled = false; btn.textContent = '开始生成'; return; }
    const neg = document.getElementById('customNeg').value.trim();
    r = await fetch('/api/generate/custom', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt, negative: neg, count, ratio})
    });
  }
  data = await r.json();
  btn.disabled = false;
  btn.textContent = '开始生成';
  if (data.task_id) pollTask(data.task_id);
};

async function pollTask(taskId) {
  const list = document.getElementById('taskList');
  const emptyMsg = list.querySelector('.empty-msg');
  if (emptyMsg) emptyMsg.remove();

  let el = document.createElement('div');
  el.className = 'task-item';
  el.id = 'task-' + taskId;
  el.innerHTML = `<div class="task-header"><span class="task-id">任务: ${taskId.substring(0,8)}</span><span class="task-status running">生成中...</span></div><div class="task-results"></div>`;
  list.prepend(el);

  const poll = async () => {
    const r = await fetch('/api/task/' + taskId);
    const t = await r.json();
    const statusEl = el.querySelector('.task-status');
    const resultsEl = el.querySelector('.task-results');

    if (t.status === 'done') {
      statusEl.className = 'task-status done';
      statusEl.textContent = `完成 ${t.ok}/${t.total}`;
    } else if (t.status === 'error') {
      statusEl.className = 'task-status error';
      statusEl.textContent = '失败';
    } else {
      statusEl.textContent = `生成中... ${t.results.length}张`;
      setTimeout(poll, 3000);
    }

    resultsEl.innerHTML = t.results.filter(r => r.status === 'OK').map(r =>
      `<img src="/output/${r.file}" title="${r.file}" onclick="window.open('/output/${r.file}','_blank')">`
    ).join('');
  };
  poll();
}

loadPrompts();
</script>
</body>
</html>"""


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _image(self, filepath):
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(os.path.getsize(filepath)))
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._html(HTML_PAGE)
        elif path == "/api/prompts":
            self._json(load_prompts())
        elif path.startswith("/api/task/"):
            task_id = path.split("/api/task/")[1]
            t = task_store.get(task_id)
            if t:
                self._json(t)
            else:
                self._json({"error": "not found"}, 404)
        elif path.startswith("/api/tasks"):
            self._json(task_store.list_all())
        elif path.startswith("/output/"):
            fname = path.split("/output/")[1]
            self._image(os.path.join(OUTPUT_DIR, fname))
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/generate":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            ids = body.get("ids", [])
            count = body.get("count", 1)
            ratio = body.get("ratio", "portrait_tall")
            if not ids:
                self._json({"error": "ids为空"}, 400)
                return
            task_id = f"{int(time.time()*1000)}_{random.randint(1000,9999)}"
            t = threading.Thread(target=run_generate_task, args=(task_id, ids, count, ratio), daemon=True)
            t.start()
            self._json({"task_id": task_id})
        elif parsed.path == "/api/generate/custom":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            prompt_text = body.get("prompt", "").strip()
            neg_text = body.get("negative", "").strip()
            count = body.get("count", 1)
            ratio = body.get("ratio", "portrait_tall")
            if not prompt_text:
                self._json({"error": "提示词为空"}, 400)
                return
            if not neg_text:
                neg_text = DEFAULT_NEG + MATERIAL_NEG_SUFFIX
            task_id = f"c{int(time.time()*1000)}_{random.randint(1000,9999)}"
            t = threading.Thread(target=run_custom_task, args=(task_id, prompt_text, neg_text, count, ratio), daemon=True)
            t.start()
            self._json({"task_id": task_id})
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def serve():
    server = HTTPServer((API_HOST, API_PORT), APIHandler)
    print(f"API服务已启动: http://{API_HOST}:{API_PORT}")
    print(f"前端页面: http://127.0.0.1:{API_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


def cli_main():
    parser = argparse.ArgumentParser(description="ComfyUI 图片生成工具")
    parser.add_argument("--serve", action="store_true", help="启动API服务（含前端页面）")
    parser.add_argument("--ids", type=int, nargs="+", help="指定提示词ID")
    parser.add_argument("--all", action="store_true", help="生成全部提示词")
    parser.add_argument("--count", type=int, default=1, help="每条提示词生成数量（默认1）")
    parser.add_argument("--ratio", default="portrait_tall", choices=list(ASPECT_RATIOS.keys()), help="画面比例")
    parser.add_argument("--skip-usu", action="store_true", help="跳过UltimateSDUpscale，只输出基底图（用于快速审核）")
    parser.add_argument("--sdxl", action="store_true", help="使用SDXL工作流（测试地面修复效果）")
    parser.add_argument("--nf4", action="store_true", help="使用Flux Dev GGUF Q4_K_S工作流")
    parser.add_argument("--q8", action="store_true", help="使用Flux Dev GGUF Q8_0工作流（含LoRA）")
    parser.add_argument("--q8-nolora", action="store_true", help="使用Flux Dev GGUF Q8_0工作流（无LoRA，纯原版）")
    parser.add_argument("--preview", action="store_true", help="快速预览模式：512x768、4步euler、无超分（需配合--q8/--q8-nolora使用）")
    args = parser.parse_args()

    if args.serve:
        serve()
        return

    if not args.ids and not args.all:
        parser.print_help()
        return

    if args.all:
        ids = [p["id"] for p in load_prompts()]
    else:
        ids = args.ids

    use_q8 = args.q8
    use_q8_nolora = args.q8_nolora
    use_preview = args.preview
    mode = ("GGUF-Q8-nolora" if use_q8_nolora else
            "GGUF-Q8" if use_q8 else
            "GGUF-Q4" if args.nf4 else
            "SDXL" if args.sdxl else
            ("FP8-base" if args.skip_usu else "FP8-full"))
    if use_preview:
        mode += "-PREVIEW"
    print(f"[img_gen v2.4] 模式: {mode}, IDs: {ids}, 数量: {args.count}, 比例: {args.ratio}")

    result = generate_for_ids(ids, args.count, args.ratio, skip_usu=args.skip_usu, use_sdxl=args.sdxl, use_nf4=args.nf4, use_q8=use_q8, use_q8_nolora=use_q8_nolora, preview=use_preview)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cli_main()