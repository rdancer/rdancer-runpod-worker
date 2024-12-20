import runpod
from runpod.serverless.utils import rp_upload
import json
import urllib.request
import urllib.parse
import time
import os
import requests
import base64
from io import BytesIO
import glob
import traceback



SERVICE_TYPE = os.environ.get("DOCKER_IMAGE_TYPE", "comfyui").lower().strip()
worker_name = f"runpod-worker-{SERVICE_TYPE}"

if os.getenv("DEBUG", False):
    print(f"{worker_name} - DEBUG is enabled")
    import debugpy
    debugpy.listen(("0.0.0.0", 5678))
    print(f"{worker_name} - Debugger listening on port 5678, connect now.")
    import time
    wait_time = 10
    for i in range(wait_time):
        print(f"{worker_name} - Waiting for debugger to attach ({wait_time-i: 3d})...")
        time.sleep(1)
        if debugpy.is_client_connected():
            print(f"{worker_name} - Debugger attached, proceeding.")
            break
    else:
        print(f"{worker_name} - Debugger failed to attach, proceeding.")

assert SERVICE_TYPE in ("comfyui", "deforum"), f"Internal error -- unknown service type: {SERVICE_TYPE}"

# Time to wait between API check attempts in milliseconds
SERVER_API_AVAILABLE_INTERVAL_MS = int(os.environ.get("COMFY_API_AVAILABLE_INTERVAL_MS", 500))
# Maximum number of API check attempts
SERVER_API_AVAILABLE_MAX_RETRIES = int(os.environ.get("COMFY_API_AVAILABLE_MAX_RETRIES", 86400))
# Time to wait between poll attempts in milliseconds
SERVER_POLLING_INTERVAL_MS = int(os.environ.get("COMFY_POLLING_INTERVAL_MS", 1000))
# Maximum number of poll attempts
SERVER_POLLING_MAX_RETRIES = int(os.environ.get("COMFY_POLLING_MAX_RETRIES", 86400)) # 24 hours -- handle timeouts using the worker timeout instead
# Host where the server is running
SERVER_HOST = {
    "comfyui": os.environ.get("COMFY_HOST", "127.0.0.1:8188"),
    "deforum": os.environ.get("WEBUI_HOST", "127.0.0.1:17860"),
}[SERVICE_TYPE]
# Enforce a clean state after each job is done
# see https://docs.runpod.io/docs/handler-additional-controls#refresh-worker
REFRESH_WORKER = os.environ.get("REFRESH_WORKER", "false").lower() == "true"


def validate_input(job_input):
    """
    Validates the input for the handler function.

    Args:
        job_input (dict): The input data to validate.

    Returns:
        tuple: A tuple containing the validated data and an error message, if any.
               The structure is (validated_data, error_message).
    """
    # Validate if job_input is provided
    if job_input is None:
        return None, "Please provide input"

    # Check if input is a string and try to parse it as JSON
    if isinstance(job_input, str):
        try:
            job_input = json.loads(job_input)
        except json.JSONDecodeError:
            return None, "Invalid JSON format in input"

    # Validate 'workflow' in input
    workflow = job_input.get("workflow")
    if workflow is None:
        return None, "Missing 'workflow' parameter"

    # Validate 'images' in input, if provided
    images = job_input.get("images")
    if images is not None:
        if not isinstance(images, list) or not all(
            "name" in image and "image" in image for image in images
        ):
            return (
                None,
                "'images' must be a list of objects with 'name' and 'image' keys",
            )

    # Return validated data and no error
    return {"workflow": workflow, "images": images}, None


