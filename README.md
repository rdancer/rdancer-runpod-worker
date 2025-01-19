# Docker images `rdancer/runpod-worker-comfy`, `rdancer/runpod-worker-a1111`, `rdancer/runpod-worker-deforum`

*Note: each worker image has its own branch in this repo, named same as the DockerHub name, i.e. `rdancer/runpod-worker-comfy`, `rdancer/runpod-worker-a1111`, and `rdancer/runpod-worker-deforum`.*

These are minimal changes on top of https://github.com/blib-la/runpod-worker-comfy to make this work nice with my Runpod images.

We will set up a Pod (server) and a serverless worker. They both share the same network volume. The instructions below have been tested with modified AI-Dock, but as long as ComfyUI is installed in /workspace/ComfyUI, with venv in /workspace/ComfyUI/venv (and analogously for A1111), this image should work.

### RunPod Pod

*TODO: Revise for A1111 and for Streaming*

The main point of this image is to be able to work with a single network volume attached at /workspace, both from a pod and from a serverless worker.

Currently this is a work in progress, and requires quite a few manual steps. Once you have verified that everything works, you should be able to save your setup as a template.

1. Create network volume
  - on the pod, this will be always attached to /workspace
  - on the serverless instance, this will be always attached to /runpod-volume (ideally we would want this to be consistent, but unfortunately this is not configurable)
