#!/usr/bin/env bash
# uninstall.sh
# MatrixMouse uninstall script
#
# Reverses everything install.sh does, in reverse order.
# Prompts before each destructive step.
# NEVER deletes the workspace or secrets without explicit confirmation.
#
# Usage:
#   chmod +x uninstall.sh
#   ./uninstall.sh

set -euo pipefail

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
    # Extra confirmation for destructive steps — requires typing "yes"
    local answer
    echo -e "${RED}WARNING: $1${RESET}"
    read -rp "Type 'yes' to confirm: " answer
    [[ "$answer" == "yes" ]]
}

HAS_SYSTEMD=false
command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1 && HAS_SYSTEMD=true

echo ""
echo -e "${BOLD}MatrixMouse Uninstaller${RESET}"
echo ""
echo "This script will remove the MatrixMouse installation."
echo "You will be asked before each step."
echo ""
echo -e "${YELLOW}Your workspace and secrets will NOT be deleted unless you"
echo -e "explicitly confirm those specific steps.${RESET}"
echo ""

if ! confirm "Proceed with uninstall?"; then
    echo "Aborted."
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1 — Stop and remove systemd services
# ---------------------------------------------------------------------------

header "Step 1 — systemd services"

if $HAS_SYSTEMD; then
    for svc in matrixmouse matrixmouse-test-runner; do
        SVC_FILE="/etc/systemd/system/${svc}.service"
        if [ -f "$SVC_FILE" ]; then
            if confirm "Remove $svc systemd service?"; then
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
    if confirm "Remove MatrixMouse's Ollama OLLAMA_MAX_LOADED_MODELS override?"; then
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
# Step 3 — Docker image and test runner
# ---------------------------------------------------------------------------

header "Step 3 — Docker test runner"

if docker image inspect matrixmouse-test-runner &>/dev/null 2>&1; then
    if confirm "Remove the matrixmouse-test-runner Docker image?"; then
        docker rmi matrixmouse-test-runner
        success "Docker image removed"
    fi
else
    info "matrixmouse-test-runner image not found — skipping"
fi

FIFO_DIR="/tmp/matrixmouse-pipes"
if [ -d "$FIFO_DIR" ]; then
    if confirm "Remove FIFO pipes at $FIFO_DIR?"; then
        rm -rf "$FIFO_DIR"
        success "FIFO directory removed"
    fi
fi

# ---------------------------------------------------------------------------
# Step 4 — Recorded image hash
# ---------------------------------------------------------------------------

header "Step 4 — Upgrade metadata"

HASH_FILE="$HOME/.config/matrixmouse/testrunner.image.sha256"
if [ -f "$HASH_FILE" ]; then
    if confirm "Remove test runner image hash at $HASH_FILE?"; then
        rm -f "$HASH_FILE"
        rmdir "$HOME/.config/matrixmouse" 2>/dev/null || true
        success "Image hash removed"
    fi
fi

# ---------------------------------------------------------------------------
# Step 5 — Uninstall MatrixMouse package
# ---------------------------------------------------------------------------

header "Step 5 — MatrixMouse package"

if uv tool list 2>/dev/null | grep -q "matrixmouse"; then
    if confirm "Uninstall the matrixmouse package via uv?"; then
        uv tool uninstall matrixmouse
        success "matrixmouse package uninstalled"
    fi
else
    info "matrixmouse not found in uv tools — skipping"
fi

# ---------------------------------------------------------------------------
# Step 6 — System user
# ---------------------------------------------------------------------------

header "Step 6 — System user"

MM_USER="matrixmouse"
if id "$MM_USER" &>/dev/null; then
    if confirm "Remove system user '$MM_USER'?"; then
        sudo userdel "$MM_USER" 2>/dev/null || true
        success "System user '$MM_USER' removed"
    fi
else
    info "System user '$MM_USER' not found — skipping"
fi

# Remove the current user from the matrixmouse group if they were added
if groups "$USER" 2>/dev/null | grep -q "$MM_USER"; then
    if confirm "Remove $USER from the '$MM_USER' group?"; then
        sudo deluser "$USER" "$MM_USER" 2>/dev/null || \
        sudo gpasswd -d "$USER" "$MM_USER" 2>/dev/null || true
        success "Removed $USER from '$MM_USER' group"
        warn "Log out and back in for group change to take effect."
    fi
fi

# ---------------------------------------------------------------------------
# Step 7 — Workspace (DANGEROUS — asks twice)
# ---------------------------------------------------------------------------

header "Step 7 — Workspace"

# Try to find workspace path from env or default
WORKSPACE_PATH="${WORKSPACE_PATH:-$HOME/matrixmouse-workspace}"
if [ -d "$WORKSPACE_PATH" ]; then
    echo ""
    echo "  Workspace: $WORKSPACE_PATH"
    echo "  This contains your cloned repos and all task history."
    echo ""
    if confirm_danger "Delete the entire workspace at $WORKSPACE_PATH?"; then
        rm -rf "$WORKSPACE_PATH"
        success "Workspace deleted: $WORKSPACE_PATH"
    else
        info "Workspace kept at $WORKSPACE_PATH"
    fi
else
    info "Workspace not found at $WORKSPACE_PATH — skipping"
fi

# ---------------------------------------------------------------------------
# Step 8 — Secrets (DANGEROUS — asks twice)
# ---------------------------------------------------------------------------

header "Step 8 — Secrets"

# Try to find secrets from common locations
for CANDIDATE_SECRETS in \
    "$HOME/.matrixmouse-secrets" \
    "${SECRETS_DIR:-}" \
; do
    [ -z "$CANDIDATE_SECRETS" ] && continue
    [ -d "$CANDIDATE_SECRETS" ] || continue

    echo ""
    echo "  Secrets directory: $CANDIDATE_SECRETS"
    echo "  This contains your SSH key and GitHub PAT."
    echo ""
    if confirm_danger "Delete secrets directory at $CANDIDATE_SECRETS?"; then
        rm -rf "$CANDIDATE_SECRETS"
        success "Secrets directory deleted"
    else
        info "Secrets kept at $CANDIDATE_SECRETS"
    fi
done

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

header "Uninstall complete"

echo ""
echo "MatrixMouse has been removed."
echo ""
echo "The following were intentionally NOT removed (if you skipped them):"
echo "  - Workspace (your repos and task history)"
echo "  - Secrets (SSH key and GitHub PAT)"
echo "  - ollama itself"
echo "  - docker itself"
echo ""
