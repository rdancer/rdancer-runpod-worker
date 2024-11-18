# Docker image `rdancer/runpod-worker-comfy`

These are minimal changes on top of https://github.com/blib-la/runpod-worker-comfy to make this work nice with my Runpod images. Tested with modified AI-Dock, but as long as ComfyUI is installed in /workspace/ComfyUI, with venv in /workspace/ComfyUI/venv, this image should work.

## AI-Dock instructions

The main point of this image is to be able to work with a single network volume attached at /workspace, both from a pod and from a serverless worker.

Currently this is a work in progress, and requires quite a few manual steps.

1. Create network volume
2. Deploy the network volume with the [AI-Dock template](https://www.runpod.io/console/explore/57we0zdwtt)
  - remember to attach the network volume you have created in (1)
3. Run the template with the default settings, and wait for the installation to be over
  - verify that ComfyUI is working, by running the default workflow
  - save the default workflow in API mode `workflow_api.json`
4. Connect via web shell, and:
  - `pip freeze > reqs.txt; deactivate; python3 -m venv /workspace/ComfyUI/venv; . /workspace/ComfyUI/venv/bin/activate; pip install -r reqs.txt`
  - If install fails, you may need to do: `pip install torch==2.4.1+cu121 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121` or somesuch
  - `mkdir -p  /workspace/environments/python && ln -s /workspace/ComfyUI/venv /workspace/environments/python/comfyui`
5. Edit the pod and change Environmental Variables
  - delete PROVISIONING_SCRIPT
  - add new variables:
    - WORKSPACE = /workspace
    - COMFYUI_VENV = /workspace/ComfyUI/venv
  - change WEB_USER and WEB_PASSWORD to something secure
  - it is strongly recommended that at this point, you create a copy of the template with these modified settings
  - when you save the settings, the pod will restart
6. Create a new serverless endpoint
  - container image: rdancer/rdancer-comfyui-worker:latest (this repository)
  - Container Disk: 20GB
  - Environmental Variables:
    - COMFYUI_OUTPUT_PATH = /workspace/ComfyUI/output
  - Attach the network volume created in (1) above
7. Run the serverless endopint
  - verify everything is working by running the `workflow_api.json` saved in (3) above


_At this point, workflows prepared in the interactive ComfyUI interface can be processed by the serverless instance._

## Timeout variables

If you use too high values, your jobs will be hanging and you will be paying for crashed workers. On the other hand, values that are too low will result in all working trying to execute jobs in a loop and timing half way through every time. Sensible values depend on your particular situation.

`COMFY_API_AVAILABLE_INTERVAL_MS`: Time (ms) between API availability checks. Default: 500.

`COMFY_API_AVAILABLE_MAX_RETRIES`: Max API check attempts. Default: 86400.

`COMFY_POLLING_INTERVAL_MS`: Time (ms) between polling attempts. Default: 1000.

`COMFY_POLLING_MAX_RETRIES`: Max polling attempts. Default: 86400.


The defaults are geared towards the "Execution Timeout" in Edit Endpoint being used exclusively for timeout control.