def check_server(url, retries=SERVER_API_AVAILABLE_MAX_RETRIES, delay=SERVER_API_AVAILABLE_INTERVAL_MS):
    """
    Check if a server is reachable via HTTP GET request

    Args:
    - url (str): The URL to check
    - retries (int, optional): The number of times to attempt connecting to the server. Default is configurable via the COMFY_API_AVAILABLE_MAX_RETRIES environment variable
    - delay (int, optional): The time in milliseconds to wait between retries. Default is configurable via the COMFY_API_AVAILABLE_INTERVAL_MS environment variable

    Returns:
    bool: True if the server is reachable within the given number of retries, otherwise False
    """

    print(f"{worker_name} - Checking server at {url}")
    if os.getenv("DEBUG_NO_CHECK_SERVER", False):
        print(f"{worker_name} - Will skip server check because DEBUG_NO_CHECK_SERVER is enabled")
        return True

    for i in range(retries):
        try:
            response = requests.get(url)

            # If the response status code is 200, the server is up and running
            if response.status_code == 200:
                print(f"{worker_name} - API is reachable")
                return True
        except requests.RequestException as e:
            # If an exception occurs, the server may not be ready
            pass

        # Wait for the specified delay before retrying
        time.sleep(delay / 1000)

    print(
        f"{worker_name} - Failed to connect to server at {url} after {retries * delay / 1000:.1f} seconds."
    )
    return False


def guess_mime_type(file_name: str = None):
    """
    Guess the MIME type of an image based on its file extension.
    """
    try:
        extension = file_name.lower().split(".")[-1]
        mime_type = {
            "png":  "image/png",
            "jpg":  "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif":  "image/gif",
            "mp4":  "video/mp4",
            "webm": "video/webm",
            "txt":  "text/plain",
            "json": "application/json",
        }[extension.lower()]
    except:
        mime_type = "application/octet-stream"
    return mime_type

def upload_images(images):
    """
    Upload a list of base64 encoded images to the ComfyUI server using the /upload/image endpoint.

    Args:
        images (list): A list of dictionaries, each containing the 'name' of the image and the 'image' as a base64 encoded string.
        server_address (str): The address of the ComfyUI server.

    Returns:
        list: A list of responses from the server for each image upload.
    """
    if not images:
        return {"status": "success", "message": "No images to upload", "details": []}

    responses = []
    upload_errors = []

    print(f"{worker_name} - image(s) upload")

    for image in images:
        name = image["name"].split("/")[-1]
        if "\\" in name:
            print(f"{worker_name} - Warning: image name contains a backslash, maybe a Windows path?: {name}")
        image_data = image["image"]
        blob = base64.b64decode(image_data)
        mime_type = guess_mime_type(name)

        # Prepare the form data
        files = {
            "image": (name, BytesIO(blob), mime_type),
            "overwrite": (None, "true"),
        }

        # POST request to upload the image
        response = requests.post(f"http://{SERVER_HOST}/upload/image", files=files)
        if response.status_code != 200:
            upload_errors.append(f"Error uploading {name}: {response.text}")
        else:
            responses.append(f"Successfully uploaded {name}")

    if upload_errors:
        print(f"{worker_name} - image(s) upload with errors")
        return {
            "status": "error",
            "message": "Some images failed to upload",
            "details": upload_errors,
        }

    print(f"{worker_name} - image(s) upload complete")
    return {
        "status": "success",
        "message": "All images uploaded successfully",
        "details": responses,
    }


def queue_workflow(workflow):
    """
    Queue a workflow to be processed by ComfyUI

    Args:
        workflow (dict): A dictionary containing the workflow to be processed

    Returns:
        dict: The JSON response from ComfyUI after processing the workflow
    """

    if SERVICE_TYPE == "comfyui":
        # The top level element "prompt" is required by ComfyUI
        data = json.dumps({"prompt": workflow}).encode("utf-8")
        api_url = f"http://{SERVER_HOST}/prompt"
    elif SERVICE_TYPE == "deforum":
        data = json.dumps(workflow).encode("utf-8")
        api_url = f"http://{SERVER_HOST}/deforum_api/batches"
    else:
        raise ValueError("Invalid SERVICE_TYPE")
    req = urllib.request.Request(api_url, data=data)
    req.add_header("Content-Type", "application/json")
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read())
    except urllib.error.HTTPError as e:
        return {"error": str(e), "error_response": e.read().decode('utf-8'), "response": res.read() if 'res' in locals() else None, "workflow": workflow, "api_url": api_url}

def get_deforum_job_status(job_id):
    """
    Get the status of a Deform job using its ID
    """
    with urllib.request.urlopen(f"http://{SERVER_HOST}/deforum_api/jobs/{job_id}") as response:
        return json.loads(response.read())

