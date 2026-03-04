#!/usr/bin/env bash
# install.sh
# MatrixMouse installation script
#
# Installs MatrixMouse natively on a Linux host using uv.
# Sets up the workspace, credentials, systemd services, and test runner.
# Safe to re-run — skips steps already completed.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh

set -euo pipefail

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

prompt() {
    local varname="$1" text="$2" default="$3"
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

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Step 1 — Prerequisites
# ---------------------------------------------------------------------------

header "Step 1 — Prerequisites"

# uv
if command -v uv &>/dev/null; then
    success "uv found ($(uv --version))"
else
    warn "uv not found. Installing via official installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Reload PATH for this session
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        success "uv installed"
    else
        fatal "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    fi
fi

# docker (for test runner)
if command -v docker &>/dev/null; then
    success "docker found"
else
    fatal "docker is not installed. Required for the test runner sandbox.\nInstall from: https://docs.docker.com/engine/install/"
fi

# git
if command -v git &>/dev/null; then
    success "git found"
else
    fatal "git is not installed. Install with: sudo apt install git"
fi

# ollama
if command -v ollama &>/dev/null; then
    success "ollama found"
    if ! ollama list &>/dev/null 2>&1; then
        warn "Ollama is installed but the service may not be running."
        warn "Start it with: ollama serve  (or enable the systemd service)"
    fi
else
    warn "ollama not found. Install from https://ollama.com"
    warn "The agent will not work until Ollama is running with a model pulled."
fi

# systemd
HAS_SYSTEMD=false
if command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1; then
    HAS_SYSTEMD=true
    success "systemd found"
else
    warn "systemd not found. Services must be started manually."
fi

# ---------------------------------------------------------------------------
# Step 2 — Install MatrixMouse
# ---------------------------------------------------------------------------

header "Step 2 — Installing MatrixMouse"

if uv tool list 2>/dev/null | grep -q "matrixmouse"; then
    success "matrixmouse already installed via uv"
    if confirm "Upgrade to latest version now?"; then
        uv tool upgrade matrixmouse
        success "matrixmouse upgraded"
    fi
else
    info "Installing matrixmouse..."
    # From PyPI once published:
    #   uv tool install matrixmouse
    # For now, install from local source:
    if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
        uv tool install "$INSTALL_DIR"
        success "matrixmouse installed from $INSTALL_DIR"
    else
        fatal "pyproject.toml not found at $INSTALL_DIR. Cannot install."
    fi
fi

# Confirm binaries are on PATH
if ! command -v matrixmouse &>/dev/null; then
    # uv tools land in ~/.local/bin
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v matrixmouse &>/dev/null; then
        fatal "matrixmouse binary not found after install. Check uv tool bin path."
    fi
fi
success "matrixmouse CLI available at $(command -v matrixmouse)"
success "matrixmouse-service available at $(command -v matrixmouse-service)"

# ---------------------------------------------------------------------------
# Step 3 — System user
# ---------------------------------------------------------------------------

header "Step 3 — System user"

MM_USER="matrixmouse"

if id "$MM_USER" &>/dev/null; then
    success "System user '$MM_USER' already exists"
else
    info "Creating system user '$MM_USER'..."
    sudo useradd \
        --system \
        --no-create-home \
        --shell /usr/sbin/nologin \
        --comment "MatrixMouse agent service user" \
        "$MM_USER"
    success "System user '$MM_USER' created"
fi

# ---------------------------------------------------------------------------
# Step 4 — Workspace directory
# ---------------------------------------------------------------------------

header "Step 4 — Workspace directory"

prompt WORKSPACE_PATH \
    "Workspace directory (where repos will be cloned)" \
    "$HOME/matrixmouse-workspace"
WORKSPACE_PATH="$(eval echo "$WORKSPACE_PATH")"

if [ -d "$WORKSPACE_PATH" ]; then
    success "Workspace already exists: $WORKSPACE_PATH"
else
    mkdir -p "$WORKSPACE_PATH"
    success "Created workspace: $WORKSPACE_PATH"
fi

# Scaffold .matrixmouse/
mkdir -p "$WORKSPACE_PATH/.matrixmouse"

# Ownership: matrixmouse user owns the workspace so the service can write.
# The installing user gets read access via world-readable permissions on files.
sudo chown -R "$MM_USER:$MM_USER" "$WORKSPACE_PATH"
sudo chmod -R u=rwX,g=rX,o=rX "$WORKSPACE_PATH"

# The installing user needs to write to the workspace for add-repo bootstrap.
# Grant them group access via the matrixmouse group.
sudo usermod -aG "$MM_USER" "$USER"
warn "Added $USER to group '$MM_USER'."
warn "You may need to log out and back in for group membership to take effect."

success "Workspace ownership set: $MM_USER owns, $USER has read+group-write"

# ---------------------------------------------------------------------------
# Step 5 — Agent credentials
# ---------------------------------------------------------------------------

header "Step 5 — Agent credentials"

echo "MatrixMouse uses a dedicated bot account for git operations and PRs."
echo "Credentials are stored outside the workspace and never committed."
echo ""

DEFAULT_SECRETS="$HOME/.matrixmouse-secrets"
prompt SECRETS_DIR \
    "Secrets directory (SSH key and GitHub PAT)" \
    "$DEFAULT_SECRETS"
SECRETS_DIR="$(eval echo "$SECRETS_DIR")"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

# SSH key
prompt AGENT_KEY_PATH \
    "Path to agent SSH private key" \
    "$SECRETS_DIR/agent_ed25519"
AGENT_KEY_PATH="$(eval echo "$AGENT_KEY_PATH")"

if [ -f "$AGENT_KEY_PATH" ]; then
    success "SSH key found: $AGENT_KEY_PATH"
else
    warn "SSH key not found at $AGENT_KEY_PATH"
    if confirm "Generate a new ed25519 SSH key now?"; then
        mkdir -p "$(dirname "$AGENT_KEY_PATH")"
        ssh-keygen -t ed25519 -C "matrixmouse-bot" -f "$AGENT_KEY_PATH" -N ""
        chmod 600 "$AGENT_KEY_PATH"
        success "SSH key generated: $AGENT_KEY_PATH"
        echo ""
        echo -e "${BOLD}Add this public key to your GitHub bot account:${RESET}"
        echo "  https://github.com/settings/keys"
        echo ""
        cat "${AGENT_KEY_PATH}.pub"
        echo ""
        read -rp "Press Enter when the key has been added to GitHub..."
    else
        warn "Skipping. Create the key manually before cloning private repos."
    fi
fi

# GitHub PAT
prompt AGENT_TOKEN_PATH \
    "Path to file containing GitHub PAT" \
    "$SECRETS_DIR/github_token"
AGENT_TOKEN_PATH="$(eval echo "$AGENT_TOKEN_PATH")"

if [ -f "$AGENT_TOKEN_PATH" ]; then
    success "GitHub token file found: $AGENT_TOKEN_PATH"
else
    warn "Token file not found at $AGENT_TOKEN_PATH"
    if confirm "Create the token file now?"; then
        read -rsp "$(echo -e "${CYAN}?${RESET} Paste your GitHub PAT (input hidden): ")" GH_PAT
        echo ""
        echo -n "$GH_PAT" > "$AGENT_TOKEN_PATH"
        chmod 600 "$AGENT_TOKEN_PATH"
        unset GH_PAT
        success "Token saved: $AGENT_TOKEN_PATH"
    else
        warn "Skipping. Create $AGENT_TOKEN_PATH manually before opening PRs."
        warn "Required scopes: repo (full). Create at: https://github.com/settings/tokens"
    fi
fi

# Make secrets readable by the matrixmouse service user
sudo chown -R "$MM_USER:$MM_USER" "$SECRETS_DIR" 2>/dev/null || true
sudo chmod -R 600 "$SECRETS_DIR"/* 2>/dev/null || true
sudo chmod 700 "$SECRETS_DIR"

# Git identity for commits
prompt AGENT_GIT_NAME  "Agent git commit name"  "MatrixMouse Bot"
prompt AGENT_GIT_EMAIL "Agent git commit email" "matrixmouse-bot@users.noreply.github.com"

# ---------------------------------------------------------------------------
# Step 6 — Model configuration
# ---------------------------------------------------------------------------

header "Step 6 — Model configuration"

echo "Enter Ollama model names for each role."
echo "Models must support tool calling."
echo "Check available models with: ollama list"
echo ""

prompt CODER_MODEL      "Coder model (implementation)"        "qwen2.5-coder:14b"
prompt PLANNER_MODEL    "Planner model (design/critique)"     "qwen2.5:14b"
prompt SUMMARIZER_MODEL "Summarizer model (context compression)" "qwen2.5:3b"

echo ""
echo "Optional: coder cascade for escalation (comma-separated, smallest to largest)"
echo "Leave blank for no escalation."
prompt CODER_CASCADE "Coder cascade" ""

# ---------------------------------------------------------------------------
# Step 7 — Notification configuration (optional)
# ---------------------------------------------------------------------------

header "Step 7 — Notifications (optional)"

echo "MatrixMouse can send push notifications via ntfy when it needs attention."
echo "Leave blank to skip."
echo ""

prompt NTFY_URL   "ntfy server URL (e.g. https://ntfy.sh)" ""
prompt NTFY_TOPIC "ntfy topic"                              "matrixmouse"

# ---------------------------------------------------------------------------
# Step 8 — Write configuration files
# ---------------------------------------------------------------------------

header "Step 8 — Configuration"

# .env file (secrets — not stored in workspace)
ENV_FILE="$SECRETS_DIR/matrixmouse.env"
if [ -f "$ENV_FILE" ]; then
    warn ".env file already exists at $ENV_FILE — skipping to avoid overwriting."
    warn "Delete it and re-run to regenerate."
else
    cat > "$ENV_FILE" << EOF
# MatrixMouse secrets environment file
# Loaded by the service at startup via config.toml env_file setting.
# Never commit this file or store it inside the workspace.

WORKSPACE_PATH=$WORKSPACE_PATH
SECRETS_PATH=$SECRETS_DIR
MATRIXMOUSE_AGENT_GH_KEY_FILE=$(basename "$AGENT_KEY_PATH")
MATRIXMOUSE_GITHUB_TOKEN_FILE=$(basename "$AGENT_TOKEN_PATH")
MM_SERVER_PORT=8080
EOF
    chmod 600 "$ENV_FILE"
    success "Written $ENV_FILE"
fi

# workspace config.toml (non-secret)
CONFIG_FILE="$WORKSPACE_PATH/.matrixmouse/config.toml"
if [ -f "$CONFIG_FILE" ]; then
    warn "config.toml already exists — skipping."
    warn "Delete $CONFIG_FILE and re-run to regenerate."
else
    # Build coder_cascade TOML array
    CASCADE_LINE="# coder_cascade = []  # add models for escalation"
    if [ -n "$CODER_CASCADE" ]; then
        IFS=',' read -ra CASCADE_MODELS <<< "$CODER_CASCADE"
        TOML_ARRAY=""
        for m in "${CASCADE_MODELS[@]}"; do
            m="$(echo "$m" | xargs)"
            TOML_ARRAY="${TOML_ARRAY}\"${m}\", "
        done
        CASCADE_LINE="coder_cascade = [${TOML_ARRAY%, }]"
    fi

    # Build ntfy lines
    if [ -n "$NTFY_URL" ]; then
        NTFY_LINES="ntfy_url   = \"$NTFY_URL\"
ntfy_topic = \"$NTFY_TOPIC\""
    else
        NTFY_LINES="# ntfy_url   = \"https://ntfy.sh\"
# ntfy_topic = \"matrixmouse\""
    fi

    sudo -u "$MM_USER" tee "$CONFIG_FILE" > /dev/null << EOF
# MatrixMouse workspace configuration
# Applies to all repos in this workspace.
# Repo-specific overrides: <repo>/.matrixmouse/config.toml
#
# Secrets (SSH keys, tokens) are in the .env file referenced below.
# Never put secrets in this file.

# Path to secrets .env file
env_file = "$ENV_FILE"

# Models
coder      = "$CODER_MODEL"
planner    = "$PLANNER_MODEL"
summarizer = "$SUMMARIZER_MODEL"
$CASCADE_LINE

# Agent git identity
agent_git_name  = "$AGENT_GIT_NAME"
agent_git_email = "$AGENT_GIT_EMAIL"

# Web server
server_port = 8080

# Logging
log_level   = "INFO"
log_to_file = false

# Notifications
$NTFY_LINES

# Priority scheduling
priority_aging_rate      = 0.01
priority_max_aging_bonus = 0.3
EOF
    success "Written $CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# Step 9 — FIFO pipes for test runner
# ---------------------------------------------------------------------------

header "Step 9 — Test runner FIFO pipes"

FIFO_DIR="/tmp/matrixmouse-pipes"
mkdir -p "$FIFO_DIR"
chmod 750 "$FIFO_DIR"
sudo chown "$MM_USER:$MM_USER" "$FIFO_DIR"

[ -p "$FIFO_DIR/request.fifo" ] || mkfifo "$FIFO_DIR/request.fifo"
[ -p "$FIFO_DIR/result.fifo"  ] || mkfifo "$FIFO_DIR/result.fifo"
sudo chown "$MM_USER:$MM_USER" "$FIFO_DIR"/*.fifo
chmod 660 "$FIFO_DIR"/*.fifo

success "FIFO pipes ready at $FIFO_DIR"

# ---------------------------------------------------------------------------
# Step 10 — Build test runner Docker image
# ---------------------------------------------------------------------------

header "Step 10 — Test runner Docker image"

DOCKERFILE_TR="$INSTALL_DIR/Dockerfile.testrunner"
if [ ! -f "$DOCKERFILE_TR" ]; then
    fatal "Dockerfile.testrunner not found at $INSTALL_DIR"
fi

if docker image inspect matrixmouse-test-runner &>/dev/null 2>&1; then
    success "matrixmouse-test-runner image already exists"
    if confirm "Rebuild the test runner image?"; then
        docker build -f "$DOCKERFILE_TR" -t matrixmouse-test-runner "$INSTALL_DIR"
        success "matrixmouse-test-runner image rebuilt"
    fi
else
    info "Building matrixmouse-test-runner image..."
    docker build -f "$DOCKERFILE_TR" -t matrixmouse-test-runner "$INSTALL_DIR"
    success "matrixmouse-test-runner image built"
fi

# Record the Dockerfile hash so matrixmouse upgrade knows when to rebuild
HASH_DIR="$HOME/.config/matrixmouse"
mkdir -p "$HASH_DIR"
sha256sum "$DOCKERFILE_TR" | awk '{print $1}' > "$HASH_DIR/testrunner.image.sha256"
success "Test runner image hash recorded"

# ---------------------------------------------------------------------------
# Step 11 — systemd services
# ---------------------------------------------------------------------------

header "Step 11 — systemd services"

# Resolve binary paths (uv installs to ~/.local/bin)
MM_SERVICE_BIN="$(command -v matrixmouse-service)"
MM_TEST_RUNNER="$INSTALL_DIR/test_runner.sh"
chmod +x "$MM_TEST_RUNNER"

if $HAS_SYSTEMD; then

    # --- MatrixMouse agent service ---
    MM_SERVICE_FILE="/etc/systemd/system/matrixmouse.service"
    if [ -f "$MM_SERVICE_FILE" ]; then
        success "matrixmouse.service already exists — skipping"
    else
        info "Installing matrixmouse.service..."
        sudo tee "$MM_SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=MatrixMouse autonomous coding agent
Documentation=https://github.com/joshmrtn/MatrixMouse
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=$MM_USER
Group=$MM_USER
WorkingDirectory=$WORKSPACE_PATH
ExecStart=$MM_SERVICE_BIN
Restart=on-failure
RestartSec=10
TimeoutStopSec=30

# Environment
Environment=WORKSPACE_PATH=$WORKSPACE_PATH
EnvironmentFile=-$ENV_FILE

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$WORKSPACE_PATH $SECRETS_DIR /tmp/matrixmouse-pipes
ProtectHome=read-only

# Logging
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

    # --- Test runner service ---
    TR_SERVICE_FILE="/etc/systemd/system/matrixmouse-test-runner.service"
    if [ -f "$TR_SERVICE_FILE" ]; then
        success "matrixmouse-test-runner.service already exists — skipping"
    else
        info "Installing matrixmouse-test-runner.service..."
        sudo tee "$TR_SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=MatrixMouse test runner (Docker sandbox)
Documentation=https://github.com/joshmrtn/MatrixMouse
After=docker.service matrixmouse.service
Requires=docker.service

[Service]
Type=simple
User=$MM_USER
Group=$MM_USER
ExecStart=$MM_TEST_RUNNER
Restart=always
RestartSec=5

Environment=FIFO_DIR=$FIFO_DIR
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

else
    warn "systemd not available. Start services manually:"
    warn "  $MM_SERVICE_BIN &"
    warn "  FIFO_DIR=$FIFO_DIR WORKSPACE=$WORKSPACE_PATH $MM_TEST_RUNNER &"
fi

# ---------------------------------------------------------------------------
# Step 12 — Ollama configuration
# ---------------------------------------------------------------------------

header "Step 12 — Ollama configuration"

OLLAMA_OVERRIDE="/etc/systemd/system/ollama.service.d/override.conf"
if $HAS_SYSTEMD; then
    if [ -f "$OLLAMA_OVERRIDE" ] || grep -q "OLLAMA_MAX_LOADED_MODELS" \
       /etc/systemd/system/ollama.service 2>/dev/null; then
        success "OLLAMA_MAX_LOADED_MODELS already configured"
    else
        if confirm "Set OLLAMA_MAX_LOADED_MODELS=4 in Ollama's systemd service?"; then
            sudo mkdir -p "$(dirname "$OLLAMA_OVERRIDE")"
            sudo tee "$OLLAMA_OVERRIDE" > /dev/null << EOF
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=4"
EOF
            sudo systemctl daemon-reload
            sudo systemctl restart ollama 2>/dev/null || true
            success "OLLAMA_MAX_LOADED_MODELS=4 set"
        fi
    fi
else
    warn "Set OLLAMA_MAX_LOADED_MODELS=4 in your Ollama environment manually."
fi

# ---------------------------------------------------------------------------
# Step 13 — Optional: nginx
# ---------------------------------------------------------------------------

header "Step 13 — Reverse proxy (optional)"

echo "MatrixMouse's web UI runs on http://localhost:8080 by default."
echo "If you want to expose it over HTTPS or from another machine, a"
echo "reverse proxy (nginx, Caddy, Traefik, etc.) is recommended."
echo ""
echo "See docs/deployment/ for example configs."
echo ""

if confirm "Generate a basic nginx config template now?"; then
    NGINX_DIR="$INSTALL_DIR/nginx"
    mkdir -p "$NGINX_DIR/certs"
    prompt DOMAIN "Your domain name" "matrixmouse.example.com"

    cat > "$NGINX_DIR/nginx.conf" << EOF
# MatrixMouse nginx reverse proxy template
# Place TLS certs in nginx/certs/fullchain.pem and privkey.pem
# Create basic auth: htpasswd -c nginx/certs/.htpasswd youruser

events { worker_connections 1024; }

http {
    server {
        listen 80;
        server_name $DOMAIN;
        return 301 https://\$host\$request_uri;
    }

    server {
        listen 443 ssl;
        server_name $DOMAIN;

        ssl_certificate     /etc/nginx/certs/fullchain.pem;
        ssl_certificate_key /etc/nginx/certs/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;

        auth_basic           "MatrixMouse";
        auth_basic_user_file /etc/nginx/certs/.htpasswd;

        location / {
            proxy_pass         http://127.0.0.1:8080;
            proxy_http_version 1.1;
            proxy_set_header   Upgrade \$http_upgrade;
            proxy_set_header   Connection "upgrade";
            proxy_set_header   Host \$host;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }
    }
}
EOF
    success "nginx template written to $NGINX_DIR/nginx.conf"
    info "Caddy alternative: see docs/deployment/Caddyfile.example"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Installation complete"

echo ""
echo -e "${BOLD}What was set up:${RESET}"
echo "  MatrixMouse CLI:    $(command -v matrixmouse)"
echo "  Service binary:     $(command -v matrixmouse-service)"
echo "  Workspace:          $WORKSPACE_PATH"
echo "  Config:             $CONFIG_FILE"
echo "  Secrets (.env):     $ENV_FILE"
echo "  SSH key:            $AGENT_KEY_PATH"
echo "  GitHub PAT:         $AGENT_TOKEN_PATH"
echo "  Test runner image:  matrixmouse-test-runner"
if $HAS_SYSTEMD; then
echo "  Services:           matrixmouse  matrixmouse-test-runner"
fi
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo "  1. Pull the models you configured:"
echo "       ollama pull $CODER_MODEL"
echo "       ollama pull $PLANNER_MODEL"
echo "       ollama pull $SUMMARIZER_MODEL"
echo ""
echo "  2. Add a repo to the workspace:"
echo "       matrixmouse add-repo git@github.com:you/yourrepo.git"
echo ""
echo "  3. Create a task:"
echo "       matrixmouse tasks add"
echo ""
echo "  4. Check the agent is running:"
echo "       matrixmouse status"
if $HAS_SYSTEMD; then
echo "       sudo systemctl status matrixmouse"
fi
echo ""
echo "  5. Open the web UI:"
echo "       http://localhost:8080"
echo ""
if $HAS_SYSTEMD; then
echo -e "${YELLOW}Service management:${RESET}"
echo "  sudo systemctl start|stop|restart|status matrixmouse"
echo "  journalctl -u matrixmouse -f"
echo ""
fi
echo -e "${YELLOW}Note:${RESET} You were added to the '$MM_USER' group."
echo "  Log out and back in if CLI commands can't reach the workspace files."
echo ""
