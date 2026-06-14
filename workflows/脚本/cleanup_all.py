"""Cleanup: delete temp scripts, generate 2 workflow JSONs, consolidate."""
import os, shutil, json, glob

ROOT = r"d:\Entertainment\ComfyUI-aki-v2"
WF_DIR = os.path.join(ROOT, "workflows")
WORKFLOW_OUT = os.path.join(ROOT, "ComfyUI", "user", "default", "workflows")

# ============================================================
# 1. DELETE temporary scripts from root directory
# ============================================================
temp_scripts = [
    "check_comfyui_db.py", "check_qwen_clip.py", "check_qwen_edit.py",
    "download_flux2_9b.py", "download_flux2_ms.py", "download_flux2.py",
    "download_qwen_image.py", "download_qwen_ms.py", "download_qwen3_8b.py",
    "extract_png_prompts.py", "extract_prompts.py",
    "generate_all_8.py", "generate_v7.py",
    "isolate_b.py", "isolate_experiment.py",
    "move_and_check.py", "quick_test.py",
    "run_b2.py", "run_cstore_compare.py", "run_db_prompts.py",
    "run_original_prompt.py", "run_qwen_compare.py", "run_qwen_proper.py",
    "runner.py",
    "search_civitai.py", "search_civitai2.py", "search_civitai3.py",
    "test_flux2_4b.py", "test_flux2_9b.py", "test_flux2_cstore.py",
    "test_flux2_final.py", "test_minimal.py", "test_qwen_image.py",
    "test_v7_qwen_chain.py", "verify_workflow.py",
    "ZIT-143925_00001_.png",
]

deleted_root = 0
for f in temp_scripts:
    path = os.path.join(ROOT, f)
    if os.path.exists(path):
        os.remove(path)
        deleted_root += 1
print(f"Root: deleted {deleted_root} temp files")

# Keep make_workflow.py and read_prompt_db.py (utilities)
# Move them to workflows/脚本/
for util in ["make_workflow.py", "read_prompt_db.py"]:
    src = os.path.join(ROOT, util)
    dst = os.path.join(WF_DIR, "脚本", util)
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"Moved: {util} -> workflows/脚本/")

# ============================================================
# 2. DELETE temporary scripts from workflows/ root
# ============================================================
wf_temp = glob.glob(os.path.join(WF_DIR, "_*.py"))
deleted_wf = 0
for f in wf_temp:
    os.remove(f)
    deleted_wf += 1
print(f"workflows/: deleted {deleted_wf} temp scripts")

# ============================================================
# 3. Clean workflows/脚本/ old batch scripts  
# ============================================================
scripts_dir = os.path.join(WF_DIR, "脚本")
old_scripts = glob.glob(os.path.join(scripts_dir, "_batch*.py"))
old_scripts += glob.glob(os.path.join(scripts_dir, "_debug*.py"))
old_scripts += glob.glob(os.path.join(scripts_dir, "_monitor*.py"))
old_scripts += glob.glob(os.path.join(scripts_dir, "test_submit*.py"))
deleted_scripts = 0
for f in old_scripts:
    os.remove(f)
    deleted_scripts += 1
print(f"workflows/脚本/: deleted {deleted_scripts} old batch scripts")

