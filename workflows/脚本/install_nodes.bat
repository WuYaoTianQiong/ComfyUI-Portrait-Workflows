@echo off
echo 安装缺失的自定义节点...
echo.

set CUSTOM_NODES=d:\Entertainment\ComfyUI-aki-v2\ComfyUI-aki-v3\ComfyUI\custom_nodes

cd /d "%CUSTOM_NODES%"

echo 1. 安装 ComfyUI_Comfyroll_CustomNodes
git clone https://github.com/RockOfFire/ComfyUI_Comfyroll_CustomNodes.git ComfyUI_Comfyroll_CustomNodes

echo 2. 安装 comfyui_layerstyle
git clone https://github.com/AIGODLIKE/comfyui_layerstyle.git comfyui_layerstyle

echo 3. 安装 comfyui-openpose-editor-dockr
git clone https://github.com/DocWorkBox/ComfyUI-OpenPose-Editor-DocKr.git comfyui-openpose-editor-dockr

echo 4. 安装 pr-was-node-suite-comfyui
git clone https://github.com/WASasquatch/was-node-suite-comfyui.git pr-was-node-suite-comfyui

echo.
echo ✅ 自定义节点安装完成！
echo 现在重启 ComfyUI...
pause
