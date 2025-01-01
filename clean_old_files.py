import os
import subprocess

def clean_old_files(dirs=None):
    """
    Iterates through directories,and removes files older than 7 days, returning a comprehensive dictionary report.
    """
    if not dirs:
        print("Nothing to clean: directory list is empty.")
        return {"status": "error", "error": "Directory list is not set or empty.", "details": {}}

    overall_status = "success"
    overall_error = None
    details = {}

    for dir_path in dirs:
        dir_report = {"status": "", "cleaned_paths": [], "error": None}
        try:
            # Change to the directory
            os.chdir(dir_path)

            # Use find command to list files older than 7 days
            command = ["find", ".", "-type", "f", "-mtime", "+7", "-print0"]
            result = subprocess.run(command, stdout=subprocess.PIPE, check=True, text=True)

            files_to_delete = result.stdout.split("\0")[:-1]  # Split by null terminator and remove the last empty entry
            dir_report["cleaned_paths"] = [os.path.abspath(file) for file in files_to_delete]

            # Remove the files
            for file in files_to_delete:
                os.remove(file)

            dir_report["status"] = "success"
            print(f"Cleaned files older than 7 days in: {dir_path}")
        except FileNotFoundError:
            dir_report["status"] = "error"
            dir_report["error"] = f"Directory not found: {dir_path}"
            overall_status = "error"
            print(f"Directory not found: {dir_path}")
        except subprocess.CalledProcessError as e:
            dir_report["status"] = "error"
            dir_report["error"] = str(e)
            overall_status = "error"
            print(f"Error processing directory {dir_path}: {e}")
        except Exception as e:
            dir_report["status"] = "error"
            dir_report["error"] = str(e)
            overall_status = "error"
            print(f"Unexpected error with directory {dir_path}: {e}")

        details[dir_path] = dir_report

    return {"status": overall_status, "error": overall_error, "details": details}

# Example usage
# To set RM_RF_DIRS, use the following syntax in your dashboard or environment setup:
# export RM_RF_DIRS="/path/to/dir1:/path/to/dir2:/path/to/dir3"

if __name__ == "__main__":
    import json
    import os
    dirs = os.environ.get("RM_RF_DIRS", "").split(":")
    cleaned_files_report = clean_old_files(dirs)
    print("Cleaned files report:", json.dumps(cleaned_files_report, indent=2))
