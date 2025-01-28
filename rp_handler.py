import os
import time
import runpod

CANCEL_DIR = "/workspace/tasks/cancel/ids"

def handler(event):
    command = event.get("task", {}).get("command")
    args = event.get("task", {}).get("args", [])

    if command == "cancel" and args:
        job_id = args[0]
        cancel_path = os.path.join(CANCEL_DIR, job_id)
        os.makedirs(CANCEL_DIR, exist_ok=True)
        with open(cancel_path, 'a'):
            os.utime(cancel_path, None)
        cleanup_old_files()
        return {"status": "cancelled", "job_id": job_id}
    else:
        return {"status": "error", "message": "Invalid command or arguments"}

def cleanup_old_files():
    now = time.time()
    cutoff = now - 86400  # 86400 seconds = 1 day

    if os.path.exists(CANCEL_DIR):
        for filename in os.listdir(CANCEL_DIR):
            file_path = os.path.join(CANCEL_DIR, filename)
            if os.path.isfile(file_path):
                file_mtime = os.path.getmtime(file_path)
                if file_mtime < cutoff:
                    os.remove(file_path)

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
