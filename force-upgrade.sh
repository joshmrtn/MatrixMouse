#!/bin/bash
# force-upgrade.sh
# Reinstall MatrixMouse from source and restart the service.
# For development use only.
# Not a full install! Run install.sh for the full installation.

sudo systemctl stop matrixmouse

SYSTEM_PYTHON="$(command -v python3.11)"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Reinstalling from $REPO_ROOT ..."


sudo UV_TOOL_DIR=/usr/local/share/uv/tools \
    uv tool install "$REPO_ROOT" \
    --python "$SYSTEM_PYTHON" \
    --force \
    --no-cache
sudo chmod -R a+rX /usr/local/share/uv/tools/matrixmouse/
sudo systemctl restart matrixmouse

echo "Done. Following logs (Ctrl+C to exit)..."
echo ""
journalctl -u matrixmouse -f
