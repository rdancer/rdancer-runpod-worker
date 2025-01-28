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
else
    echo "runpod-worker-utility: Starting Utility Handler"
    python3 -u /rp_handler.py
fi