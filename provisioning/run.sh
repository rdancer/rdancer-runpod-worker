#!/bin/bash
# provisioning/run.sh -- run before /run.sh (a hack)
#
# Run this script before startup using the PROVISIONING_SCRIPT environmental variable:
# My Pods >> click on pod >> hamburger menu >> Edit Pod >> ...
# Storage >> Deploy >> [select machine type >> change template >> ComfyUI - AI-Dock] >> Edit Template >> ...
# ... Environment Variables >> PROVISIONING_SCRIPT = https://raw.githubusercontent.com/rdancer/runpod-worker-comfy-actual/master/provisioning/run.sh

# Knock out *Storage Monitor*
#
# Why we do this:
#
# The Ai-Dock has a very clever-by-half system of handling model weights. We use a different system, and so switch the Storage Monitor off.
#
# Unfortunately, the Storage Monitor is hard-coded, and there is no way to switch it off using variable names or files in /workspace. We have tried making /workspace/storage read-only, but this only crashed the boot-up process and corrupted the volume(?)
#
# The call stack of the Storage Monitor looks like this:
# # ps auxf
# ...
# root          19  0.0  0.0  15368  8192 ?        S    Nov29   0:00 /bin/bash /opt/ai-dock/bin/init.sh
# root         538  0.0  0.0  39924 26624 ?        S    Nov29   0:07  \_ /usr/bin/python3 /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
# user         553  0.0  0.0  10496  3328 ?        S    Nov29   0:00      \_ /bin/bash /opt/ai-dock/bin/supervisor-storagemonitor.sh
# user         559  0.0  0.0  10496  2816 ?        S    Nov29   0:00      |   \_ /bin/bash /opt/ai-dock/storage_monitor/bin/storage-monitor.sh
# user         782  0.0  0.0   3264  1792 ?        S    Nov29   0:00      |       \_ inotifywait -m -r -e create -e delete -e move --format %e %w%f /workspace/storage
# user         783  0.0  0.0  10496  1540 ?        S    Nov29   0:00      |       \_ /bin/bash /opt/ai-dock/storage_monitor/bin/storage-monitor.sh
# ...
#
# There are 3 plausible ways to neuter the startup sequence:
#
# 1. Set `autostart=false` in /etc/supervisor/supervisord.conf
# 2. Overwrite /opt/ai-dock/bin/supervisor-storagemonitor.sh <-- this is what we do
# 3. Overwrite /opt/ai-dock/storage_monitor/bin/storage-monitor.sh

SCRIPT_PATH=/opt/ai-dock/bin/supervisor-storagemonitor.sh
echo -n "Neutering Storage Monitor: $SCRIPT_PATH..."
echo '#!/usr/bin/sleep infinity' > "$SCRIPT_PATH"
echo done.
