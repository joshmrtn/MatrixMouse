#!/usr/bin/env bash
# install.sh
# MatrixMouse installation script
#
# Run as your NORMAL USER — not with sudo.
# The script uses sudo internally only where root is required.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh        ← do NOT prefix with sudo

set -euo pipefail

# ---------------------------------------------------------------------------
# Guard: refuse to run as root directly
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
INVOKING_USER="$USER"
INVOKING_HOME="$HOME"

# ---------------------------------------------------------------------------
# Step 1 — Prerequisites
# ---------------------------------------------------------------------------

header "Step 1 — Prerequisites"

# uv — install as current user, never as root
if command -v uv &>/dev/null; then
    success "uv found ($(uv --version))"
else
    warn "uv not found. Installing for current user..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$INVOKING_HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        success "uv installed"
    else
        fatal "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    fi
fi

# Clear any stale uv cache that might cause install failures
# This is safe — uv will re-download anything it needs
if [ -d "$INVOKING_HOME/.cache/uv/archive-v0" ]; then
    info "Clearing uv archive cache to prevent stale file errors..."
    rm -rf "$INVOKING_HOME/.cache/uv/archive-v0"
    success "uv cache cleared"
fi

if command -v docker &>/dev/null; then
    success "docker found"
else
    fatal "docker is not installed.\nInstall from: https://docs.docker.com/engine/install/"
fi

if command -v git &>/dev/null; then
    success "git found"
else
    fatal "git is not installed. Install with: sudo apt install git"
fi

if command -v ollama &>/dev/null; then
    success "ollama found"
    if ! ollama list &>/dev/null 2>&1; then
        warn "Ollama may not be running. Start with: ollama serve"
    fi
else
    warn "ollama not found. Install from https://ollama.com"
    warn "The agent will not work until Ollama is running with a model pulled."
fi

HAS_SYSTEMD=false
if command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1; then
    HAS_SYSTEMD=true
    success "systemd found"
else
    warn "systemd not found. Services must be started manually."
fi

# ---------------------------------------------------------------------------
# Step 2 — Install MatrixMouse (as current user, never root)
# ---------------------------------------------------------------------------

header "Step 2 — Installing MatrixMouse"

if uv tool list 2>/dev/null | grep -q "matrixmouse"; then
    success "matrixmouse already installed via uv"
    if confirm "Upgrade to latest version now?"; then
        uv tool upgrade matrixmouse
        success "matrixmouse upgraded"
    fi
else
    info "Installing matrixmouse from $INSTALL_DIR ..."
    # From local source during development.
    # Once on PyPI: uv tool install matrixmouse
    uv tool install "$INSTALL_DIR"
    success "matrixmouse installed"
fi

# Ensure uv tool binaries are on PATH for this session
export PATH="$INVOKING_HOME/.local/bin:$PATH"

if ! command -v matrixmouse &>/dev/null; then
    fatal "matrixmouse binary not found after install.\nExpected at $INVOKING_HOME/.local/bin/matrixmouse"
fi
if ! command -v matrixmouse-service &>/dev/null; then
    fatal "matrixmouse-service binary not found after install."
fi

success "matrixmouse:         $(command -v matrixmouse)"
success "matrixmouse-service: $(command -v matrixmouse-service)"

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

# Default to /var/lib — correct FHS location for service data,
# outside any home directory, compatible with ProtectHome=read-only.
prompt WORKSPACE_PATH \
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

# Grant the invoking user read access to the workspace so CLI commands
# like `matrixmouse tasks list` can read files when the service is down.
# Writes always go through the API, so the invoking user doesn't need write.
sudo chmod -R u=rwX,g=rX,o=rX "$WORKSPACE_PATH"

# Add invoking user to the matrixmouse group for read access
sudo usermod -aG "$MM_USER" "$INVOKING_USER"
warn "Added $INVOKING_USER to group '$MM_USER' for workspace read access."
warn "Log out and back in for group membership to take effect."

success "Workspace: $WORKSPACE_PATH (owned by $MM_USER)"

# ---------------------------------------------------------------------------
# Step 5 — Agent credentials
# ---------------------------------------------------------------------------

header "Step 5 — Agent credentials"

echo "MatrixMouse uses a dedicated bot account for git operations and PRs."
echo ""

DEFAULT_SECRETS="$INVOKING_HOME/.matrixmouse-secrets"
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
    fi
fi

# The service user needs to read the secrets.
# We make the secrets dir group-readable by the matrixmouse group,
# and add the service user to that group — or simply grant read via ACL.
# Simplest approach: set group ownership to matrixmouse, mode 640 on files.
sudo chown -R "$INVOKING_USER:$MM_USER" "$SECRETS_DIR"
find "$SECRETS_DIR" -type f -exec chmod 640 {} \;
chmod 750 "$SECRETS_DIR"
success "Secrets directory accessible to $MM_USER service user"

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

