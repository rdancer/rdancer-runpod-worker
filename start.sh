#!/usr/bin/env bash

set -x

ensure_network_volume_mounted() {
    ln -s /runpod-volume /workspace

    while [ ! -d "/workspace/ComfyUI" ]; do
        echo "Waiting for /workspace/ComfyUI to be mounted..."
        sleep 1
    done

    echo "/workspace/ComfyUI is now available."
    ls -l /workspace # lrwxrwxrwx 1 root root 14 Dec  4 19:57 /workspace -> /runpod-volume
    ls -l /workspace/ # list contents of the mounted volume
}
ensure_network_volume_mounted

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

# Serve the API and don't shutdown the container
if [ -z "$DOCKER_IMAGE_TYPE" ]; then
    DOCKER_IMAGE_TYPE="comfyui"
fi
if [ "$DOCKER_IMAGE_TYPE" == "comfyui" ]; then
    echo "runpod-worker-$DOCKER_IMAGE_TYPE: Starting ComfyUI"
    (
        cd /workspace/ComfyUI
        . /workspace/ComfyUI/venv/bin/activate
        python3 main.py --disable-auto-launch --disable-metadata 2>&1 | tee -a /workspace/ComfyUI/logs/sls-comfyui.log &
    )
    echo "runpod-worker-$DOCKER_IMAGE_TYPE: Starting RunPod Handler"
    python3 -u /rp_handler.py
elif [ "$DOCKER_IMAGE_TYPE" == "deforum" ] || [ "$DOCKER_IMAGE_TYPE" == "a1111" ]; then
    echo "runpod-worker-$DOCKER_IMAGE_TYPE: Starting ${DOCKER_IMAGE_TYPE}"

    # Note that init.sh requires a (fairly recent version of) bash
    (
        if [ -n "$DEBUG" ]; then
            # Wait for a bit so that we can see initial handler logs
            sleep 5
        fi
        export SERVERLESS=true # Only run webui and not Portal or any of the other AI-Dock services
        export WEB_ENABLE_AUTH=false # Enable normal API access; besides, we don't have any ports open externally => auth is redundant
        /bin/bash ${DEBUG:+-x} /opt/ai-dock/bin/init.sh &
    )

    echo "runpod-worker-$DOCKER_IMAGE_TYPE: Starting RunPod Handler"
    if [ -n "$DEBUG" ]; then
        while :; do python3 -m debugpy --listen 0.0.0.0:5678 /rp_handler.py; sleep 1; done
    else
        python3 -u /rp_handler.py
    fi
fi

