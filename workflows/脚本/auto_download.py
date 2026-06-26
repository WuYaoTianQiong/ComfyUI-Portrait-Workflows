"""
Automated download Qwen-Image-Edit models (HF-Mirror China)
Adapted for 12GB VRAM: use FP8 + GGUF Q5_K_M quantization
"""

import os
import sys
import urllib.request
import time

# Config
HF_MIRROR = "https://hf-mirror.com"
DOWNLOAD_LIST = [
    # (filename, target_dir, download_URL)
    (
        "qwen_2.5_vl_7b_fp8_scaled.safetensors",
        r"d:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\ComfyUI\models\clip",
        f"{HF_MIRROR}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
    ),
    (
        "ae.safetensors",
        r"d:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\ComfyUI\models\vae",
        f"{HF_MIRROR}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/ae.safetensors"
    ),
    (
        "qwen-image-edit-rapid-aio-q5_k_m.gguf",
        r"d:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\ComfyUI\models\unet",
        f"{HF_MIRROR}/Phil2Sat/Qwen-Image-Edit-Rapid-AIO-GGUF/resolve/main/qwen-image-edit-rapid-aio-q5_k_m.gguf"
    ),
]

def download_file(url, filepath):
    """Download file with progress"""
    filename = os.path.basename(filepath)
    dirname = os.path.dirname(filepath)
    
    # Create directory
    os.makedirs(dirname, exist_ok=True)
    
    # Check if already exists
    if os.path.exists(filepath):
        print(f"[OK] Already exists: {filename}")
        return True
    
    # Download
    try:
        print(f"[..] Downloading: {filename}")
        print(f"     URL: {url[:80]}...")
        
        # Use urllib to download
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
            total_size = int(response.headers.get('Content-Length', 0))
            block_size = 8192
            downloaded = 0
            
            start_time = time.time()
            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                out_file.write(buffer)
                downloaded += len(buffer)
                
                # Progress display
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    elapsed = time.time() - start_time
                    speed = mb_downloaded / elapsed if elapsed > 0 else 0
                    
                    print(f"\r    {percent:5.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB) {speed:.1f} MB/s", end='')
            
            print(f"\n[OK] Download complete: {filename}")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Download failed: {e}")
        # Delete incomplete file
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

def main():
    print("=" * 70)
    print("Automated download Qwen-Image-Edit models (HF-Mirror China)")
    print("=" * 70)
    
    success_count = 0
    total_count = len(DOWNLOAD_LIST)
    
    for i, (filename, target_dir, url) in enumerate(DOWNLOAD_LIST, 1):
        print(f"\n[{i}/{total_count}] {filename}")
        filepath = os.path.join(target_dir, filename)
        
        if download_file(url, filepath):
            success_count += 1
    
    print("\n" + "=" * 70)
    print(f"Download complete: {success_count}/{total_count} files")
    print("=" * 70)
    
    if success_count == total_count:
        print("\n[SUCCESS] All models downloaded!")
        print("\nNext steps:")
        print("  1. Run auto_install_nodes.py to install custom nodes")
        print("  2. Restart ComfyUI")
        print("  3. Load the modified workflow (1024x1024 resolution)")
    else:
        print(f"\n[WARNING] Some downloads failed. Check network connection.")
        print("  Manual download: Visit https://hf-mirror.com")
    
    return success_count == total_count

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
