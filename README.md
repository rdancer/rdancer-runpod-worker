### **rdancer-utility-worker**

Docker image for [`rdancer/rdancer-utility-worker:latest`](https://hub.docker.com/repository/docker/rdancer/rdancer-utility-worker/general)

This repository contains a minimal worker designed to run on RunPod using Docker. The worker handles cancellation tasks communicated via the file system and periodically cleans up old files.

---

### **Features**
- Processes `cancel` commands by creating a file for the job ID in `/workspace/tasks/cancel/ids/`.
- Cleans up files older than 1 day to maintain an organized environment.
- Lightweight and efficient, with minimal dependencies.
- Includes a script to ensure the workspace is mounted correctly.

---

### **Directory Structure**
```
.
├── Dockerfile            # Docker image definition
├── docker-compose.yml    # Compose file for local testing
├── rp_handler.py         # Worker logic
├── requirements.txt      # Python dependencies
├── start.sh              # Startup script for the worker
└── README.md             # Documentation
```

---

### **Usage**

1. (optional) `docker compose build && docker compose push`
2. Create a new worker on Runpod with the image `rdancer/rdancer-utility-worker:latest`.
3. Send a `cancel` command:
```bash
UTILITY_WORKER_ID=your_worker_id # get it from the RunPod console
JOB_ID=example_job_id_12345 # replace with your job ID

cat <<EOF > ./cancel.json
{
    "input": {
        "task": {
            "command": "cancel",
            "args": [
                "${JOB_ID}"
            ]
        }
    }
}
EOF

curl -X POST \
     -H "Content-Type: application/json" \
     -d @cancel.json \
     https://api.runpod.ai/v2/${UTILITY_WORKER_ID}/run

{"status": "cancelled", "job_id": example_job_id_12345}
```

### **Configuration**

- **Environment Variables**:
  - `PYTHONUNBUFFERED=1`: Ensures logs are not buffered.

- **Volumes**:
  - We use the filesystem under `/workspace` to communicate the cancelled jobs. The worker pauses during initialization, and waits for the network-attached volume to be mounted on `/workspace` -- if you forget to mount the volume in Runpod configuration, the worker will get stuck. 

---

### **File Details**

#### **rp_handler.py**
Handles the main logic:
- Processes `cancel` commands.
- Cleans up old files in `/workspace/tasks/cancel/ids/`.

#### **start.sh**
Startup script:
- Waits for the `/workspace` volume to be available.
- Configures memory management using `libtcmalloc` if available.
- Starts the RunPod worker.

#### **Dockerfile**
- Based on `python:3.11-slim` for a small footprint.
- Installs dependencies from `requirements.txt`.

#### **docker-compose.yml**
- Defines the service for local testing and development.

---

### **License**
This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for more information.

---

### **Contributing**
Feel free to submit issues or PRs to improve the worker functionality or documentation.
