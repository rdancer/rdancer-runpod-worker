from signal import signal
import uuid
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
import threading
from datetime import datetime
from tempfile import NamedTemporaryFile
import re
import tqdm


class InternalServerError(Exception):
    pass

class JobCancelledException(Exception):
    pass

def raise_for_cancel(runpod_job_id: str):
    """
    Checks if a job has been cancelled, deletes the cancellation signal file,
    and raises JobCancelledException if the job is cancelled.

    :param job_id: The ID of the job being checked.
    :raises JobCancelledException: If the job was cancelled by the user.
    """
    if not runpod_job_id:
        print(f"Warning: Runpod Job ID is missing.")
        return

    CANCEL_DIR = "/workspace/tasks/cancel/ids"
    try:
        cancel_path = os.path.join(CANCEL_DIR, fs_safe(runpod_job_id, raise_=True))
    except UnsafeInputError:
        print(f"Warning: Runpod Job ID is filesystem-unsafe: {runpod_job_id}")
        return

    if os.path.exists(cancel_path):
        # Get the timestamp of when cancellation was requested
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(cancel_path)))

        # Remove the cancellation file to clean up
        try:
            os.remove(cancel_path)
        except:
            print(f"Warning: Failed to remove cancellation file: {cancel_path}")
            pass

        # Raise the exception with a simple message
        message = f"Cancelling job '{runpod_job_id}' as requested at {timestamp}."
        print(message)
        raise JobCancelledException(message)

class JobTimestampCallback:
    """
    A class that handles job timestamping.
    """
    def __init__(self):
        self.timestamp = datetime.now()
    
    def set_job_id(self, job_id: str, is_fake=False) -> None:
        """
        Set the job id and store the timestamp in the database.

        The `is_fake` argument is ignored in this implementation.
        """
        JobTimestamp.database[job_id] = self.timestamp # This leaks about a word per job. That is fine.

class JobTimestamp:
    """
    A class that handles job timestamping.

    The job timestamp is captured as soon as a job is received.

    At some later point, the job id is obtained and stored by the class.

    Later the timestamp can be retrieved by any method that is interested in knowing the timestamp of the job, without the timestamp having to be passed around as a parameter.

    This class is not to be instantiated. It is a static class.
    """
    def __init__(self):
        raise Exception("This class is not to be instantiated. It is a static class.")


    database = {} # job_id -> timestamp

    @staticmethod
    def start_job():
        """
        Start a job and capture the timestamp.

        Returns:
            a class with a callback set_job_id(), which will store the job id in the database
        """
        return JobTimestampCallback()

    @staticmethod
    def get_timestamp(job_id: str) -> datetime:
        """
        Get the timestamp of a job.

        Args:
            job_id (str): The job id of the job whose timestamp is to be retrieved

        Returns:
            datetime: The timestamp of the job
        """
        timestamp = JobTimestamp.database.get(job_id)
        if timestamp is None:
            raise ValueError(f"Job {job_id} not found in database")
        return timestamp

