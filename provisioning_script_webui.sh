#!/bin/bash

set -ex

# Define paths
venv_path=/workspace/environments/python/webui
system_env_paths=(
    "/opt/environments/python/python_310"
    "/opt/environments/python/webui"
)
packages_path_fragment="lib/python3.10/site-packages"

# Step 1: Create the target virtual environment
echo "Creating virtual environment at $venv_path..."
mkdir -p "${venv_path%/*}" # Ensure parent directory exists
python -m venv "$venv_path"

# Step 2: Copy packages in reverse order of precedence
for env_path in "${system_env_paths[@]}"; do
    echo "Copying packages: $env_path/$packages_path_fragment -> $venv_path/$packages_path_fragment..."
    cp -r "$env_path/$packages_path_fragment"/* "$venv_path/$packages_path_fragment"
done

# Step 3: Clean up bytecode and caches (optional but recommended)
echo "Cleaning up .pyc files and __pycache__ directories..."
find "$venv_path/$packages_path_fragment" -name '*.pyc' -delete
find "$venv_path/$packages_path_fragment" -name '__pycache__' -exec rm -r {} +

# Step 4: Activate the virtual environment
echo "Activating the virtual environment..."
source "$venv_path/bin/activate"

# Step 5: Confirmation of setup
echo "Provisioning complete. Virtual environment is ready at $venv_path."
echo "PYTHONPATH: $PYTHONPATH"
which python
which pip

if [ -n "${UPSTREAM_PROVISIONING_SCRIPT:-}" ]; then
    echo "Running \$UPSTREAM_PROVISIONING_SCRIPT: $UPSTREAM_PROVISIONING_SCRIPT..."
    curl -sSL "$UPSTREAM_PROVISIONING_SCRIPT" | bash
else
    echo "\$UPSTREAM_PROVISIONING_SCRIPT not set, finishing up."
fi
