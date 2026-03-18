#!/usr/bin/env bash
# install.sh
# MatrixMouse installation script
#
# Run as your normal user — NOT with sudo.
# The script uses sudo internally only where root is required.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Guard: refuse to run as root
# ---------------------------------------------------------------------------

if [ "$EUID" -eq 0 ]; then
    echo "ERROR: Do not run this script with sudo or as root."
    echo "Run as your normal user — the script will sudo when needed."
    exit 1
fi

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
error()   { echo -e "${RED}[error]${RESET} $*" >&2; }
fatal()   { error "$*"; exit 1; }
header()  { echo -e "\n${BOLD}── $* ──${RESET}"; }

# prompt <varname> <text> <default>
# If default is non-empty, accepts Enter to use it.
# If default is empty, the field is optional — blank input is allowed.
prompt() {
    local varname="$1" text="$2" default="$3"
    if [ -n "$default" ]; then
        read -rp "$(echo -e "${CYAN}?${RESET} ${text} [${default}]: ")" value
        value="${value:-$default}"
    else
        read -rp "$(echo -e "${CYAN}?${RESET} ${text} (optional, Enter to skip): ")" value
    fi
    eval "$varname=\"$value\""
}

# prompt_required <varname> <text> <default>
# Always requires a non-empty value.
prompt_required() {
    local varname="$1" text="$2" default="$3"
    local value=""
    if [ -n "$default" ]; then
        read -rp "$(echo -e "${CYAN}?${RESET} ${text} [${default}]: ")" value
        value="${value:-$default}"
    else
        read -rp "$(echo -e "${CYAN}?${RESET} ${text}: ")" value
        while [ -z "$value" ]; do
            warn "This field is required."
            read -rp "$(echo -e "${CYAN}?${RESET} ${text}: ")" value
        done
    fi
    eval "$varname=\"$value\""
}