class LastLog(str):
    """
    A string subclass that captures the last log messages from the ComfyUI or Deform server logs.

    To avoid races (printing other jobs' logs), instantiate this class *just before* a job is started, and only call it while the job is ongoing. We will probably need to call this class one last time just after the job finishes, and if there are back-to-back jobs, we may print the next job's logs. We would need to refactor the logging of the upstream services to avoid this, which we won't, or restart the service after every job, which we also don't want to do. So we'll just have to live with the possibility of printing the next job's logs, for now.
    """
    def __new__(cls, service_type, *args, **kwargs):
        instance = super().__new__(cls, *args, **kwargs)
        instance.service_type = service_type
        now = datetime.now()
        instance.ignore_before = now
        instance.sent_data = ""
        return instance
    
    def __str__(self):
        return self.get_log()
    
    def get_log(self, last_only=True):
        if self.service_type == "comfyui":
            s = self.comfyui_log()
        elif self.service_type == "deforum":
            s = self.deforum_log()
        elif self.service_type == "a1111":
            s = self.a1111_log()
        else:
            s = ""
        if not last_only:
            return s
        # Check if truncated or something else went wrong
        # The first len(self.sent_data) characters of s should be self.sent_data
        if not s.startswith(self.sent_data):
            print(f"WARNING: Truncated log message! {len(s)} characters, {len(self.sent_data)} sent so far.")
            to_send = s
        else:
            to_send = s[len(self.sent_data):]
        self.sent_data += to_send
        return to_send

    def a1111_log(self):
        """
        WARNING:root:Sampler Scheduler autocorrection: "Euler" -> "Euler", "default" -> "Automatic"
        INFO:sd_dynamic_prompts.dynamic_prompting:Prompt matrix will create 3 images in a total of 1 batches.
        ...
        Total progress: 100%|██████████| 50/50 [00:04<00:00, 11.21it/s]
        """
        LOG_FILE = "/var/log/supervisor/webui.log"
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            # Find the last occurence of /INFO:sd_dynamic_prompts.dynamic_prompting:Prompt matrix will create/
            lines.reverse()
            printable_lines = []
            good_log = False
            for line in lines:
                printable_lines.append(line)
                if "INFO:sd_dynamic_prompts.dynamic_prompting:Prompt matrix will create" in line:
                    good_log = True
                    # Ignore the /Euler/ line, that's fine, those errors are not always there, and we don't have a good way to figure out which errors are ours
                    break
            printable_lines.reverse()
            return "".join(printable_lines) if good_log else ""
        
    def deforum_log(self):
        """
        INFO:deforum_api:Starting batch batch(230991444) in thread 127007337743936.
        ...
        ^MVideo stitching ESC[0;32mdoneESC[0m in 1.07 seconds!
        """
        LOG_FILE = "/var/log/supervisor/webui.log"
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            # Find the last occurence of /deforum_api:Starting batch/
            lines.reverse()
            printable_lines = []
            good_log = False
            for line in lines:
                printable_lines.append(line)
                if "deforum_api:Starting batch" in line:
                    good_log = True
                    break
            printable_lines.reverse()
            return "".join(printable_lines) if good_log else ""

    def comfyui_log(self):
        """
        Every 1.0s: ../bin/lastlog_comfy.sh                                                                                        d4c8c0aac707: Sat Dec 28 16:37:30 2024

        [2024-12-28 16:36:45.533] got prompt
        [2024-12-28 16:36:45.595] Prompt executed in 0.05 seconds
        """
        LOG_FILE = "/workspace/ComfyUI/comfyui.log"
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            # Find the last occurence of /] got prompt$/
            lines.reverse()
            printable_lines = []
            start_datetime = None
            for line in lines:
                printable_lines.append(line)
                # I believe this will reliably match even in cases where multiple processes write into the same file
                if line.strip().endswith("] got prompt"):
                    timestamp = line.split("]")[0].split("[")[1].strip()
                    try:
                        start_datetime = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")
                    except:
                        start_datetime = None
                    break
            printable_lines.reverse()
            if start_datetime is None:
                return ""
            elif start_datetime < self.ignore_before:
                return ""
            else:
                return "".join(printable_lines)

def get_bool_env(var_name, default=False):
    """
    Retrieve an environment variable as a boolean value using `strtobool`.

    :param var_name: Name of the environment variable.
    :param default: Default value if the environment variable is not set.
    :return: Boolean representation of the environment variable.
    """
    value = os.getenv(var_name, str(default)).lower().strip()
    try:
        return bool(int(value))
    except (ValueError, TypeError):
        pass
    return value in {"1", "true", "yes", "on", "enable", "enabled"}

STREAM_OUTPUT = get_bool_env("STREAM_OUTPUT_IMAGES", True)
SERVICE_TYPE = os.environ.get("DOCKER_IMAGE_TYPE", "comfyui").lower().strip()
worker_name = f"runpod-worker-{SERVICE_TYPE}"

if get_bool_env("DEBUG", False):
    print(f"{worker_name} - DEBUG is enabled")
    try:
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
    except:
        print(f"{worker_name} - Debug init failed -- probably already listening.")
        pass

assert SERVICE_TYPE in ("comfyui", "deforum", "a1111"), f"Internal error -- unknown service type: {SERVICE_TYPE}"

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
    "a1111": os.environ.get("WEBUI_HOST", "127.0.0.1:17860"),
}[SERVICE_TYPE]
# Enforce a clean state after each job is done
# see https://docs.runpod.io/docs/handler-additional-controls#refresh-worker
REFRESH_WORKER = get_bool_env("REFRESH_WORKER", False)