# ============================================================
# 4. Generate two clean workflow JSONs
# ============================================================
def make_workflow_json(filename, clip_name, clip_type, vae_name, unet_name, 
                       loras, model_sampling_type, sampler_advanced, latent_type,
                       upscale_model, face_detector, face_detailer, title):
    """Generic workflow builder."""
    S = str
    nodes = [
        {"id": 1, "type": "CLIPLoader", "pos": [50, 50], "size": [200, 60], "flags": {}, "order": 1, "mode": 0,
         "inputs": [], "outputs": [{"name": "CLIP", "type": "CLIP", "links": [1, 2, 3]}],
         "properties": {"Node name for S&R": "CLIPLoader"},
         "widgets_values": [clip_name, clip_type, "default"], "title": f"CLIP: {clip_name}"},
        
        {"id": 2, "type": "VAELoader", "pos": [50, 180], "size": [200, 60], "flags": {}, "order": 2, "mode": 0,
         "inputs": [], "outputs": [{"name": "VAE", "type": "VAE", "links": [4, 5, 6]}],
         "properties": {"Node name for S&R": "VAELoader"},
         "widgets_values": [vae_name], "title": f"VAE: {vae_name}"},
        
        {"id": 3, "type": "UNETLoader", "pos": [50, 310], "size": [260, 60], "flags": {}, "order": 3, "mode": 0,
         "inputs": [], "outputs": [{"name": "MODEL", "type": "MODEL", "links": [7]}],
         "properties": {"Node name for S&R": "UNETLoader"},
         "widgets_values": [unet_name, "default"], "title": f"UNET: {unet_name}"},
        
        {"id": 4, "type": "CLIPTextEncode", "pos": [350, 50], "size": [450, 220], "flags": {}, "order": 4, "mode": 0,
         "inputs": [{"name": "clip", "type": "CLIP", "link": 1}],
         "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [8, 9, 10, 11]}],
         "properties": {"Node name for S&R": "CLIPTextEncode"},
         "widgets_values": ["在此输入正面提示词 ↓\n\n"], "title": "正面提示词（双击修改）"},
        
        {"id": 5, "type": "CLIPTextEncode", "pos": [350, 300], "size": [450, 100], "flags": {}, "order": 5, "mode": 0,
         "inputs": [{"name": "clip", "type": "CLIP", "link": 2}],
         "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [12, 13, 14, 15]}],
         "properties": {"Node name for S&R": "CLIPTextEncode"},
         "widgets_values": ["low quality, blurry, distorted, bad hands, text, watermark, abstract ground texture"],
         "title": "负面提示词"},
        
        {"id": 6, "type": latent_type, "pos": [350, 450], "size": [180, 80], "flags": {}, "order": 6, "mode": 0,
         "inputs": [], "outputs": [{"name": "LATENT", "type": "LATENT", "links": [16]}],
         "properties": {"Node name for S&R": latent_type},
         "widgets_values": [640, 960, 1] if latent_type == "EmptyLatentImage" else [1024, 1024, 1],
         "title": "Latent"},
    ]
    
    # LoRAs and ModelSampling
    prev_node = 3
    link_id = 7
    for i, (lora_name, strength) in enumerate(loras):
        lid = 7 + i*2
        nid = 7 + i
        nodes.append({
            "id": nid, "type": "LoraLoaderModelOnly", "pos": [600 + i*250, 310], "size": [200, 60],
            "flags": {}, "order": nid, "mode": 0,
            "inputs": [{"name": "model", "type": "MODEL", "link": lid - 1 if i == 0 else lid}],
            "outputs": [{"name": "MODEL", "type": "MODEL", "links": [lid + 1]}],
            "properties": {"Node name for S&R": "LoraLoaderModelOnly"},
            "widgets_values": [lora_name, strength],
            "title": f"LoRA: {lora_name.split('.')[0]} {strength}",
        })
    
    ms_id = 7 + len(loras)
    ms_link = 7 + len(loras)*2 + 1
    nodes.append({
        "id": ms_id, "type": model_sampling_type, "pos": [600 + len(loras)*250, 310], "size": [200, 60],
        "flags": {}, "order": ms_id, "mode": 0,
        "inputs": [{"name": "model", "type": "MODEL", "link": ms_link}],
        "outputs": [{"name": "MODEL", "type": "MODEL", "links": [ms_link+1, ms_link+2, ms_link+3, ms_link+4]}],
        "properties": {"Node name for S&R": model_sampling_type},
        "widgets_values": [3],
        "title": model_sampling_type,
    })
    
    # KSampler Base (use KSamplerAdvanced for V7, KSampler for Qwen-Image)
    use_advanced = sampler_advanced == "KSamplerAdvanced"
    ks1_id = ms_id + 1
    nodes.append({
        "id": ks1_id, "type": sampler_advanced,
        "pos": [1300, 240], "size": [300, 260], "flags": {}, "order": ks1_id, "mode": 0,
        "inputs": [
            {"name": "model", "type": "MODEL", "link": ms_link+1},
            {"name": "positive", "type": "CONDITIONING", "link": 8},
            {"name": "negative", "type": "CONDITIONING", "link": 12},
            {"name": "latent_image", "type": "LATENT", "link": 16},
        ],
        "outputs": [{"name": "LATENT", "type": "LATENT", "links": [ms_link+5]}],
        "properties": {"Node name for S&R": "KSamplerAdvanced"},
        "widgets_values": (
            ["enable", 42, "randomize", 9, 1.0, "dpmpp_2m_sde_gpu", "beta", 0, 9, "enable"]
            if use_advanced else
            [42, 30, 4.0, "dpmpp_2m", "simple", 1.0]
        ),
        "title": "① KSampler 基础生成",
    })
    
    next_latent = ks1_id
    next_latent_link = ms_link+5
    
    # LatentUpscale for V7
    if loras:
        lu_id = ks1_id + 1
        nodes.append({
            "id": lu_id, "type": "LatentUpscaleBy", "pos": [1650, 310], "size": [200, 80],
            "flags": {}, "order": lu_id, "mode": 0,
            "inputs": [{"name": "samples", "type": "LATENT", "link": next_latent_link}],
            "outputs": [{"name": "LATENT", "type": "LATENT", "links": [ms_link+6]}],
            "properties": {"Node name for S&R": "LatentUpscaleBy"},
            "widgets_values": ["bislerp", 1.7],
            "title": "LatentUpscale 1.7x",
        })
        next_latent_link = ms_link+6
        next_latent = lu_id
        
        # KSampler Refine
        ks2_id = lu_id + 1
        nodes.append({
            "id": ks2_id, "type": "KSamplerAdvanced",
            "pos": [1950, 240], "size": [300, 260], "flags": {}, "order": ks2_id, "mode": 0,
            "inputs": [
                {"name": "model", "type": "MODEL", "link": ms_link+2},
                {"name": "positive", "type": "CONDITIONING", "link": 9},
                {"name": "negative", "type": "CONDITIONING", "link": 13},
                {"name": "latent_image", "type": "LATENT", "link": next_latent_link},
            ],
            "outputs": [{"name": "LATENT", "type": "LATENT", "links": [ms_link+7]}],
            "properties": {"Node name for S&R": "KSamplerAdvanced"},
            "widgets_values": ["enable", 43, "randomize", 9, 1.0, "dpmpp_2m_sde_gpu", "sgm_uniform", 4, 9, "disable"],
            "title": "② KSampler 精修",
        })
        next_latent_link = ms_link+7
        next_latent = ks2_id
    
    # VAE Decode
    vd_id = next_latent + 1
    nodes.append({
        "id": vd_id, "type": "VAEDecode", "pos": [2300 + (100 if loras else 0), 310], "size": [200, 80],
        "flags": {}, "order": vd_id, "mode": 0,
        "inputs": [
            {"name": "samples", "type": "LATENT", "link": next_latent_link},
            {"name": "vae", "type": "VAE", "link": 4},
        ],
        "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [ms_link+8]}],
        "properties": {"Node name for S&R": "VAEDecode"},
        "widgets_values": [], "title": "VAEDecode",
    })
    next_image = vd_id
    next_image_link = ms_link+8
    
    # UltimateSDUpscale + FaceDetailer (V7 only)
    if upscale_model:
        um_id = next_image + 1
        nodes.append({
            "id": um_id, "type": "UpscaleModelLoader", "pos": [2550, 230], "size": [280, 60],
            "flags": {}, "order": um_id, "mode": 0,
            "inputs": [], "outputs": [{"name": "UPSCALE_MODEL", "type": "UPSCALE_MODEL", "links": [ms_link+9]}],
            "properties": {"Node name for S&R": "UpscaleModelLoader"},
            "widgets_values": ["4xNomosWebPhoto_RealPLKSR.pth"],
            "title": "PLKSR 4x",
        })
        
        usu_id = um_id + 1
        nodes.append({
            "id": usu_id, "type": "UltimateSDUpscale", "pos": [2550, 330], "size": [380, 340],
            "flags": {}, "order": usu_id, "mode": 0,
            "inputs": [
                {"name": "image", "type": "IMAGE", "link": next_image_link},
                {"name": "model", "type": "MODEL", "link": ms_link+3},
                {"name": "positive", "type": "CONDITIONING", "link": 10},
                {"name": "negative", "type": "CONDITIONING", "link": 14},
                {"name": "vae", "type": "VAE", "link": 5},
                {"name": "upscale_model", "type": "UPSCALE_MODEL", "link": ms_link+9},
            ],
            "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [ms_link+10]}],
            "properties": {"Node name for S&R": "UltimateSDUpscale"},
            "widgets_values": [2.5, 242, "fixed", 3, 1.0, "dpmpp_2m_sde_gpu", "sgm_uniform", 0.23, "Linear",
                             1024, 1024, 8, 32, "None", 1.0, 64, 8, 16, True, False, 1],
            "title": "③ UltimateSDUpscale 2.5x",
        })
        next_image_link = ms_link+10
        
        if face_detector:
            fd_id = usu_id + 1
            nodes.append({
                "id": fd_id, "type": "MediaPipeFaceMeshDetectorProvider //Inspire",
                "pos": [3000, 230], "size": [350, 120], "flags": {}, "order": fd_id, "mode": 0,
                "inputs": [],
                "outputs": [{"name": "BBOX_DETECTOR", "type": "BBOX_DETECTOR", "links": [ms_link+11]}],
                "properties": {"Node name for S&R": "MediaPipeFaceMeshDetectorProvider"},
                "widgets_values": [1, True, False, False, False, False, False, False, False],
                "title": "MediaPipe 人脸检测",
            })
            
            fdl_id = fd_id + 1
            nodes.append({
                "id": fdl_id, "type": "FaceDetailer",
                "pos": [3000, 390], "size": [380, 370], "flags": {}, "order": fdl_id, "mode": 0,
                "inputs": [
                    {"name": "image", "type": "IMAGE", "link": next_image_link},
                    {"name": "model", "type": "MODEL", "link": ms_link+4},
                    {"name": "clip", "type": "CLIP", "link": 3},
                    {"name": "vae", "type": "VAE", "link": 6},
                    {"name": "positive", "type": "CONDITIONING", "link": 11},
                    {"name": "negative", "type": "CONDITIONING", "link": 15},
                    {"name": "bbox_detector", "type": "BBOX_DETECTOR", "link": ms_link+11},
                ],
                "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [ms_link+12]}],
                "properties": {"Node name for S&R": "FaceDetailer"},
                "widgets_values": [1440, True, 2048, 442, 6, 1.0, "dpmpp_2m_sde_gpu", "sgm_uniform",
                                  0.30, 5, True, True, 0.5, 10, 2.0,
                                  "none", 0, 0.93, 0, 0.7, "False", 10, "", 1],
                "title": "④ FaceDetailer (crop=2.0, denoise=0.30)",
            })
            next_image_link = ms_link+12
            last_id = fdl_id
        else:
            last_id = usu_id
    else:
        last_id = vd_id
    
    # SaveImage
    sv_id = last_id + 1
    nodes.append({
        "id": sv_id, "type": "SaveImage", "pos": [3450, 420], "size": [280, 100],
        "flags": {}, "order": sv_id, "mode": 0,
        "inputs": [{"name": "images", "type": "IMAGE", "link": next_image_link}],
        "outputs": [],
        "properties": {"Node name for S&R": "SaveImage"},
        "widgets_values": [filename.replace(".json", "")],
        "title": "⑤ 保存图片",
    })
    
    # Build links
    links = []
    lid = 1
    # Map link IDs to actual connections
    # Simplifying: since link IDs are complex, just build from our defined links
    for node in nodes:
        for out in node["outputs"]:
            for output_link in out.get("links", []):
                for n2 in nodes:
                    for s_i, inp in enumerate(n2["inputs"]):
                        if inp.get("link") == output_link:
                            links.append([output_link, node["id"], node["outputs"].index(out), n2["id"], s_i, out["type"]])
                            break
    
    return {
        "last_node_id": sv_id,
        "last_link_id": links[-1][0] if links else 0,
        "nodes": nodes,
        "links": links,
        "groups": [], "config": {}, "extra": {}, "version": 0.4,
    }

