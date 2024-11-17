# Docker image `rdancer/runpod-worker-comfy`

These are minimal changes on top of https://github.com/blib-la/runpod-worker-comfy to make this work nice with my Runpod images. Tested with modified AI-Dock, but as long as ComfyUI is installed in /workspace/ComfyUI, with venv in /workspace/ComfyUI/venv, this image should work.

## AI-Dock instructions

The main point of this image is to be able to work with a single network volume attached at /workspace, both from a pod and from a serverless worker.

1. Create network volume
2. Deploy the network volume with the AI-Dock template
  - opt to select a template, and use the search box to search for AI-Dock
3. Run the template with the default settings, and wait for the installation to be over
  - verify that ComfyUI is working, by running the default workflow
  - save the default workflow in API mode `workflow_api.json`
4. Connect via web shell, and
  - `cp -r "$COMFYUI_VENV" /workspace/ComfyUI/venv`
5. Edit the pod and change Environmental Variables
  - delete PROVISIONING_SCRIPT
  - add new variables:
    - WORKSPACE = /workspace
    - COMFYUI_VENV = /workspace/ComfyUI/venv *[isn't this set automatically by setting WORKSPACE?]*
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