2. Deploy the network volume with the AI-Dock [ComfyUI template](https://www.runpod.io/console/explore/57we0zdwtt) or [A1111 Web-UI with Deforum template](https://www.runpod.io/console/explore/f1ohaqcrbo)
  - remember to attach the network volume you have created in (1)
  - edit the template and change/add *Environment Variables*:
  - ComfyUI:
    - WORKSPACE = /workspace
    - ~COMFYUI_VENV = /workspace/environments/python/comfyui~
    - ~rename PROVISIONING_SCRIPT to UPSTREAM_PROVISIONING_SCRIPT~
    - ~PROVISIONING_SCRIPT = https://raw.githubusercontent.com/rdancer/runpod-worker-comfy-actual/master/provisioning_script.sh~
    - Note: there is a bug in the upstream Docker image that means $PROVISIONING_SCRIPT is being ignored (although it is specified in the template, so I'm not sure what's going on). Work-around:
      - run the template normally
      - after install has finished, connect via web terminal, and run: `curl -sSL https://raw.githubusercontent.com/rdancer/runpod-worker-comfy-actual/master/provisioning_script.sh | bash`
      - only then set COMFYUI_VENV = /workspace/environments/python/comfyui (this will reboot the instance)
    - (optionally) change WEB_USER and WEB_PASSWORD to something secure
  - Deforum:
    - Same as above, but:
     - add the following to the WEBUI_ARGS: --api --deforum-api
      - instead of COMFYUI_ENV, use WEBUI_VENV = /workspace/environments/python/webui
3. Run the modified template, and wait for the installation to be over
  - verify that ComfyUI is working, by running the default workflow
  - save the default workflow in API mode `workflow_api.json` -- we will use this to test the serverless endpoint later
4. Having verified that the Pod works, edit the pod and change *Environmental Variables*:
  - delete PROVISIONING_SCRIPT and UPSTREAM_PROVISIONING_SCRIPT
  - disable services that you do not need by setting this variable to any of the following (comma-separated list):
    - SUPERVISOR_NO_AUTOSTART = caddy,cloudflared,jupyter,logtail,quicktunnel,serviceportal,sshd,storagemonitor,syncthing
  - it is strongly recommended that at this point, you create a copy of the template with these modified settings
  - when you save the settings, the pod will restart
5. Create a new serverless endpoint
  - container image: rdancer/rdancer-comfyui-worker:latest (this repository)
  - Container Disk: 20GB
  - Environmental Variables:
    - COMFYUI_OUTPUT_PATH = /workspace/ComfyUI/output
  - Attach the network volume created in (1) above
6. Run the serverless endpoint
  - verify everything is working by running the `workflow_api.json` saved in (3) above


_At this point, workflows prepared in the interactive ComfyUI interface can be processed by the serverless instance._

## RunPod Serverless Worker

### Timeout variables

#### ComfyUI

If you use too high values, your jobs will be hanging and you will be paying for crashed workers. On the other hand, values that are too low will result in all working trying to execute jobs in a loop and timing half way through every time. Sensible values depend on your particular situation.

`COMFY_API_AVAILABLE_INTERVAL_MS`: Time (ms) between API availability checks. Default: 500.

`COMFY_API_AVAILABLE_MAX_RETRIES`: Max API check attempts. Default: 86400.

`COMFY_POLLING_INTERVAL_MS`: Time (ms) between polling attempts. Default: 1000.

`COMFY_POLLING_MAX_RETRIES`: Max polling attempts. Default: 86400.


The defaults are geared towards the "Execution Timeout" in Edit Endpoint being used exclusively for timeout control.


### Environment variables

#### S3

If you're returning a lot of images, it will be more efficient to use S3. Also there are some limits on the size of the responses in the Runpod API, and passing S3 URLs will help to stay within these limits.

```
SAVE_TO_S3 = true # defaults to false -- if set, will save to S3 and return the corresponding pre-signed https: URL, else it will return data: URIs
AWS_REGION=eu-central-1
AWS_ACCESS_KEY_ID = KDLTYIDEHIIBZTYQPORY
AWS_SECRET_ACCESS_KEY = c5uqPiax6YOPvEFBF7AKT4c4Lvsd3c1Pn+2Vq9Y+
AWS_S3_BUCKET = my-bucket
```

### Input schema

POST this to https://api.runpod.ai/v2/{{SLS_ENDPOINT_ID}}/run

#### ComfyUI

```json
{
  "input": {
      "workflow": <workflow_api.json>,
      "images": [
        {
          "name": "foo.png", // only PNG is supported by rp_handler.py at the moment
          "url": "data: or https:" // data: if SAVE_TO_S3 is false, https: if SAVE_TO_S3 is true
        },
        ...
      ]
  }
}
```

#### Deforum

```json
{
    // TODO
}
```


### In-Progress Status

While the job is *IN_PROGRESS*, the status is updated periodically with logs:

```json
{
    "delayTime": 14604,
    "id": "5b775469-d6e6-4af2-815b-649007fcfada-e1",
    "output": {
        // these are raw logs, with terminal escape sequences; lines are terminated with \n; note that progress bars often are overprinted using bare \r
        "log": "[2024-12-29 21:17:29.927] got prompt\n[2024-12-29 21:17:34.416] model weight dtype torch.float16, manual cast: None\n[2024-12-29 21:17:34.418] model_type EPS\n"
    },
    "status": "IN_PROGRESS",
    "workerId": "o4z7gczo8to13u"
}
```

### Streaming output

You can stream the output from the /stream endpoint. The schema is similar to the final output schema, but the output is sharded under the `stream` key.

### Output schema

#### ComfyUI

It is perfectly fine to operate the API in a fire-and-forget mode. Runpod will keep trying to process the jobs until it succeeds. You can monitor the job queue on the endpoint's page, and once the job completes, the output images will be permanently saved to /workspace/ComfyUI/output.

Please refer to https://docs.runpod.io/docs/api-reference/run-endpoint for more information on monitoring the job queue and individual job status.

A successfully *completed* job will return a JSON object like this:

```json
{
  "delayTime": 226952,
  "executionTime": 153879,
  "id": "b39ee8c4-0d0c-4dcb-aedc-364d4fa771eb-u1",
  "output": [
    {
      // there is either "images" or "log" or both, and sometimes other keys such as "error", "satatus", etc.
      "images": [
        {
          "url": "data: or https:", // data: if SAVE_TO_S3 is false, https: if SAVE_TO_S3 is true
          "name": "image_0000.png"
        },
        ...
      ],
      "log": "\n\n2023-09-21 14:58:18.718 \e[31m;INFO\e[0;   | comfyui.server:handle_req..."
    },
    ...
  ],
  "status": "COMPLETED",
  "workerId": "r853qiic7qsaf3"
}
```