def get_comfyui_history(job_id):
    """
    Retrieve the history of a given prompt using its ID

    Args:
        prompt_id (str): The ID of the prompt whose history is to be retrieved

    Returns:
        dict: The history of the prompt, containing all the processing steps and results
    """
    with urllib.request.urlopen(f"http://{SERVER_HOST}/history/{job_id}") as response:
        return json.loads(response.read())


def base64_encode(img_path):
    """
    Returns base64 encoded image.

    Args:
        img_path (str): The path to the image

    Returns:
        str: The base64 encoded image
    """
    with open(img_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        return f"{encoded_string}"


def process_output_images(outputs, job_id):
    """
    This function takes the "outputs" from image generation and the job ID,
    then determines the correct way to return the image, either as a direct URL
    to an AWS S3 bucket or as a base64 encoded string, depending on the
    environment configuration.

    Args:
        outputs (dict): A dictionary containing the outputs from image generation,
                        typically includes node IDs and their respective output data.
                        (for comfyui)
        outputs (str): Absolute file path of the directory which contains the generated images & videos. (for deforum)
        job_id (str): The unique identifier for the job.

    Returns:
        dict: A dictionary with the status ('success' or 'error') and the message,
              which is either the URL to the image in the AWS S3 bucket or a base64
              encoded string of the image. In case of error, the message details the issue.

    The function works as follows:
    - It first determines the output path for the images from an environment variable,
      defaulting to "/comfyui/output" if not set.
    - It then iterates through the outputs to find the filenames of the generated images.
    - After confirming the existence of the image in the output folder, it checks if the
      AWS S3 bucket is configured via the BUCKET_ENDPOINT_URL environment variable.
    - If AWS S3 is configured, it uploads the image to the bucket and returns the URL.
    - If AWS S3 is not configured, it encodes the image in base64 and returns the string.
    - If the image file does not exist in the output folder, it returns an error status
      with a message indicating the missing image file.
    """

    if SERVICE_TYPE == "comfyui":
        # The path where ComfyUI stores the generated images
        OUTPUT_PATH = os.environ.get("COMFY_OUTPUT_PATH") or os.environ.get("WEBUI_OUTPUT_PATH") or "/comfyui/output"

        output_images = []
        all_outputs = {}

        for node_id, node_output in outputs.items():
            if "images" in node_output:
                for image in node_output["images"]:
                    output_images.append(os.path.join(OUTPUT_PATH, image["subfolder"], image["filename"]))
            if "gifs" in node_output:
                for video in node_output["gifs"]:
                    output_images.append(os.path.join(OUTPUT_PATH, video["subfolder"], video["filename"]))
            if node_output:
                all_outputs[node_id] = node_output
                    
    elif SERVICE_TYPE == "deforum":
        # the basename looks like "/runpod-volume/stable-diffusion-webui/outputs/img2img-images/Deforum_20241204213940"
        # so we have to do the equivalent of "/runpod-volume/stable-diffusion-webui/outputs/img2img-images/Deforum_20241204213940"* to get all the images' paths
        output_images = [f for f in glob.glob(f"{outputs}/*") if os.path.isfile(f)]

    print(f"{worker_name} - image generation is done")

    encoded_output_images = []
    for local_image_path in output_images:
        print(f"{worker_name} - {local_image_path}")

        # The image is in the output folder
        if os.path.exists(local_image_path):
            base_name = os.path.basename(local_image_path)
            if os.environ.get("BUCKET_ENDPOINT_URL", False):
                # URL to image in AWS S3
                image = rp_upload.upload_image(job_id, local_image_path)
                print(
                    f"{worker_name} - the image {base_name} was generated and uploaded to AWS S3"
                )
            else:
                # base64 image
                encoded_output_images.append({
                    "name": base_name,
                    "image": base64_encode(local_image_path)
                })
                print(
                    f"{worker_name} - the image {base_name} was generated and converted to base64"
                )
    if encoded_output_images:
        print(f"{worker_name} - Success: sending image{'s' if len(encoded_output_images)>1 else ''}: {[f['name'] for f in encoded_output_images]}")
        ret = {
            "status": "success",
            "images": encoded_output_images,
        }
        if "all_outputs" in locals():
            ret["outputs"] = all_outputs
        return ret
    else:
        if output_images:
            message = f"Images generated, but none exist in the output folder: {output_images}"
        else:
            message = "No images were generated"
        print(f"{worker_name} - {message}")
        ret = {
            "status": "error",
            "error": message,
        }
        if "all_outputs" in locals():
            ret["outputs"] = all_outputs
        return ret


def handler(job):
    """
    The main function that handles a job of generating an image.

    This function validates the input, sends a prompt to ComfyUI for processing,
    polls ComfyUI for result, and retrieves generated images.

    Args:
        job (dict): A dictionary containing job details and input parameters.

    Returns:
        dict: A dictionary containing either an error message or a success status with generated images.
    """
    try:
        job_input = job["input"]

        # Make sure that the input is valid
        validated_data, error_message = validate_input(job_input)
        if error_message:
            return {"error": error_message}

        # Extract validated data
        workflow = validated_data["workflow"]
        images = validated_data.get("images")

        # Make sure that the ComfyUI API is available
        check_server(
            f"http://{SERVER_HOST}",
            SERVER_API_AVAILABLE_MAX_RETRIES,
            SERVER_API_AVAILABLE_INTERVAL_MS,
        )

        # Upload images if they exist
        upload_result = upload_images(images)

        if upload_result["status"] == "error":
            return upload_result

        # Queue the workflow
        queued_workflow = None
        try:
            queued_workflow = queue_workflow(workflow)
            if SERVICE_TYPE == "comfyui":
                job_id = queued_workflow["prompt_id"]
            elif SERVICE_TYPE == "deforum":
                job_id = queued_workflow["job_ids"][0]
            print(f"{worker_name} - queued workflow with ID {job_id}")
        except Exception as e:
            traceback_str = traceback.format_exc()
            return {"error": f"Error queuing workflow -- {e.__class__.__name__}: {str(e)}", "traceback": traceback_str, "workflow": workflow, "queued_workflow": queued_workflow}

        # Poll for completion
        print(f"{worker_name} - wait until image generation is complete")
        retries = 0
        images_result = {}
        try:
            while retries < SERVER_POLLING_MAX_RETRIES:
                if SERVICE_TYPE == "comfyui":
                    history = get_comfyui_history(job_id)

                    # Exit the loop if we have found the history or encountered an error
                    if job_id in history and history[job_id].get("outputs"):
                        images_result = process_output_images(history[job_id].get("outputs"), job_id)
                        break
                    else:
                        try:
                            if history[job_id]["status"]["status_str"] in ["error"]:
                                return {"error": "Image generation failed -- ComfyUI workflow failed unexpectedly", "full_response": history[job_id]}
                        except:
                            pass
                elif SERVICE_TYPE == "deforum":
                    job_status = get_deforum_job_status(job_id)
                    if job_status["status"] == "FAILED":
                        return {"error": "Image generation failed", "full_response": job_status}
                    elif job_status["status"] == "SUCCEEDED":
                        output_directory_absolute_path = job_status["outdir"]
                        images_result = process_output_images(output_directory_absolute_path, job_id)
                        break
                    # break
                else:
                    raise ValueError("Invalid SERVICE_TYPE")
                # Wait before trying again
                time.sleep(SERVER_POLLING_INTERVAL_MS / 1000)
                retries += 1
            else:
                return {"error": "Max retries reached while waiting for image generation"}
        except Exception as e:
            return {"error": f"Error waiting for image generation: {str(e)}"}
        # Get the generated image and return it as URL in an AWS bucket or as base64
        result = {**images_result, "refresh_worker": REFRESH_WORKER}
    except Exception as e:
        # stringify and jsonify the trackback
        traceback_str = traceback.format_exc()
        result = {"error": f"Error: {e.__class__.__name__}: {str(e)}", "traceback": traceback_str}
    return result


# Start the handler only if this script is run directly
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})