# ============================================================
# 5. Generate V7 Portrait Workflow
# ============================================================
v7 = make_workflow_json(
    filename="Moody_V7_Portrait.json",
    clip_name="qwen_3_4b.safetensors",
    clip_type="lumina2",
    vae_name="ae.safetensors",
    unet_name="moodyRealMix_zitV7GlobalFP8.safetensors",
    loras=[("momoka-zib-v2_clean.safetensors", 1.0), ("zit_sda_v1.safetensors", 0.49)],
    model_sampling_type="ModelSamplingAuraFlow",
    sampler_advanced="KSamplerAdvanced",
    latent_type="EmptyLatentImage",
    upscale_model=True,
    face_detector=True,
    face_detailer=True,
    title="Moody V7 写实人像管线",
)

out_v7 = os.path.join(WORKFLOW_OUT, "Moody_V7_Portrait.json")
os.makedirs(WORKFLOW_OUT, exist_ok=True)
with open(out_v7, 'w', encoding='utf-8') as f:
    json.dump(v7, f, ensure_ascii=False, indent=2)
print(f"Generated: Moody_V7_Portrait.json ({len(v7['nodes'])} nodes, {len(v7['links'])} links)")

# ============================================================
# 6. Generate Qwen-Image Text Workflow
# ============================================================
qwen = make_workflow_json(
    filename="QwenImage_Text.json",
    clip_name="qwen_2.5_vl_7b_fp8_scaled.safetensors",
    clip_type="qwen_image",
    vae_name="qwen_image_vae.safetensors",
    unet_name="qwen_image_2512_fp8_e4m3fn.safetensors",
    loras=[],
    model_sampling_type="KSampler",
    sampler_advanced="KSampler",
    latent_type="EmptySD3LatentImage",
    upscale_model=False,
    face_detector=False,
    face_detailer=False,
    title="Qwen-Image 文字渲染管线",
)

out_qwen = os.path.join(WORKFLOW_OUT, "QwenImage_Text.json")
with open(out_qwen, 'w', encoding='utf-8') as f:
    json.dump(qwen, f, ensure_ascii=False, indent=2)
print(f"Generated: QwenImage_Text.json ({len(qwen['nodes'])} nodes, {len(qwen['links'])} links)")

# ============================================================
# 7. Copy workflows to workflows/ folder for backup
# ============================================================
import shutil as sh
sh.copy2(out_v7, os.path.join(WF_DIR, "Moody_V7_Portrait.json"))
sh.copy2(out_qwen, os.path.join(WF_DIR, "QwenImage_Text.json"))
print("Copied workflows to workflows/ folder")

print("\nAll done!")
