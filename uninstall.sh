#!/usr/bin/env bash
# uninstall.sh
# MatrixMouse uninstall script
#
# Run as your normal user — NOT with sudo.
# Prompts before each destructive step.
# Secrets and workspace are NEVER deleted without explicit double-confirmation.
#
# Usage:
#   chmod +x uninstall.sh
#   ./uninstall.sh

set -euo pipefail

if [ "$EUID" -eq 0 ]; then
    echo "ERROR: Do not run this script with sudo or as root."
    echo "Run as your normal user — the script will sudo when needed."
    exit 1
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
header()  { echo -e "\n${BOLD}── $* ──${RESET}"; }

confirm() {
    local answer
    read -rp "$(echo -e "${CYAN}?${RESET} $1 [y/N]: ")" answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

confirm_danger() {
    local answer
    echo -e "${RED}WARNING: $1${RESET}"
    read -rp "Type 'yes' to confirm: " answer
    [[ "$answer" == "yes" ]]
}

HAS_SYSTEMD=false
command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1 && HAS_SYSTEMD=true

MM_USER="matrixmouse"
ETC_DIR="/etc/matrixmouse"
SECRETS_DIR="$ETC_DIR/secrets"
DEFAULT_WORKSPACE="/var/lib/matrixmouse-workspace"

echo ""
echo -e "${BOLD}MatrixMouse Uninstaller${RESET}"
echo ""
echo "Prompts before each step. Workspace and secrets kept unless"
echo "you explicitly confirm their deletion."
echo ""

confirm "Proceed with uninstall?" || { echo "Aborted."; exit 0; }

# ---------------------------------------------------------------------------
# Step 1 — Stop and remove systemd services
# ---------------------------------------------------------------------------

header "Step 1 — systemd services"

if $HAS_SYSTEMD; then
    for svc in matrixmouse matrixmouse-test-runner; do
        SVC_FILE="/etc/systemd/system/${svc}.service"
        if [ -f "$SVC_FILE" ]; then
            if confirm "Remove $svc service?"; then
                sudo systemctl stop    "$svc" 2>/dev/null || true
                sudo systemctl disable "$svc" 2>/dev/null || true
                sudo rm -f "$SVC_FILE"
                success "Removed $svc.service"
            fi
        else
            info "$svc.service not found — skipping"
        fi
    done
    sudo systemctl daemon-reload 2>/dev/null || true
else
    info "systemd not available — no services to remove"
fi

# ---------------------------------------------------------------------------
# Step 2 — Ollama override
# ---------------------------------------------------------------------------

header "Step 2 — Ollama configuration"

OLLAMA_OVERRIDE="/etc/systemd/system/ollama.service.d/override.conf"
if [ -f "$OLLAMA_OVERRIDE" ]; then
    if confirm "Remove MatrixMouse Ollama override (OLLAMA_MAX_LOADED_MODELS)?"; then
        sudo rm -f "$OLLAMA_OVERRIDE"
        sudo rmdir /etc/systemd/system/ollama.service.d 2>/dev/null || true
        if $HAS_SYSTEMD; then
            sudo systemctl daemon-reload
            sudo systemctl restart ollama 2>/dev/null || true
        fi
        success "Ollama override removed"
    fi
else
    info "No Ollama override found — skipping"
fi

# ---------------------------------------------------------------------------
# Step 3 — Docker image 
# ---------------------------------------------------------------------------

header "Step 3 — Docker test runner"

if docker image inspect matrixmouse-test-runner &>/dev/null 2>&1; then
    if confirm "Remove matrixmouse-test-runner Docker image?"; then
        docker rmi matrixmouse-test-runner
        success "Docker image removed"
    fi
else
    info "matrixmouse-test-runner image not found — skipping"
fi

# ---------------------------------------------------------------------------
# Step 4 — Uninstall MatrixMouse package
# ---------------------------------------------------------------------------

header "Step 4 — MatrixMouse package"

if uv tool list 2>/dev/null | grep -q "matrixmouse"; then
    if confirm "Uninstall matrixmouse via uv?"; then
        uv tool uninstall matrixmouse
        success "matrixmouse package uninstalled"
    fi
else
    info "matrixmouse not found in uv tools — skipping"
fi

# ---------------------------------------------------------------------------
# Step 5 — System user
# ---------------------------------------------------------------------------

header "Step 5 — System user"

if id "$MM_USER" &>/dev/null; then
    if confirm "Remove system user '$MM_USER'?"; then
        sudo userdel "$MM_USER" 2>/dev/null || true
        success "System user '$MM_USER' removed"
    fi
else
    info "System user '$MM_USER' not found — skipping"
fi

if groups "$USER" 2>/dev/null | grep -qw "$MM_USER"; then
    if confirm "Remove $USER from the '$MM_USER' group?"; then
        sudo deluser "$USER" "$MM_USER" 2>/dev/null || \
        sudo gpasswd -d "$USER" "$MM_USER" 2>/dev/null || true
        success "Removed $USER from '$MM_USER' group"
        warn "Log out and back in for group change to take effect."
    fi
fi

# ---------------------------------------------------------------------------
# Step 6 — /etc/matrixmouse (config + secrets) — DANGEROUS
# ---------------------------------------------------------------------------

header "Step 6 — /etc/matrixmouse"

if [ -d "$ETC_DIR" ]; then
    echo ""
    echo "  $ETC_DIR contains:"
    echo "    config.toml, matrixmouse.env, SSH key, GitHub PAT"
    echo ""
    echo "  Keeping this directory lets you reinstall without re-entering credentials."
    echo ""
    if confirm_danger "Delete $ETC_DIR and ALL credentials inside?"; then
        sudo rm -rf "$ETC_DIR"
        success "Deleted $ETC_DIR"
    else
        info "Kept $ETC_DIR — credentials preserved for reinstall"
    fi
else
    info "$ETC_DIR not found — skipping"
fi

# ---------------------------------------------------------------------------
# Step 7 — Workspace — DANGEROUS
# ---------------------------------------------------------------------------

header "Step 7 — Workspace"

# Find workspace — try the default, fall back to env var
WORKSPACE_PATH="${WORKSPACE_PATH:-$DEFAULT_WORKSPACE}"
if [ -d "$WORKSPACE_PATH" ]; then
    echo ""
    echo "  Workspace: $WORKSPACE_PATH"
    echo "  Contains your cloned repos and all task history."
    echo ""
    if confirm_danger "Delete the entire workspace at $WORKSPACE_PATH?"; then
        sudo rm -rf "$WORKSPACE_PATH"
        success "Workspace deleted"
    else
        info "Workspace kept at $WORKSPACE_PATH"
    fi
else
    info "Workspace not found at $WORKSPACE_PATH — skipping"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

header "Uninstall complete"

echo ""
echo "MatrixMouse has been removed."
echo ""
echo "Intentionally preserved (if you declined above):"
echo "  $ETC_DIR   — credentials, ready for reinstall"
echo "  $WORKSPACE_PATH  — repos and task history"
echo "  ollama, docker   — not touched"
echo ""