SAVE_TO_S3 = get_bool_env("SAVE_TO_S3", False)
if SAVE_TO_S3:
    print("SAVE_TO_S3 is enabled, loading AWS credentials...")
    AWS_REGION = os.getenv("AWS_REGION")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
    assert AWS_REGION is not None, "AWS_REGION must be set"
    assert AWS_ACCESS_KEY_ID is not None, "AWS_ACCESS_KEY_ID must be set"
    assert AWS_SECRET_ACCESS_KEY is not None, "AWS_SECRET_ACCESS_KEY must be set"
    assert AWS_S3_BUCKET is not None, "AWS_S3_BUCKET must be set"

def construct_output_path_stub(deforum_status_json):
    """
    Construct the output path stub for the Deform job based on the status JSON.

    Before the execution starts, the output path is unknown. Once the job starts, the output path is determined. However. When `batch_name` is set in the input json, the `outdir` is that (sanitized). If it is not set, it is called `Deforum_{timestring}`. Regardless, the output files' paths all begin with `{outdir}/{timestring}`. We call this the path stub. This function reconstructs the output path stub from the output directory `outdir` and the job timestamp `timestring`.

    Args:
        deforum_status_json (dict): The status JSON of the Deform job.
    Returns:
        str: The constructed output path stub, or None if it couldn't yet be constructed.
    """
    output_directory_absolute_path = deforum_status_json.get("outdir")
    timestring = deforum_status_json.get("timestring")
    output_path_stub = f"{output_directory_absolute_path}/{timestring}" if output_directory_absolute_path and timestring else None
    return output_path_stub

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

    metadata = job_input.get("metadata", {})
    if not isinstance(metadata, dict):
        return None, "'metadata' must be a dictionary"
    if "user" in metadata:
        if not isinstance(metadata["user"], str):
            return None, "'metadata.user' must be a string"

    # Return validated data and no error
    return {"workflow": workflow, "images": images, "metadata": metadata}, None


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
    if get_bool_env("DEBUG_NO_CHECK_SERVER", False):
        print(f"{worker_name} - Will skip server check because DEBUG_NO_CHECK_SERVER is enabled")
        return True

    for i in range(retries):
        try:
            response = requests.get(url)

            # If the response status code is 200, the server is up and running
            if response.status_code == 200:
                print(f"{worker_name} - API is reachable")
                if SERVICE_TYPE in ["a1111", "deforum"]:
                    if not "crash_workaround_done" in locals():
                        print(f"{worker_name} - API is reachable, but checking again to work around a crash bug")
                        crash_workaround_done = True
                        time.sleep(5)
                        continue
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


