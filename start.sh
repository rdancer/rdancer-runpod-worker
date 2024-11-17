#!/usr/bin/env bash

set -x

ensure_network_volume_mounted() {
    ln -s /runpod-volume /workspace

    while [ ! -d "/workspace/ComfyUI" ]; do
        echo "Waiting for /workspace/ComfyUI to be mounted..."
        sleep 1
    done

    echo "/workspace/ComfyUI is now available."
    ls -l /workspace
}
ensure_network_volume_mounted

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

# Serve the API and don't shutdown the container
if [ "$SERVE_API_LOCALLY" == "true" ]; then
    echo "runpod-worker-comfy: Starting ComfyUI"
    python3 /comfyui/main.py --disable-auto-launch --disable-metadata --listen &

    echo "runpod-worker-comfy: Starting RunPod Handler"
    python3 -u /rp_handler.py --rp_serve_api --rp_api_host=0.0.0.0
else
    echo "runpod-worker-comfy: Starting ComfyUI"
    (
        cd /workspace/ComfyUI
        . /workspace/ComfyUI/venv/bin/activate
        python3 main.py --disable-auto-launch --disable-metadata 2>&1 | tee -a /workspace/ComfyUI/logs/sls-comfyui.log &
    )

    echo "runpod-worker-comfy: Starting RunPod Handler"
    python3 -u /rp_handler.py
fi