prompt CODER_MODEL      "Coder model (implementation)"           "qwen2.5-coder:14b"
prompt PLANNER_MODEL    "Planner model (design/critique)"        "qwen2.5:14b"
prompt SUMMARIZER_MODEL "Summarizer model (context compression)" "qwen2.5:3b"

echo ""
echo "Optional: coder cascade for escalation (comma-separated, smallest to largest)"
echo "Leave blank for no escalation."
prompt CODER_CASCADE "Coder cascade" ""

# ---------------------------------------------------------------------------
# Step 7 — Notifications (optional)
# ---------------------------------------------------------------------------

header "Step 7 — Notifications (optional)"

echo "MatrixMouse can send push notifications via ntfy when it needs attention."
echo "Leave blank to skip — configure later in config.toml."
echo ""

prompt NTFY_URL   "ntfy server URL (e.g. https://ntfy.sh)" ""
prompt NTFY_TOPIC "ntfy topic"                              "matrixmouse"

# ---------------------------------------------------------------------------
# Step 8 — Write configuration files
# ---------------------------------------------------------------------------

header "Step 8 — Configuration"

# .env secrets file — owned by invoking user, group-readable by service user
ENV_FILE="$SECRETS_DIR/matrixmouse.env"
if [ -f "$ENV_FILE" ]; then
    warn ".env already exists at $ENV_FILE — skipping."
    warn "Delete and re-run to regenerate."
else
    cat > "$ENV_FILE" << EOF
# MatrixMouse secrets environment file
# Loaded at service startup via the env_file config setting.
# Never commit this file or place it inside the workspace.

WORKSPACE_PATH=$WORKSPACE_PATH
SECRETS_PATH=$SECRETS_DIR
MATRIXMOUSE_AGENT_GH_KEY_FILE=$(basename "$AGENT_KEY_PATH")
MATRIXMOUSE_GITHUB_TOKEN_FILE=$(basename "$AGENT_TOKEN_PATH")
MM_SERVER_PORT=8080
EOF
    chmod 640 "$ENV_FILE"
    success "Written $ENV_FILE"
fi

# workspace config.toml — written as the service user so it can read/write it
CONFIG_FILE="$WORKSPACE_PATH/.matrixmouse/config.toml"
if [ -f "$CONFIG_FILE" ]; then
    warn "config.toml already exists — skipping."
else
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

    if [ -n "$NTFY_URL" ]; then
        NTFY_LINES="ntfy_url   = \"$NTFY_URL\"\nntfy_topic = \"$NTFY_TOPIC\""
    else
        NTFY_LINES="# ntfy_url   = \"https://ntfy.sh\"\n# ntfy_topic = \"matrixmouse\""
    fi

    sudo -u "$MM_USER" tee "$CONFIG_FILE" > /dev/null << EOF
# MatrixMouse workspace configuration
# Applies to all repos in this workspace.
# Repo-specific overrides: <repo>/.matrixmouse/config.toml
# Secrets go in the env_file below — not here.

env_file = "$ENV_FILE"

coder      = "$CODER_MODEL"
planner    = "$PLANNER_MODEL"
summarizer = "$SUMMARIZER_MODEL"
$CASCADE_LINE

agent_git_name  = "$AGENT_GIT_NAME"
agent_git_email = "$AGENT_GIT_EMAIL"

server_port = 8080
log_level   = "INFO"
log_to_file = false

$NTFY_LINES

priority_aging_rate      = 0.01
priority_max_aging_bonus = 0.3
EOF
    success "Written $CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# Step 9 — FIFO pipes
# ---------------------------------------------------------------------------

header "Step 9 — Test runner FIFO pipes"

FIFO_DIR="/tmp/matrixmouse-pipes"
sudo mkdir -p "$FIFO_DIR"
sudo chown "$MM_USER:$MM_USER" "$FIFO_DIR"
sudo chmod 750 "$FIFO_DIR"