confirm() {
    local answer
    read -rp "$(echo -e "${CYAN}?${RESET} $1 [y/N]: ")" answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

# Read a single value from a TOML file.
# Returns the bare value (no quotes) or empty string if not found.
read_toml() {
    local file="$1" key="$2"
    [ -f "$file" ] || { echo ""; return; }
    sudo grep -E "^${key}[[:space:]]*=" "$file" 2>/dev/null \
        | head -1 \
        | sed "s/^${key}[[:space:]]*=[[:space:]]*//;s/[\"']//g;s/[[:space:]]*$//"
}

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOKING_USER="$USER"

# ---------------------------------------------------------------------------
# Step 1 — Prerequisites
# ---------------------------------------------------------------------------

header "Step 1 — Prerequisites"

# python3.11 must be installed
SYSTEM_PYTHON="$(command -v python3.11)"
[ -n "$SYSTEM_PYTHON" ] || fatal "python3.11 not found. Install with: sudo apt install python3.11"
success "python3.11 found at $SYSTEM_PYTHON"

# uv — install as current user, never root
if command -v uv &>/dev/null; then
    success "uv found ($(uv --version))"
else
    warn "uv not found. Installing for current user..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    command -v uv &>/dev/null || fatal "uv installation failed. See: https://docs.astral.sh/uv/"
    success "uv installed"
fi

# Clear stale uv archive cache — prevents "No such file or directory" errors
# caused by partial downloads from previous failed installs.
if [ -d "$HOME/.cache/uv/archive-v0" ]; then
    info "Clearing stale uv archive cache..."
    rm -rf "$HOME/.cache/uv/archive-v0"
    success "uv cache cleared"
fi


if command -v docker &>/dev/null; then
    success "docker found"
    if groups "$INVOKING_USER" | grep -qw "docker"; then
        success "$INVOKING_USER is in the docker group"
    else
        warn "$INVOKING_USER is not in the docker group — docker requires sudo without it."
        if confirm "Add $INVOKING_USER to the docker group now?"; then
            sudo usermod -aG docker "$INVOKING_USER"
            echo ""
            echo "  Added $INVOKING_USER to the docker group."
            echo "  You must log out and back in for this to take effect."
            echo "  Re-run install.sh after logging back in."
            echo ""
            exit 0
        else
            fatal "Cannot continue: docker commands will fail without group membership."
        fi
    fi
else
    fatal "docker is not installed.\nInstall from: https://docs.docker.com/engine/install/"
fi


command -v git &>/dev/null || fatal "git not installed. Run: sudo apt install git"
success "git found"

if command -v ollama &>/dev/null; then
    success "ollama found"
    ollama list &>/dev/null 2>&1 || warn "Ollama may not be running. Start with: ollama serve"
else
    warn "ollama not found. Install from https://ollama.com"
    warn "The agent will not work until Ollama is running with a model pulled."
fi

if command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1; then
    success "systemd found"
else
    fatal "systemd is required. MatrixMouse cannot run without it."
fi

# ---------------------------------------------------------------------------
# Step 2 — Install MatrixMouse (as current user, never root)
# ---------------------------------------------------------------------------

header "Step 2 — Installing MatrixMouse"

# Install system-wide so the matrixmouse service user can execute the binaries.
# uv tool installs to /usr/local/bin when run as root with CARGO_HOME/UV_TOOL_DIR set.

if [ -f "/usr/local/bin/matrixmouse-service" ]; then
    success "matrixmouse already installed at /usr/local/bin"
    if confirm "Upgrade to latest version now?"; then
        sudo UV_TOOL_DIR=/usr/local/share/uv/tools \
            uv tool install "$INSTALL_DIR" --force \
	    --python "$SYSTEM_PYTHON"
	sudo chmod -R a+rX /usr/local/share/uv/tools/matrixmouse/
        success "matrixmouse upgraded"
    fi
else
    info "Installing matrixmouse system-wide..."
    sudo UV_TOOL_DIR=/usr/local/share/uv/tools \
        uv tool install "$INSTALL_DIR" \
	--python "$SYSTEM_PYTHON"
    sudo chmod -R a+rX /usr/local/share/uv/tools/matrixmouse/
    # Symlink binaries into /usr/local/bin so they're on PATH for all users
    sudo ln -sf /usr/local/share/uv/tools/matrixmouse/bin/matrixmouse \
        /usr/local/bin/matrixmouse
    sudo ln -sf /usr/local/share/uv/tools/matrixmouse/bin/matrixmouse-service \
        /usr/local/bin/matrixmouse-service
    success "matrixmouse installed at /usr/local/bin"
fi

command -v matrixmouse &>/dev/null \
    || fatal "matrixmouse binary not found at /usr/local/bin/matrixmouse"
command -v matrixmouse-service &>/dev/null \
    || fatal "matrixmouse-service binary not found."

success "matrixmouse:         $(command -v matrixmouse)"
success "matrixmouse-service: $(command -v matrixmouse-service)"

# ---------------------------------------------------------------------------
# Step 3 — System user and Shared Group
# ---------------------------------------------------------------------------

header "Step 3 — System user"

MM_USER="matrixmouse"
MM_GROUP="matrixmouse"

if id "$MM_USER" &>/dev/null; then
    success "System user '$MM_USER' already exists"
else
    info "Creating system user '$MM_USER'..."
    sudo useradd \
        --system \
        --create-home \
        --home-dir /home/matrixmouse \
        --shell /usr/sbin/nologin \
        --comment "MatrixMouse agent service user" \
        "$MM_USER"
    success "System user '$MM_USER' created"
fi

# Ensure home directory exists (handles users created without --create-home)
if [ ! -d "/home/matrixmouse" ]; then
    sudo mkdir -p /home/matrixmouse
    sudo chown matrixmouse:matrixmouse /home/matrixmouse
    sudo chmod 700 /home/matrixmouse
    success "Created home directory for $MM_USER"
fi

# Configure git for the service user — trust all mirror directories.
# safe.directory '*' disables ownership checks for this user, which is
# safe because matrixmouse has no shell access (nologin).
cd /tmp
sudo -u matrixmouse git config --global --replace-all safe.directory '*'
success "git safe.directory configured for $MM_USER"

# Create the shared group if it doesn't exist
if ! getent group "$MM_GROUP" &>/dev/null; then
    sudo groupadd --system "$MM_GROUP"
    success "Created group: $MM_GROUP"
else
    success "Group $MM_GROUP already exists"
fi


# ---------------------------------------------------------------------------
# Step 4 — /etc/matrixmouse  (config + secrets)
# ---------------------------------------------------------------------------

header "Step 4 — /etc/matrixmouse"

# All service config and secrets live under /etc/matrixmouse, owned by the
# matrixmouse user. The regular user never needs to read or write here —
# all interaction is via the HTTP API or CLI commands.

ETC_DIR="/etc/matrixmouse"
SECRETS_DIR="$ETC_DIR/secrets"

if [ -d "$ETC_DIR" ]; then
    success "/etc/matrixmouse already exists — skipping directory creation"
else
    sudo mkdir -p "$ETC_DIR"
    sudo chown "$MM_USER:$MM_GROUP" "$ETC_DIR"
    sudo chmod 750 "$ETC_DIR"
    success "Created $ETC_DIR"
fi

if [ -d "$SECRETS_DIR" ]; then
    success "$SECRETS_DIR already exists — skipping directory creation"
else
    sudo mkdir -p "$SECRETS_DIR"
    sudo chown "$MM_USER:$MM_USER" "$SECRETS_DIR"
    sudo chmod 700 "$SECRETS_DIR"
    success "Created $SECRETS_DIR"
fi

# Global config — readable by matrixmouse group (regular user can read server_port etc.)
GLOBAL_CONFIG="$ETC_DIR/config.toml"

if sudo test -f "$GLOBAL_CONFIG"; then
    success "$GLOBAL_CONFIG already exists — skipping"
else
    sudo tee "$GLOBAL_CONFIG" > /dev/null << 'EOF'
# MatrixMouse global configuration
# Values here apply to all workspaces. Workspace and repo configs override these.
# Uncomment and edit lines to activate settings.
# Full reference: https://github.com/joshmrtn/MatrixMouse

# --- Server ---
# server_port = 8080

# --- Models ---
# coder_model     = "qwen3.5:4b"
# manager_model   = "qwen3.5:4b"
# critic_model     = "qwen3.5:4b"
# summarizer_model = "qwen3.5:4b"
# coder_cascade   = ["qwen3.5:4b", "qwen3.5:9b", "qwen3.5:27b"]

# --- Logging ---
# log_level   = "INFO"
# log_to_file = false

# --- Comms ---
# ntfy_url   = ""
# ntfy_topic = "matrixmouse"
# web_ui_url = ""
EOF
    sudo chown "$MM_USER:$MM_GROUP" "$GLOBAL_CONFIG"
    sudo chmod 640 "$GLOBAL_CONFIG"
    success "Written $GLOBAL_CONFIG"
fi


# ---------------------------------------------------------------------------
# Step 5 — Workspace directory
# ---------------------------------------------------------------------------

header "Step 5 — Workspace directory"

prompt_required WORKSPACE_PATH \
    "Workspace directory" \
    "/var/lib/matrixmouse-workspace"
WORKSPACE_PATH="$(eval echo "$WORKSPACE_PATH")"

if [ -d "$WORKSPACE_PATH" ]; then
    success "Workspace already exists: $WORKSPACE_PATH"
else
    sudo mkdir -p "$WORKSPACE_PATH"
    success "Created workspace: $WORKSPACE_PATH"
fi

sudo mkdir -p "$WORKSPACE_PATH/.matrixmouse"
sudo chown -R "$MM_USER:$MM_USER" "$WORKSPACE_PATH"
sudo chmod -R u=rwX,g=,o= "$WORKSPACE_PATH"

success "Workspace: $WORKSPACE_PATH (owned by $MM_USER)"

CONFIG_FILE="$WORKSPACE_PATH/.matrixmouse/config.toml"

# ---------------------------------------------------------------------------
# Step 6 — Agent credentials
# ---------------------------------------------------------------------------

header "Step 6 — Agent credentials"

echo "MatrixMouse uses a dedicated bot account for git operations and PRs."
echo "Credentials are stored in $SECRETS_DIR, owned by the matrixmouse user."
echo ""

# SSH key
AGENT_KEY_PATH="$SECRETS_DIR/agent_ed25519"

if sudo test -f "$AGENT_KEY_PATH"; then
    success "SSH key already exists: $AGENT_KEY_PATH — skipping"
else
    if confirm "Generate a new ed25519 SSH key now?"; then
        # Generate as invoking user in a temp location, then move into place
        TMP_KEY="$(mktemp)"
        rm -f "$TMP_KEY"
        ssh-keygen -t ed25519 -C "matrixmouse-bot" -f "$TMP_KEY" -N ""
        sudo mv "$TMP_KEY"     "$AGENT_KEY_PATH"
        sudo mv "${TMP_KEY}.pub" "${AGENT_KEY_PATH}.pub"
        sudo chown "$MM_USER:$MM_USER" "$AGENT_KEY_PATH" "${AGENT_KEY_PATH}.pub"
        sudo chmod 600 "$AGENT_KEY_PATH"
        sudo chmod 644 "${AGENT_KEY_PATH}.pub"
        success "SSH key generated: $AGENT_KEY_PATH"
        echo ""
        echo -e "${BOLD}Add this public key to your GitHub bot account:${RESET}"
        echo "  https://github.com/settings/keys"
        echo ""
        sudo cat "${AGENT_KEY_PATH}.pub"
        echo ""
        read -rp "Press Enter when the key has been added to GitHub..."
    else
        warn "Skipping SSH key. Required for cloning private repos."
        warn "To add manually:"
        warn "  sudo -u $MM_USER ssh-keygen -t ed25519 -f $AGENT_KEY_PATH -N ''"
    fi
fi

# GitHub PAT
AGENT_TOKEN_PATH="$SECRETS_DIR/github_token"

if sudo test -f "$AGENT_TOKEN_PATH"; then
    success "GitHub token already exists: $AGENT_TOKEN_PATH — skipping"
else
    if confirm "Create GitHub PAT file now?"; then
        read -rsp "$(echo -e "${CYAN}?${RESET} Paste your GitHub PAT (input hidden): ")" GH_PAT
        echo ""
        echo -n "$GH_PAT" | sudo -u "$MM_USER" tee "$AGENT_TOKEN_PATH" > /dev/null
        unset GH_PAT
        sudo chmod 600 "$AGENT_TOKEN_PATH"
        success "Token saved: $AGENT_TOKEN_PATH"
    else
        warn "Skipping. Required for opening PRs."
        warn "Required scopes: repo (full). Create at: https://github.com/settings/tokens"
        warn "To add manually: echo -n 'TOKEN' | sudo -u $MM_USER tee $AGENT_TOKEN_PATH"
    fi
fi

_cur_git_name=$(read_toml "$CONFIG_FILE" "agent_git_name")
_cur_git_email=$(read_toml "$CONFIG_FILE" "agent_git_email")
prompt_required AGENT_GIT_NAME  "Agent git commit name" \
    "${_cur_git_name:-MatrixMouse Agent}"
prompt_required AGENT_GIT_EMAIL "Agent git commit email" \
    "${_cur_git_email:-matrixmouse-bot@users.noreply.github.com}"


# ---------------------------------------------------------------------------
# Step 7 — matrixmouse group and mirror directory
# ---------------------------------------------------------------------------

header "Step 7 — Mirror directory"

MIRRORS_DIR="/var/lib/matrixmouse-mirrors"

# Add both users to the group
sudo usermod -aG "$MM_GROUP" "$MM_USER"
sudo usermod -aG "$MM_GROUP" "$INVOKING_USER"
success "Added $MM_USER and $INVOKING_USER to $MM_GROUP"

# Check group membership — requires re-login to take effect
NEEDS_RELOGIN=false

if ! groups "$INVOKING_USER" | grep -qw "$MM_GROUP"; then
    warn "$INVOKING_USER was just added to $MM_GROUP."
    NEEDS_RELOGIN=true
fi

if [ "$NEEDS_RELOGIN" = true ]; then
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────┐"
    echo "  │  ACTION REQUIRED: You must log out and back in for      │"
    echo "  │  group membership to take effect, then re-run           │"
    echo "  │  install.sh to complete the installation.               │"
    echo "  └─────────────────────────────────────────────────────────┘"
    echo ""
    exit 0
fi

# Create the mirrors root with setgid so subdirs inherit the group
sudo install -d -m 2775 -g "$MM_GROUP" "$MIRRORS_DIR"
success "Mirror directory ready at $MIRRORS_DIR"


# ---------------------------------------------------------------------------
# Step 8 — Model configuration
# ---------------------------------------------------------------------------

header "Step 8 — Model configuration"

echo "Enter Ollama model names for each role."
echo "Models must support tool calling. Check available: ollama list"
echo ""

_cur_coder=$(read_toml "$CONFIG_FILE" "coder_model")
_cur_manager=$(read_toml "$CONFIG_FILE" "manager_model")
_cur_critic=$(read_toml "$CONFIG_FILE" "critic_model")
_cur_summarizer=$(read_toml "$CONFIG_FILE" "summarizer_model")

prompt_required CODER_MODEL      "Coder model (implementation)" \
    "${_cur_coder:-qwen3.5:4b}"
prompt_required MANAGER_MODEL    "Manager model (design/task management)" \
    "${_cur_manager:-qwen3.5:9b}"
prompt_required CRITIC_MODEL      "Critic model (critique/decision making)" \
    "${_cur_critic:-qwen3.5:9b}"
prompt_required SUMMARIZER_MODEL "Summarizer model (context compression)" \
    "${_cur_summarizer:-qwen3.5:4b}"

echo ""
echo "Coder cascade: models to escalate through when stuck (comma-separated,"
echo "smallest to largest). Defaults to just the coder model (no escalation)."
if sudo test -f "$CONFIG_FILE"; then
    info "coder_cascade: edit directly in $CONFIG_FILE if needed — skipping prompt"
    CODER_CASCADE=""  # sentinel: skip upsert in Step 9
else
    prompt_required CODER_CASCADE "Coder cascade" "$CODER_MODEL"
fi

# ---------------------------------------------------------------------------
# Step 9 — Notifications (optional)
# ---------------------------------------------------------------------------

header "Step 9 — Notifications (optional)"

echo "MatrixMouse can push notifications via ntfy when it needs attention."
echo "Leave blank to skip — configure later in /etc/matrixmouse/config.toml"
echo ""

_cur_ntfy_url=$(read_toml "$CONFIG_FILE" "ntfy_url")
_cur_ntfy_topic=$(read_toml "$CONFIG_FILE" "ntfy_topic")
_cur_web_ui_url=$(read_toml "$CONFIG_FILE" "web_ui_url")

prompt NTFY_URL     "ntfy server URL (e.g. https://ntfy.sh)" \
    "${_cur_ntfy_url:-}"
prompt NTFY_TOPIC   "ntfy topic" \
    "${_cur_ntfy_topic:-matrixmouse}"
prompt WEB_UI_URL   "Web UI URL (included in ntfy notifications)" \
    "${_cur_web_ui_url:-https://mm.example.com}"

# ---------------------------------------------------------------------------
# Step 10 — Write configuration files
# ---------------------------------------------------------------------------

header "Step 10 — Configuration files"

CONFIG_EXISTS=false
sudo test -f "$CONFIG_FILE" && CONFIG_EXISTS=true

if [ "$CONFIG_EXISTS" = false ]; then
    # Fresh install — write full config via heredoc
    IFS=',' read -ra CASCADE_MODELS <<< "$CODER_CASCADE"
    TOML_ARRAY=""
    for m in "${CASCADE_MODELS[@]}"; do
        m="$(echo "$m" | xargs)"
        TOML_ARRAY="${TOML_ARRAY}\"${m}\", "
    done
    CASCADE_LINE="coder_cascade = [${TOML_ARRAY%, }]"

    sudo -u "$MM_USER" tee "$CONFIG_FILE" > /dev/null << EOF
# MatrixMouse workspace configuration
# Repo-specific overrides: <repo>/.matrixmouse/config.toml

coder_model      = "$CODER_MODEL"
manager_model    = "$MANAGER_MODEL"
critic_model      = "$CRITIC_MODEL"
summarizer_model = "$SUMMARIZER_MODEL"
$CASCADE_LINE

agent_git_name  = "$AGENT_GIT_NAME"
agent_git_email = "$AGENT_GIT_EMAIL"

server_port = 8080
web_ui_url  = "$WEB_UI_URL"
log_level   = "INFO"
log_to_file = false

ntfy_url   = "$NTFY_URL"
ntfy_topic = "$NTFY_TOPIC"

priority_aging_rate      = 0.01
priority_max_aging_bonus = 0.3
EOF
    success "Written $CONFIG_FILE"

else
    # Reinstall — upsert individual keys, never clobber
    # coder_cascade is skipped — edit manually if needed (multi-line array safe)
    upsert_toml "$CONFIG_FILE" "coder_model"      "$CODER_MODEL"
    upsert_toml "$CONFIG_FILE" "manager_model"    "$MANAGER_MODEL"
    upsert_toml "$CONFIG_FILE" "critic_model"      "$CRITIC_MODEL"
    upsert_toml "$CONFIG_FILE" "summarizer_model" "$SUMMARIZER_MODEL"
    upsert_toml "$CONFIG_FILE" "agent_git_name"   "$AGENT_GIT_NAME"
    upsert_toml "$CONFIG_FILE" "agent_git_email"  "$AGENT_GIT_EMAIL"
    upsert_toml "$CONFIG_FILE" "web_ui_url"       "$WEB_UI_URL"
    upsert_toml "$CONFIG_FILE" "ntfy_url"         "$NTFY_URL"
    upsert_toml "$CONFIG_FILE" "ntfy_topic"       "$NTFY_TOPIC"
    success "Updated $CONFIG_FILE"
fi


# ---------------------------------------------------------------------------
# Step 11 — Build test runner Docker image and install script
# ---------------------------------------------------------------------------

header "Step 11 — Test runner"

DOCKERFILE_TR="$INSTALL_DIR/Dockerfile.testrunner"
[ -f "$DOCKERFILE_TR" ] || fatal "Dockerfile.testrunner not found at $INSTALL_DIR"
[ -f "$INSTALL_DIR/test_runner.sh" ] || fatal "test_runner.sh not found at $INSTALL_DIR"

# Install test_runner.sh to a system path the service user can execute
TR_LIB_DIR="/usr/local/lib/matrixmouse"
TR_INSTALL_PATH="$TR_LIB_DIR/test_runner.sh"

sudo mkdir -p "$TR_LIB_DIR"
sudo cp "$INSTALL_DIR/test_runner.sh" "$TR_INSTALL_PATH"
sudo chown "$MM_USER:$MM_USER" "$TR_INSTALL_PATH"
sudo chmod 755 "$TR_INSTALL_PATH"
success "test_runner.sh installed to $TR_INSTALL_PATH"

HASH_FILE="$WORKSPACE_PATH/.matrixmouse/testrunner.image.sha256"

if docker image inspect matrixmouse-test-runner &>/dev/null 2>&1; then
    success "matrixmouse-test-runner image already exists"
    if confirm "Rebuild the test runner image?"; then
        docker build -f "$DOCKERFILE_TR" -t matrixmouse-test-runner "$INSTALL_DIR"
        sha256sum "$DOCKERFILE_TR" | awk '{print $1}' \
            | sudo -u "$MM_USER" tee "$HASH_FILE" > /dev/null
        success "matrixmouse-test-runner rebuilt"
    fi
else
    info "Building matrixmouse-test-runner image..."
    docker build -f "$DOCKERFILE_TR" -t matrixmouse-test-runner "$INSTALL_DIR"
    sha256sum "$DOCKERFILE_TR" | awk '{print $1}' \
        | sudo -u "$MM_USER" tee "$HASH_FILE" > /dev/null
    success "matrixmouse-test-runner image built"
fi


# ---------------------------------------------------------------------------
# Step 12 — systemd services
# ---------------------------------------------------------------------------

header "Step 12 — systemd services"

MM_SERVICE_BIN="$(command -v matrixmouse-service)"

MM_SVC="/etc/systemd/system/matrixmouse.service"
if [ -f "$MM_SVC" ]; then
    success "matrixmouse.service already exists — skipping"
else
    info "Installing matrixmouse.service..."
    sudo tee "$MM_SVC" > /dev/null << EOF
[Unit]
Description=MatrixMouse autonomous coding agent
Documentation=https://github.com/joshmrtn/MatrixMouse
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=$MM_USER
Group=$MM_GROUP
WorkingDirectory=$WORKSPACE_PATH
ExecStart=$MM_SERVICE_BIN
Restart=on-failure
RestartSec=10
TimeoutStopSec=30

Environment=WORKSPACE_PATH=$WORKSPACE_PATH

NoNewPrivileges=true
ProtectSystem=strict
# read-only not true: matrixmouse user reads ~/.gitconfig at runtime
ProtectHome=read-only
ReadWritePaths=$WORKSPACE_PATH $SECRETS_DIR $ETC_DIR /run/matrixmouse-pipes

RuntimeDirectory=matrixmouse-pipes
RuntimeDirectoryMode=0750

StandardOutput=journal
StandardError=journal
SyslogIdentifier=matrixmouse

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable matrixmouse
    sudo systemctl start matrixmouse
    success "matrixmouse.service installed and started"
fi

TR_SVC="/etc/systemd/system/matrixmouse-test-runner.service"
if [ -f "$TR_SVC" ]; then
    success "matrixmouse-test-runner.service already exists — skipping"
else
    info "Installing matrixmouse-test-runner.service..."
    sudo tee "$TR_SVC" > /dev/null << EOF
[Unit]
Description=MatrixMouse test runner (Docker sandbox)
After=docker.service matrixmouse.service
Requires=docker.service

[Service]
Type=simple
User=$MM_USER
Group=$MM_GROUP
ExecStart=$TR_INSTALL_PATH
Restart=always
RestartSec=5

Environment=FIFO_DIR=/run/matrixmouse-pipes
Environment=WORKSPACE=$WORKSPACE_PATH
Environment=TEST_IMAGE=matrixmouse-test-runner

StandardOutput=journal
StandardError=journal
SyslogIdentifier=matrixmouse-test-runner

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable matrixmouse-test-runner
    sudo systemctl start matrixmouse-test-runner
    success "matrixmouse-test-runner.service installed and started"
fi

# ---------------------------------------------------------------------------
# Step 13 — Ollama configuration
# ---------------------------------------------------------------------------

header "Step 13 — Ollama configuration"

OLLAMA_OVERRIDE="/etc/systemd/system/ollama.service.d/override.conf"

if grep -q "OLLAMA_MAX_LOADED_MODELS" "$OLLAMA_OVERRIDE" 2>/dev/null || \
   grep -q "OLLAMA_MAX_LOADED_MODELS" /etc/systemd/system/ollama.service 2>/dev/null; then
    success "OLLAMA_MAX_LOADED_MODELS already configured"
elif [ -f "$OLLAMA_OVERRIDE" ]; then
    # Override file exists with other settings — append rather than clobber
    if confirm "Add OLLAMA_MAX_LOADED_MODELS=4 to existing Ollama override?"; then
        echo 'Environment="OLLAMA_MAX_LOADED_MODELS=4"' | sudo tee -a "$OLLAMA_OVERRIDE" > /dev/null
        sudo systemctl daemon-reload
        sudo systemctl restart ollama 2>/dev/null || true
        success "OLLAMA_MAX_LOADED_MODELS=4 added to existing override"
    fi
else
    if confirm "Set OLLAMA_MAX_LOADED_MODELS=4 in Ollama's systemd service?"; then
        sudo mkdir -p "$(dirname "$OLLAMA_OVERRIDE")"
        sudo tee "$OLLAMA_OVERRIDE" > /dev/null << 'EOF'
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=4"
EOF
        sudo systemctl daemon-reload
        sudo systemctl restart ollama 2>/dev/null || true
        success "OLLAMA_MAX_LOADED_MODELS=4 configured"
    fi
fi


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Installation complete"

echo ""
echo -e "${BOLD}Directory layout:${RESET}"
echo "  /etc/matrixmouse/           global config, secrets (SSH key, PAT, ntfy)"
echo "  $WORKSPACE_PATH"
echo "    .matrixmouse/             tasks, repos, workspace config.toml"
echo "  /run/matrixmouse-pipes/     test runner FIFO pipes (created by systemd)"
echo "  /usr/local/lib/matrixmouse/ test_runner.sh"
echo ""
echo -e "${BOLD}Binaries:${RESET}"
echo "  matrixmouse:         $(command -v matrixmouse)"
echo "  matrixmouse-service: $(command -v matrixmouse-service)"
echo ""
echo -e "${BOLD}Services:${RESET}"
echo "  matrixmouse               matrixmouse-test-runner"
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo "  1. Pull your models:"
echo "       ollama pull $CODER_MODEL"
echo "       ollama pull $MANAGER_MODEL"
echo "       ollama pull $CRITIC_MODEL"
echo "       ollama pull $SUMMARIZER_MODEL"
echo ""
echo "  2. Add a repo:"
echo "       matrixmouse add-repo git@github.com:you/repo.git"
echo ""
echo "  3. Create a task:"
echo "       matrixmouse tasks add"
echo ""
echo "  4. Check status:"
echo "       matrixmouse status"
echo "       curl http://localhost:8080/health"
echo "       sudo systemctl status matrixmouse"
echo "       journalctl -u matrixmouse -f"
echo ""
