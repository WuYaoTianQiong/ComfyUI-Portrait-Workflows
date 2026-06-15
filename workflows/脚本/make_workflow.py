"""
Generate drag-drop ComfyUI workflow JSON with proper link IDs.
"""
import json, os

OUTFILE = r"d:\Entertainment\ComfyUI-aki-v2\ComfyUI\user\default\workflows\Moody V7 纯净管线_修复版.json"

def node(id, type, pos, size, inputs, outputs, widgets, title=""):
    return {
        "id": id, "type": type, "pos": pos, "size": size,
        "flags": {}, "order": id, "mode": 0,
        "inputs": inputs, "outputs": outputs,
        "properties": {"Node name for S&R": type},
        "widgets_values": widgets, "title": title,
    }

def iport(name, typ):
    return {"name": name, "type": typ}

def oport(name, typ, links):
    return {"name": name, "type": typ, "links": links or []}

# Define connections as: (src_id, src_slot, dst_id, dst_slot, type)
# Then assign link IDs sequentially
connections = [
    # CLIP routing (CLIPLoader has 2 outputs in parallel to pos+neg, FaceDetailer clip)
    (1, 0, 4, 0, "CLIP"),   # CLIPLoader(1) → CLIPTextEncode POS(4)
    (1, 1, 5, 0, "CLIP"),   # CLIPLoader(1) → CLIPTextEncode NEG(5)
    (1, 2, 31, 2, "CLIP"),  # CLIPLoader(1) → FaceDetailer(31) clip

    # VAE routing
    (2, 0, 13, 1, "VAE"),   # VAELoader(2) → VAEDecode(13)
    (2, 1, 21, 4, "VAE"),   # VAELoader(2) → UltimateSDUpscale(21)
    (2, 2, 31, 3, "VAE"),   # VAELoader(2) → FaceDetailer(31)

    # UNET → LoRA chain
    (3, 0, 7, 0, "MODEL"),  # UNETLoader(3) → Lora momoka(7)

    # Prompt → Conditioning
    (4, 0, 10, 1, "CONDITIONING"),  # POS → KSampler base + refine + Ultimate
    (4, 1, 12, 1, "CONDITIONING"),
    (4, 2, 21, 2, "CONDITIONING"),
    (4, 3, 31, 10, "CONDITIONING"),  # POS → FaceDetailer positive

    (5, 0, 10, 2, "CONDITIONING"),  # NEG → KSampler base + refine + Ultimate
    (5, 1, 12, 2, "CONDITIONING"),
    (5, 2, 21, 3, "CONDITIONING"),
    (5, 3, 31, 11, "CONDITIONING"),  # NEG → FaceDetailer negative

    # EmptyLatent → KSampler base
    (6, 0, 10, 3, "LATENT"),

    # LoRA chain
    (7, 0, 8, 0, "MODEL"),   # momoka → zit_sda
    (8, 0, 9, 0, "MODEL"),   # zit_sda → ModelSampling

    # ModelSampling → KSamplers + Ultimate + FaceDetailer
    (9, 0, 10, 0, "MODEL"),  # → KSampler base
    (9, 1, 12, 0, "MODEL"),  # → KSampler refine
    (9, 2, 21, 1, "MODEL"),  # → UltimateSDUpscale
    (9, 3, 31, 1, "MODEL"),  # → FaceDetailer

    # KSampler base → LatentUpscale
    (10, 0, 11, 0, "LATENT"),

    # LatentUpscale → KSampler refine
    (11, 0, 12, 3, "LATENT"),

    # KSampler refine → VAEDecode
    (12, 0, 13, 0, "LATENT"),

    # VAEDecode → UltimateSDUpscale
    (13, 0, 21, 0, "IMAGE"),

    # UpscaleModelLoader → UltimateSDUpscale
    (20, 0, 21, 5, "UPSCALE_MODEL"),

    # UltimateSDUpscale → FaceDetailer
    (21, 0, 31, 0, "IMAGE"),

    # FaceDetector → FaceDetailer
    (30, 0, 31, 4, "BBOX_DETECTOR"),

    # FaceDetailer → SaveImage
    (31, 0, 40, 0, "IMAGE"),
]

# Build output link IDs
link_id = 1
src_outputs = {}  # (src_id, src_slot) → link_id
for src_id, src_slot, dst_id, dst_slot, ltype in connections:
    key = (src_id, src_slot)
    if key not in src_outputs:
        src_outputs[key] = []
    src_outputs[key].append(link_id)
    link_id += 1

