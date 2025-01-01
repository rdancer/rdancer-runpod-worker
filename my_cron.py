from crontab import CronTab
import subprocess
import os

def run_cron_tasks(crontab_path="/workspace/etc/cron/crontab", ignore_scheduling=False):
    """
    Parses a crontab file and runs tasks defined in it.
    If ignore_scheduling is True, runs all tasks regardless of scheduling instructions.
    Returns a report of task execution.
    """
    if not os.path.exists(crontab_path):
        return {"status": "error", "error": f"Crontab file not found: {crontab_path}", "details": []}

    tasks_report = {"status": "success", "details": []}

    try:
        # Read the crontab file
        with open(crontab_path, "r") as crontab_file:
            cron = CronTab(tab=crontab_file.read())

        for job in cron:
            task_result = {"command": job.command, "status": "pending", "output": "", "error": ""}

            if ignore_scheduling or job.is_valid():
                try:
                    result = subprocess.run(
                        job.command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                    )
                    task_result["output"] = result.stdout
                    if result.returncode != 0:
                        task_result["status"] = "error"
                        task_result["error"] = result.stderr
                        tasks_report["status"] = "error"
                    else:
                        task_result["status"] = "success"
                except Exception as e:
                    task_result["status"] = "error"
                    task_result["error"] = str(e)
                    tasks_report["status"] = "error"
            else:
                task_result["status"] = "skipped"

            tasks_report["details"].append(task_result)

    except Exception as e:
        tasks_report["status"] = "error"
        tasks_report["error"] = str(e)

    return tasks_report

if __name__ == "__main__":
    report = run_cron_tasks(ignore_scheduling=False)
    print("Cron tasks report:", report)