def cancel_job(job_id: str) -> None:
    """
    Cancel a job with the given job ID.

    Args:
        job_id (str): The ID of the job to cancel.
    Raiises:
        NotImplementedError: If the cancel job functionality is not implemented for the current service type.
    """
    if SERVICE_TYPE == "deforum":
        api_url = f"http://{SERVER_HOST}/deforum_api/jobs/{job_id}"
        req = urllib.request.Request(api_url, method="DELETE")
    elif SERVICE_TYPE == "comfyui":
        # The server-side code we're coding against is here: https://github.com/comfyanonymous/ComfyUI/blob/1cd6cd608086a8ff8789b747b8d4f8b9273e576e/server.py#L662
        api_url = f"http://{SERVER_HOST}/queue"
        data = json.dumps({"delete": [job_id]}).encode("utf-8")
        req = urllib.request.Request(api_url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    else:
        raise NotImplementedError(f"Cancel job not implemented for service type: {SERVICE_TYPE}")

    try:
        res = urllib.request.urlopen(req)
        ret_data = json.loads(res.read())
        print(f"{worker_name} - Successfully cancelled {SERVICE_TYPE} job {job_id}: {ret_data}")
    except urllib.error.HTTPError as e:
        print(f"{worker_name} - Warning - Failed to cancel {SERVICE_TYPE} job {job_id} -- {e.__class__.__name__}: {e}")

def queue_workflow(workflow):
    """
    Queue a workflow to be processed by ComfyUI

    Args:
        workflow (dict): A dictionary containing the workflow to be processed

    Returns:
        dict: The JSON response from ComfyUI after processing the workflow
        LastLog: object that encapsulates the string representation of the log messages associated with the workflow
    """

    lastlog = LastLog(service_type=SERVICE_TYPE) # Instantiate before the server starts logging, because we use timestamps to deconflict which log messages are ours

    if SERVICE_TYPE == "comfyui":
        # The top level element "prompt" is required by ComfyUI
        data = json.dumps({"prompt": workflow}).encode("utf-8")
        api_url = f"http://{SERVER_HOST}/prompt"
    elif SERVICE_TYPE == "deforum":
        data = json.dumps(workflow).encode("utf-8")
        api_url = f"http://{SERVER_HOST}/deforum_api/batches"
    elif SERVICE_TYPE == "a1111":
        data = json.dumps(workflow).encode("utf-8")
        api_url = f"http://{SERVER_HOST}/sdapi/v1/txt2img"
    else:
        raise ValueError("Invalid SERVICE_TYPE")
    req = urllib.request.Request(api_url, data=data)
    req.add_header("Content-Type", "application/json")
    try:
        res = urllib.request.urlopen(req)
        return lastlog, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return None, {"error": str(e), "error_response": e.read().decode('utf-8'), "response": res.read() if 'res' in locals() else None, "workflow": workflow, "api_url": api_url}

def get_a1111_job_status(job_id):
    """
    The A1111 API is synchronous, so we don't need to poll for job status
    """
    raise NotImplementedError("A1111 API is synchronous, you should not be using this method [get_a1111_job_status()] for A1111")

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


def image_to_data_url(img_path):
    """
    Returns data: URL representation of an image

    Args:
        img_path (str): The path to the image

    Returns:
        str: The image encoded as data: URL
    """
    with open(img_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        mime_type = guess_mime_type(img_path)
        url = f"data:{mime_type};base64,{encoded_string}"
        return url

def is_video(file_path: str) -> bool:
    """
    Check if a file is a video

    Args:
        file_path (str): The path to the file

    Returns:
        bool: True if the file is a video, False otherwise
    """
    VIDEO_EXTENSIONS = [".mp4", ".webm"]
    return any(file_path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS)

class UnsafeInputError(Exception):
    pass

def fs_safe(s: str, raise_: bool = False) -> str:
    """
    Make a string safe for use in a filesystem

    Args:
        s (str): The string to make safe
    
    Returns:
        str: The safe string
    """
    ss = re.sub(r'[^\w\s-]', '_', s).strip()
    if len(ss) > 255:
        ss = ss[:255]
    while ss.endswith("_"):
        ss = ss[:-1]
    while ss.startswith("_"):
        ss = ss[1:]
    if len(ss) < 1:
        ss = "__empty__"
    if s != ss:
        if raise_:
            raise UnsafeInputError(f"String {s} was sanitized to {ss}")
        else:
            print(f"Warning: string {s} was sanitized to {ss}")
    return ss

def rp_upload_image(job_id: str, local_image_path: str, metadata: dict = {}, store_metadata: bool = False) -> str:
    """
    Save in S3.

    Args:
        job_id (str): The ID of the job
        local_image_path (str): The path to the image
        metadata (dict): We use this to construct the path-like prefix for the S3 object's key. The metadata should contain the user's name. If the metadata does not contain the user's name, we default to "no_user".

    We use the following folder structure:
    
    Root
    └── users
        └── marius
            └── output
                ├── 1111-deforum
                │   └── generating-image-sequence
                ├── automatic1111
                │   └── generating-image
                └── comfyui
                    ├── generating-image
                    └── generating-video
    
    Each job is saved in its own folder which is the timestamp of the job.

    We use the RunPod SDK's S3 upload function, because we are masochists, love bad library code, becuase the fine developers at RunPod use some nice optimalisations, and most importantly because their version is tested so that the quirks of boto3 and the quirks of RunPod play together nicely -- which we cannot otherwise guarantee. Having said that, their code looks like someone took a shell script fragment, and without any thinking implemented it in Python, which is probably exactly what happened.
    """
    def my_upload_file_to_bucket(*args, **kwargs):
        """
        Wrapper around the original upload_file_to_bucket to temporarily disable tqdm updates.

        Why?
        - The original implementation incorrectly updates `tqdm` with absolute byte counts instead
        of incremental differences.
        - Instead of refactoring the function, we monkey-patch `tqdm.update` to be a no-op just
        during the execution of `upload_file_to_bucket`.
        - This ensures that the function runs without issues, while preserving tqdm's normal behavior
        for any other part of the application.

        The original tqdm behavior is restored immediately after the function call.
        """
        file_name = args[0] if len(args) > 0 else kwargs.get("file_name", "[no file provided]")
        print(f"{worker_name} - Uploading {file_name} to S3 - Warning: uploading with TQDM disabled, to work around a bug in the RunPod SDK")
        original_update = tqdm.tqdm.update  # Save original tqdm update method
        tqdm.tqdm.update = lambda *_, **__: None  # Disable tqdm updates

        try:
            return rp_upload.upload_file_to_bucket(*args, **kwargs)  # Call the original function
        finally:
            tqdm.tqdm.update = original_update  # Restore tqdm after execution

    try:
        user = metadata["user"]
    except:
        user = "no_user"
    TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S" # 2024-12-24-17-45-33
    timestamp = JobTimestamp.get_timestamp(job_id).strftime(TIMESTAMP_FORMAT)

    # Ideally the sanitization is a no-op. The helper function prints a warning if the sanitization is not a no-op.
    path_within_bucket = f"""users/{fs_safe(user)}/output/{
                                {
                                    "comfyui": f"comfyui/generating-{'video' if is_video(local_image_path) else 'image'}",
                                    "deforum": "1111-deforum/generating-image-sequence",
                                    "a1111": "automatic1111/generating-image",
                                }[SERVICE_TYPE]
                            }/{fs_safe(timestamp)}"""

    # Cf. https://github.com/runpod/runpod-python/blob/main/docs/serverless/utils/rp_upload.md#bucket-credentials
    aws_credentials = {
        "endpointUrl": f"https://s3.{AWS_REGION}.amazonaws.com",
        "accessId": AWS_ACCESS_KEY_ID,
        "accessSecret": AWS_SECRET_ACCESS_KEY,
    }

    # This method is simply wrong, so we monkeypatch it in the simplest way possible
    rp_upload.extract_region_from_url = lambda url: AWS_REGION

    # We are getting reports that the images are only partially uploaded.
    url = my_upload_file_to_bucket(
        file_name=os.path.basename(local_image_path),
        file_location=local_image_path,
        bucket_creds=aws_credentials,
        bucket_name=AWS_S3_BUCKET,
        prefix=path_within_bucket,
        extra_args={
            "ContentType": guess_mime_type(local_image_path),
            **({"Metadata": metadata} if store_metadata else {})
        },
    )
    return url

def upload_png_to_s3(job_id: str, png_data: str, metadata: dict) -> str:
    """
    Upload a PNG image to an S3 bucket

    Args:
        job_id (str): The unique identifier for the job
        png_data (str): base64-encoded PNG image data

    Returns:
        str: The URL to the uploaded image in the S3 bucket
    """
    bytes = base64.b64decode(png_data)
    with NamedTemporaryFile(mode="wb", suffix=".png") as temp_file:
        temp_file.write(bytes)
        temp_file.flush()
        # Upload the PNG file to the S3 bucket
        return rp_upload_image(job_id, temp_file.name, metadata)

if get_bool_env("SAVE_TO_S3", False):
    s3_url_cache = {}
def process_output_images(outputs, job_id, metadata):
    """
    This function takes the "outputs" from image generation and the job ID,
    then determines the correct way to return the image, either as a direct URL
    to an AWS S3 bucket or as a base64 encoded string, depending on the
    environment configuration.

    Args:
        outputs (dict): A dictionary containing the outputs from image generation,
                        typically includes node IDs and their respective output data.
                        (for comfyui)
        outputs (str): File path stub of the generated images & videos. (for deforum)
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
      SAVE_TO_S3 environment variable.
    - If it is set and is truthy, it uploads the image to the bucket and returns the URL.
    - If it is is falsy or unset, it encodes the image in base64 and returns a data: URL.
    - If the image file does not exist in the output folder, it returns an error status
      with a message indicating the missing image file.
    """
    class ImageOutputError(Exception):
        pass

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
        assert type(outputs) is str, "outputs must be a string when SERVICE_TYPE is deforum"
        # the `outputs` output path stub looks like "/runpod-volume/stable-diffusion-webui/outputs/img2img-images/Deforum_foobar/20241204213940"
        # so we have to do the equivalent of "/runpod-volume/stable-diffusion-webui/outputs/img2img-images/Deforum_foobar/20241204213940"* to get all the images' paths
        print("DEBUG: outputs: ", outputs, "SERVICE_TYPE:", SERVICE_TYPE)
        output_images = [f for f in glob.glob(f"{outputs}*") if os.path.isfile(f)]
        # exclude .mp4 files and .txt files
        output_images = [f for f in output_images if not f.endswith(".mp4") and not f.endswith(".txt")]
        output_images.sort(key=lambda x: os.path.basename(x))

    elif SERVICE_TYPE == "a1111":
        raise InternalServerError("A1111 is synchronous, you should not be using this method [process_output_images()] for A1111")

    print(f"{worker_name} - gathering output images")

    try:
        encoded_output_images = []
        for local_image_path in output_images:
            print(f"{worker_name} - {local_image_path}")

            # The image is in the output folder
            if os.path.exists(local_image_path):
                base_name = os.path.basename(local_image_path)
                if get_bool_env("SAVE_TO_S3", False):
                    # URL to image in AWS S3
                    # Most of the time, the image has previously been already processed
                    if local_image_path in s3_url_cache:
                        url = s3_url_cache[local_image_path]
                    else:
                        url = rp_upload_image(job_id, local_image_path, metadata)
                        s3_url_cache[local_image_path] = url
                        print(
                            f"{worker_name} - the image {base_name} was generated and uploaded to AWS S3: {url}"
                        )
                else:
                    # data: URL
                    url = image_to_data_url(local_image_path)
                    print(
                        f"{worker_name} - the image {base_name} was generated and converted to data URL: {url[:40]+'...' if len(url)>42 else url}"
                    )
                encoded_output_images.append({
                    "name": base_name,
                    "url": url
                })
        if encoded_output_images:
            print(f"{worker_name} - Success: sending image{'s' if len(encoded_output_images)>1 else ''}: {[f['name'] for f in encoded_output_images]}")
            ret = {
                "status": "success",
                "images": encoded_output_images,
                **({"outputs": all_outputs} if "all_outputs" in locals() else {}),
            }
            return ret
        else:
            raise ImageOutputError(f"Images generated, but none exist in the output folder: {output_images}" if output_images else "No images generated")
    except Exception as e:
        print(f"{worker_name} - Error -- {e.__class__.__name__}: {e}")
        ret = {
            "status": "error",
            "error": f"{e.__class__.__name__}: {str(e)}",
            **({"outputs": all_outputs} if "all_outputs" in locals() else {}),
        }
        return ret

class OutputStreamer:
    def __init__(self, output_files_path_stub, job_id, metadata):
        self.output_files_path_stub = output_files_path_stub
        self.job_id = job_id
        self.metadata = metadata
        self.output_images = {}
        self.output_images_lock = threading.Lock()

    def get_new_images(self):
        """
        This is a very ingenious wrapper around process_output_images() that yields any new images as they are generated.
        """
        try:
            images_result = process_output_images(self.output_files_path_stub, self.job_id, self.metadata)
            if images_result["status"] == "success":
                for image in images_result["images"]:
                    with self.output_images_lock:
                        if image["name"] not in self.output_images:
                            self.output_images[image["name"]] = image
                            yield image
        except Exception as e:
            print(f"{worker_name} - Error streaming output for job {self.job_id} in directory {self.output_files_path_stub}: {e}")
    
    def get_all_images(self):
        """
        Return any previously returned images, plus any new images that have been generated since the last call to get_new_images().
        """
        for _ in self.get_new_images():
            pass
        with self.output_images_lock:
            return [self.output_images[image_name] for image_name in self.output_images]

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
    print("handler()", job)
    try:
        timestamp = JobTimestamp.start_job()
        job_input = job["input"]
        runpod_job_id = job.get("id")

        raise_for_cancel(runpod_job_id)

        # Make sure that the input is valid
        validated_data, error_message = validate_input(job_input)
        if error_message:
            yield {"error": error_message}
            return

        # Extract validated data
        workflow = validated_data["workflow"]
        images = validated_data.get("images")
        metadata = validated_data.get("metadata")

        # Make sure that the ComfyUI API is available
        check_server(
            # Note we use the deforum API endpoint's existence as a proxy for the webui being up and not having crashed on startup (it gets reloaded on crash, but if we just check the normal API endpoint, we often catch it while it still has not crashed yet)
            f"http://{SERVER_HOST}" + ("/deforum_api/jobs" if SERVICE_TYPE in ["deforum", "a1111"] else ""),
            SERVER_API_AVAILABLE_MAX_RETRIES,
            SERVER_API_AVAILABLE_INTERVAL_MS,
        )

        # Upload images if they exist
        upload_result = upload_images(images)

        if upload_result["status"] == "error":
            yield upload_result
            return

        # Queue the workflow
        lastlog, queued_workflow = None, None
        try:
            lastlog, queued_workflow = queue_workflow(workflow)
            if SERVICE_TYPE == "comfyui":
                job_id = queued_workflow["prompt_id"]
                timestamp.set_job_id(job_id)
            elif SERVICE_TYPE == "deforum":
                if "error" in queued_workflow:
                    print(f"{worker_name} - Error: queued_workflow is already the error response:", queued_workflow)
                    yield queued_workflow
                    return
                job_id = queued_workflow["job_ids"][0]
                timestamp.set_job_id(job_id)
            elif SERVICE_TYPE == "a1111":
                # The sdapi API is synchronous, so we just return the result here straight away

                # Get the logging out of the way, we will not come back to it later
                time.sleep(1) # allow log to be written to disk
                runpod.serverless.progress_update(job, {'log': lastlog.get_log(last_only=False)}) 
                yield {"log": str(lastlog)}
                
                result = queued_workflow
                if "error" in result:
                    print(f"{worker_name} - Error running txt2image: {result['error']}")
                    yield {**result}
                try:
                    # SDAPI does not give us image names, only image data
                    images = []
                    for i, base64_encoded_png_data in enumerate(result["images"]):
                        fake_job_id = uuid.uuid4().hex # This serves as the unique path within the S3 bucket, so it must be something random
                        timestamp.set_job_id(fake_job_id, is_fake=True)
                        url = upload_png_to_s3(fake_job_id, base64_encoded_png_data, metadata) if SAVE_TO_S3 else f"data:image/png;base64,{base64_encoded_png_data}"
                        assert url.startswith("https:") or url.startswith("data:"), f"Invalid URL: {url}"
                        images.append({
                            "name": f"image_{i:04d}.png",
                            "url": url,
                        })
                    if not images:
                        raise ValueError("No images generated")
                except Exception as e:
                    yield {"error": f"Error processing output images -- {e.__class__.__name__}: {str(e)}"}
                yield {"status": "success", "images": images}
                return
            print(f"{worker_name} - queued workflow with ID {job_id}")
        except Exception as e:
            traceback_str = traceback.format_exc()
            yield {"error": f"Error queuing workflow -- {e.__class__.__name__}: {str(e)}", "traceback": traceback_str, "workflow": workflow, "queued_workflow": queued_workflow}
            return

        # Poll for completion
        print(f"{worker_name} - wait until image generation is complete")
        retries = 0
        images_result = {}
        try:
            while retries < SERVER_POLLING_MAX_RETRIES:
                runpod.serverless.progress_update(job, {'log': lastlog.get_log(last_only=False)})
                raise_for_cancel(runpod_job_id)
                if SERVICE_TYPE == "comfyui":
                    history = get_comfyui_history(job_id)

                    # Exit the loop if we have found the history or encountered an error
                    if job_id in history and history[job_id].get("outputs"):
                        images_result = process_output_images(history[job_id].get("outputs"), job_id, metadata)
                        break
                    else:
                        try:
                            if history[job_id]["status"]["status_str"] in ["error"]:
                                yield {"error": "Image generation failed -- ComfyUI workflow failed unexpectedly", "full_response": history[job_id]}
                                return
                        except:
                            pass
                elif SERVICE_TYPE == "deforum":
                    job_status = get_deforum_job_status(job_id)
                    output_path_stub = construct_output_path_stub(job_status)
                    try:
                        __index__ += 1
                    except NameError:
                        __index__ = 0
                    with open(f"/tmp/{job_id}_status{__index__:06d}.json", "w") as f:
                        f.write(json.dumps(job_status, indent=4))
                        print(f"DEBUG: job status saved to {f.name}")
                    if job_status["status"] == "FAILED":
                        yield {"error": "Image generation failed", "full_response": job_status}
                        return
                    elif job_status["status"] == "SUCCEEDED":
                        if "output_streamer" in locals():
                            images = output_streamer.get_all_images()
                            images_result = { **({"images": images} if images else {}), "streamed": True }
                        else:
                            assert output_path_stub, "Output directory not found even tough job is SUCCEEDED"
                            images_result = process_output_images(output_path_stub, job_id, metadata)
                        break
                    elif STREAM_OUTPUT:
                        stream_res = {}
                        try:
                            if "output_streamer" not in locals():
                                if not output_path_stub:
                                    # The output directory does not exist yet, this is expected while the job has not been started in earnest
                                    raise ValueError("Output directory not found")
                                output_streamer = OutputStreamer(output_path_stub, job_id, metadata)
                            images = [image for image in output_streamer.get_new_images()]
                            if images:
                                stream_res = { "images": images }
                        except Exception as e:
                            pass
                        log = str(lastlog)
                        # Do not spam empty updates
                        if log or stream_res:
                            yield {"log": log, **stream_res}
                    # break
                elif SERVICE_TYPE == "a1111":
                    raise InternalServerError("A1111 is synchronous, we should not be polling for job status, yet somehow we are?")
                else:
                    raise ValueError("Invalid SERVICE_TYPE")
                # Wait before trying again
                time.sleep(SERVER_POLLING_INTERVAL_MS / 1000)
                retries += 1
            else:
                yield {"error": "Max retries reached while waiting for image generation"}
                return
        except JobCancelledException as e:
            raise e
        except Exception as e:
            yield {"error": f"Error waiting for image generation: {str(e)}"}
            return
        # Get the generated image and return it as URL in an AWS bucket or as base64
        result = {**images_result, "refresh_worker": REFRESH_WORKER}
    except JobCancelledException as e:
        if "job_id" in locals():
            cancel_job(job_id) if SERVICE_TYPE in ["comfyui", "deforum"] else None
        result = {"status": "cancelled", "message": f"Cancelled by user - {e}"}
    except Exception as e:
        # stringify and jsonify the trackback
        traceback_str = traceback.format_exc()
        result = {"error": f"Error: {e.__class__.__name__}: {str(e)}", "traceback": traceback_str}
    finally:
        # Clean up
        try:
            s3_url_cache.pop(job_id, None)
        except:
            pass
        # TODO clean up the respective output directories
    print(f"{worker_name} - Done - {result}")
    yield result
    return {"status": result["status"] if "status" in result else "done"} # XXX the yield ought to be enough, why are we returning this?

def init_server():
    """
    Initialize the server by running either:
      1. an empty job
      2. or, if present, all jobs (alphabetically) found in /workspace/worker-warmup/{SERVICE_TYPE}/*.json
    """
    def run_job(job):
        print(f"{worker_name} - Running warm-up job {job} -- because it is a warm-up job, errors will be ignored...")
        try:
            for output in handler(job):
                print("...", output)
        except Exception as e:
            print(f"... caught exception: {e.__class__.__name__}: {e}")

    warmup_dir = f"/workspace/worker-warmup/{SERVICE_TYPE}"
    jobs_to_run = []
    
    # Check if the directory exists and has job files
    if os.path.isdir(warmup_dir):
        jobs = sorted(glob.glob(os.path.join(warmup_dir, "*.json")))
        if jobs:
            print(f"{worker_name} - Initializing server {SERVICE_TYPE} by running {len(jobs)} jobs...")
            for job_file in jobs:
                try:
                    with open(job_file, "r") as f:
                        jobs_to_run.append(json.load(f))
                except Exception as e:
                    print(f"... error processing {job_file}: {e.__class__.__name__}: {e}")
    else:
        print(f"{worker_name} - Warm-up directory {warmup_dir} not found.")

    # If no valid jobs were found, add the dummy job
    if not jobs_to_run:
        print(f"{worker_name} - Using dummy workflow for initialization.")
        jobs_to_run.append({"input": {"workflow": {}}})

    # Run all gathered jobs
    for job in jobs_to_run:
        run_job(job)

    print(f"{worker_name} - Server {SERVICE_TYPE} initialized successfully.")

# Start the handler only if this script is run directly
if __name__ == "__main__":
    init_server()
    runpod.serverless.start({"handler": handler, "return_aggregate_stream": True})