# Build nodes with correct link IDs
nodes = [
    node(1, "CLIPLoader", [50, 50], [200, 60],
         [], [
             oport("CLIP", "CLIP", src_outputs.get((1,0),[])),
             oport("CLIP", "CLIP", src_outputs.get((1,1),[])),
             oport("CLIP", "CLIP", src_outputs.get((1,2),[])),
         ],
         ["qwen_3_4b.safetensors", "lumina2", "default"], "CLIP: qwen_3_4b"),

    node(2, "VAELoader", [50, 180], [200, 60],
         [], [
             oport("VAE", "VAE", src_outputs.get((2,0),[])),
             oport("VAE", "VAE", src_outputs.get((2,1),[])),
             oport("VAE", "VAE", src_outputs.get((2,2),[])),
         ],
         ["ae.safetensors"], "VAE: ae"),

    node(3, "UNETLoader", [50, 310], [260, 60],
         [], [oport("MODEL", "MODEL", src_outputs.get((3,0),[]))],
         ["moodyRealMix_zitV7GlobalFP8.safetensors", "default"], "UNET: V7 FP8"),

    node(4, "CLIPTextEncode", [350, 50], [450, 250],
         [{**iport("clip", "CLIP"), "link": src_outputs[(1,0)][0]}],
         [
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((4,0),[])),
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((4,1),[])),
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((4,2),[])),
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((4,3),[])),
         ],
         ["修改提示词 ↓\n\nMoody Photography, 20岁中国清纯可爱女孩，精致韩式妆容，韩风冷色调网红美白滤镜，极致冷白皮，通体雪白。\n\n场景描述：在此输入...\n\n细节：透明PVC高跟凉鞋（透明鞋底结构清晰，鞋跟为透明亚克力材质，防滑纹理可见），脚趾自然可见。地面细节清晰。\n\n(重要：必须包含鞋类和地面描述，防止脚部涂抹)", ],
         "正面提示词（双击修改）"),

    node(5, "CLIPTextEncode", [350, 330], [450, 100],
         [{**iport("clip", "CLIP"), "link": src_outputs[(1,1)][0]}],
         [
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((5,0),[])),
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((5,1),[])),
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((5,2),[])),
             oport("CONDITIONING", "CONDITIONING", src_outputs.get((5,3),[])),
         ],
         ["low quality, blurry, distorted, bad hands, text, watermark, abstract ground texture"],
         "负面提示词"),

    node(6, "EmptyLatentImage", [350, 470], [180, 80],
         [], [oport("LATENT", "LATENT", src_outputs.get((6,0),[]))],
         [640, 960, 1], "Latent 640x960"),

    node(7, "LoraLoaderModelOnly", [600, 310], [200, 60],
         [{**iport("model", "MODEL"), "link": src_outputs[(3,0)][0]}],
         [oport("MODEL", "MODEL", src_outputs.get((7,0),[]))],
         ["momoka-zib-v2_clean.safetensors", 1.0], "LoRA: momoka 1.0"),

    node(8, "LoraLoaderModelOnly", [850, 310], [200, 60],
         [{**iport("model", "MODEL"), "link": src_outputs[(7,0)][0]}],
         [oport("MODEL", "MODEL", src_outputs.get((8,0),[]))],
         ["zit_sda_v1.safetensors", 0.49], "LoRA: zit_sda 0.49"),

    node(9, "ModelSamplingAuraFlow", [1100, 310], [200, 60],
         [{**iport("model", "MODEL"), "link": src_outputs[(8,0)][0]}],
         [
             oport("MODEL", "MODEL", src_outputs.get((9,0),[])),
             oport("MODEL", "MODEL", src_outputs.get((9,1),[])),
             oport("MODEL", "MODEL", src_outputs.get((9,2),[])),
             oport("MODEL", "MODEL", src_outputs.get((9,3),[])),
         ],
         [3], "ModelSampling shift=3"),

    node(10, "KSamplerAdvanced", [1350, 240], [300, 260],
         [
             {**iport("model", "MODEL"), "link": src_outputs[(9,0)][0]},
             {**iport("positive", "CONDITIONING"), "link": src_outputs[(4,0)][0]},
             {**iport("negative", "CONDITIONING"), "link": src_outputs[(5,0)][0]},
             {**iport("latent_image", "LATENT"), "link": src_outputs[(6,0)][0]},
         ],
         [oport("LATENT", "LATENT", src_outputs.get((10,0),[]))],
         ["enable", 42, "randomize", 9, 1.0, "dpmpp_2m_sde_gpu", "beta", 0, 9, "enable"],
         "① KSampler 基础 9步 beta"),

    node(11, "LatentUpscaleBy", [1700, 310], [200, 80],
         [{**iport("samples", "LATENT"), "link": src_outputs[(10,0)][0]}],
         [oport("LATENT", "LATENT", src_outputs.get((11,0),[]))],
         ["bislerp", 1.7], "LatentUpscale 1.7x"),

    node(12, "KSamplerAdvanced", [1950, 240], [300, 260],
         [
             {**iport("model", "MODEL"), "link": src_outputs[(9,1)][0]},
             {**iport("positive", "CONDITIONING"), "link": src_outputs[(4,1)][0]},
             {**iport("negative", "CONDITIONING"), "link": src_outputs[(5,1)][0]},
             {**iport("latent_image", "LATENT"), "link": src_outputs[(11,0)][0]},
         ],
         [oport("LATENT", "LATENT", src_outputs.get((12,0),[]))],
         ["enable", 43, "randomize", 9, 1.0, "dpmpp_2m_sde_gpu", "sgm_uniform", 4, 9, "disable"],
         "② KSampler 精修 sgm_uniform"),

    node(13, "VAEDecode", [2300, 310], [200, 80],
         [
             {**iport("samples", "LATENT"), "link": src_outputs[(12,0)][0]},
             {**iport("vae", "VAE"), "link": src_outputs[(2,0)][0]},
         ],
         [oport("IMAGE", "IMAGE", src_outputs.get((13,0),[]))],
         [], "VAEDecode 1088x1632"),

    node(20, "UpscaleModelLoader", [2550, 230], [280, 60],
         [], [oport("UPSCALE_MODEL", "UPSCALE_MODEL", src_outputs.get((20,0),[]))],
         ["4xNomosWebPhoto_RealPLKSR.pth"], "PLKSR 4x模型"),

    node(21, "UltimateSDUpscale", [2550, 330], [380, 340],
         [
             {**iport("image", "IMAGE"), "link": src_outputs[(13,0)][0]},
             {**iport("model", "MODEL"), "link": src_outputs[(9,2)][0]},
             {**iport("positive", "CONDITIONING"), "link": src_outputs[(4,2)][0]},
             {**iport("negative", "CONDITIONING"), "link": src_outputs[(5,2)][0]},
             {**iport("vae", "VAE"), "link": src_outputs[(2,1)][0]},
             {**iport("upscale_model", "UPSCALE_MODEL"), "link": src_outputs[(20,0)][0]},
         ],
         [oport("IMAGE", "IMAGE", src_outputs.get((21,0),[]))],
         [2.5, 42+200, "fixed", 3, 1.0, "dpmpp_2m_sde_gpu", "sgm_uniform",
          0.23, "Linear", 1024, 1024, 8, 32, "None",
          1.0, 64, 8, 16, True, False, 1],
         "③ UltimateSDUpscale 2.5x"),

    node(30, "MediaPipeFaceMeshDetectorProvider //Inspire", [3000, 230], [350, 120],
         [], [oport("BBOX_DETECTOR", "BBOX_DETECTOR", src_outputs.get((30,0),[]))],
         [1, True, False, False, False, False, False, False, False],
         "MediaPipe 人脸检测"),

    node(31, "FaceDetailer", [3000, 390], [380, 400],
         [
             {**iport("image", "IMAGE"), "link": src_outputs[(21,0)][0]},
             {**iport("model", "MODEL"), "link": src_outputs[(9,3)][0]},
             {**iport("clip", "CLIP"), "link": src_outputs[(1,2)][0]},
             {**iport("vae", "VAE"), "link": src_outputs[(2,2)][0]},
             {**iport("positive", "CONDITIONING"), "link": src_outputs[(4,3)][0]},
             {**iport("negative", "CONDITIONING"), "link": src_outputs[(5,3)][0]},
             {**iport("bbox_detector", "BBOX_DETECTOR"), "link": src_outputs[(30,0)][0]},
         ],
         [oport("IMAGE", "IMAGE", src_outputs.get((31,0),[]))],
         # Widgets: guide_size, guide_size_for, max_size, seed, steps, cfg, sampler, scheduler,
         #          denoise, feather, noise_mask, force_inpaint, bbox_threshold, bbox_dilation, bbox_crop_factor,
         #          sam_detection_hint, sam_dilation, sam_threshold, sam_bbox_expansion, sam_mask_hint_threshold,
         #          sam_mask_hint_use_negative, drop_size, wildcard, cycle
         [1440, True, 2048, 42+400, 6, 1.0,
          "dpmpp_2m_sde_gpu", "sgm_uniform",
          0.30, 5, True, True, 0.5, 10, 2.0,
          "none", 0, 0.93, 0, 0.7, "False", 10, "", 1],
         "④ FaceDetailer (crop=2.0, denoise=0.30)"),

    node(40, "SaveImage", [3430, 420], [280, 100],
         [{**iport("images", "IMAGE"), "link": src_outputs[(31,0)][0]}],
         [],
         ["MoodyV7_"], "⑤ 保存图片"),

    # Note node omitted - MarkdownNote not installed in this environment.
    # To add a note in ComfyUI GUI: right-click canvas → Add Node → utils → Note
]

# Build links list
links = []
link_id = 1
for src_id, src_slot, dst_id, dst_slot, ltype in connections:
    links.append([link_id, src_id, src_slot, dst_id, dst_slot, ltype])
    link_id += 1

workflow = {
    "last_node_id": 40,
    "last_link_id": link_id - 1,
    "nodes": nodes,
    "links": links,
    "groups": [],
    "config": {},
    "extra": {},
    "version": 0.4,
}

os.makedirs(os.path.dirname(OUTFILE), exist_ok=True)
with open(OUTFILE, 'w', encoding='utf-8') as f:
    json.dump(workflow, f, ensure_ascii=False, indent=2)

print(f"Saved: {OUTFILE}")
print(f"Nodes: {len(nodes)}, Links: {len(links)}")
print("Drag this JSON into ComfyUI to use.")