[ -p "$FIFO_DIR/request.fifo" ] || sudo -u "$MM_USER" mkfifo "$FIFO_DIR/request.fifo"
[ -p "$FIFO_DIR/result.fifo"  ] || sudo -u "$MM_USER" mkfifo "$FIFO_DIR/result.fifo"
sudo chmod 660 "$FIFO_DIR"/*.fifo

success "FIFO pipes ready at $FIFO_DIR"

# ---------------------------------------------------------------------------
# Step 10 — Build test runner Docker image
# ---------------------------------------------------------------------------

header "Step 10 — Test runner Docker image"

DOCKERFILE_TR="$INSTALL_DIR/Dockerfile.testrunner"
[ -f "$DOCKERFILE_TR" ] || fatal "Dockerfile.testrunner not found at $INSTALL_DIR"

if docker image inspect matrixmouse-test-runner &>/dev/null 2>&1; then
    success "matrixmouse-test-runner image already exists"
    if confirm "Rebuild the test runner image?"; then
        docker build -f "$DOCKERFILE_TR" -t matrixmouse-test-runner "$INSTALL_DIR"
        success "matrixmouse-test-runner rebuilt"
    fi
else
    info "Building matrixmouse-test-runner image..."
    docker build -f "$DOCKERFILE_TR" -t matrixmouse-test-runner "$INSTALL_DIR"
    success "matrixmouse-test-runner image built"
fi

HASH_DIR="$INVOKING_HOME/.config/matrixmouse"
mkdir -p "$HASH_DIR"
sha256sum "$DOCKERFILE_TR" | awk '{print $1}' > "$HASH_DIR/testrunner.image.sha256"
success "Test runner image hash recorded"

# ---------------------------------------------------------------------------
# Step 11 — systemd services
# ---------------------------------------------------------------------------

header "Step 11 — systemd services"

MM_SERVICE_BIN="$(command -v matrixmouse-service)"
MM_TEST_RUNNER="$INSTALL_DIR/test_runner.sh"
chmod +x "$MM_TEST_RUNNER"

if $HAS_SYSTEMD; then

    # --- MatrixMouse agent service ---
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
Group=$MM_USER
WorkingDirectory=$WORKSPACE_PATH
ExecStart=$MM_SERVICE_BIN
Restart=on-failure
RestartSec=10
TimeoutStopSec=30

Environment=WORKSPACE_PATH=$WORKSPACE_PATH
EnvironmentFile=-$ENV_FILE

# Security hardening
# ProtectHome=read-only is safe because the workspace is in /var/lib,
# not under any user's home directory.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$WORKSPACE_PATH $SECRETS_DIR /tmp/matrixmouse-pipes

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
    warn "systemd not available. Start manually:"
    warn "  $MM_SERVICE_BIN &"
    warn "  FIFO_DIR=$FIFO_DIR WORKSPACE=$WORKSPACE_PATH $MM_TEST_RUNNER &"
fi

# ---------------------------------------------------------------------------
# Step 12 — Ollama configuration
# ---------------------------------------------------------------------------

header "Step 12 — Ollama configuration"

OLLAMA_OVERRIDE="/etc/systemd/system/ollama.service.d/override.conf"
if $HAS_SYSTEMD; then
    if [ -f "$OLLAMA_OVERRIDE" ] || \
       grep -q "OLLAMA_MAX_LOADED_MODELS" /etc/systemd/system/ollama.service 2>/dev/null; then
        success "OLLAMA_MAX_LOADED_MODELS already configured"
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
else
    warn "Set OLLAMA_MAX_LOADED_MODELS=4 in your Ollama environment manually."
fi

# ---------------------------------------------------------------------------
# Step 13 — Reverse proxy (optional)
# ---------------------------------------------------------------------------

header "Step 13 — Reverse proxy (optional)"

echo "The web UI is at http://localhost:8080 by default."
echo "A reverse proxy is recommended for HTTPS or remote access."
echo "See docs/deployment/ for nginx, Caddy, and Traefik examples."
echo ""

if confirm "Generate a basic nginx config template?"; then
    NGINX_DIR="$INSTALL_DIR/nginx"
    mkdir -p "$NGINX_DIR/certs"
    prompt DOMAIN "Your domain name" "matrixmouse.example.com"
    cat > "$NGINX_DIR/nginx.conf" << EOF
# MatrixMouse nginx reverse proxy template
# Place TLS certs in nginx/certs/ and set basic auth:
#   htpasswd -c nginx/certs/.htpasswd youruser

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
        }
    }
}
EOF
    success "nginx template written to $NGINX_DIR/nginx.conf"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Installation complete"

echo ""
echo -e "${BOLD}What was set up:${RESET}"
echo "  matrixmouse CLI:     $(command -v matrixmouse)"
echo "  matrixmouse-service: $(command -v matrixmouse-service)"
echo "  Workspace:           $WORKSPACE_PATH"
echo "  Config:              $CONFIG_FILE"
echo "  Secrets + .env:      $SECRETS_DIR"
echo "  Test runner image:   matrixmouse-test-runner"
if $HAS_SYSTEMD; then
echo "  Services:            matrixmouse  matrixmouse-test-runner"
fi
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo "  1. Pull the models you configured:"
echo "       ollama pull $CODER_MODEL"
echo "       ollama pull $PLANNER_MODEL"
echo "       ollama pull $SUMMARIZER_MODEL"
echo ""
echo "  2. Add a repo:"
echo "       matrixmouse add-repo git@github.com:you/repo.git"
echo ""
echo "  3. Create a task:"
echo "       matrixmouse tasks add"
echo ""
echo "  4. Check the agent:"
echo "       matrixmouse status"
echo "       curl http://localhost:8080/health"
if $HAS_SYSTEMD; then
echo "       sudo systemctl status matrixmouse"
echo "       journalctl -u matrixmouse -f"
fi
echo ""
echo -e "${YELLOW}Important:${RESET} You were added to the '$MM_USER' group."
echo "  Log out and back in for this to take effect."
echo ""
