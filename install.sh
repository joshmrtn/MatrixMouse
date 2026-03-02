#!/usr/bin/env bash
# install.sh
# MatrixMouse installation script
#
# Run this once on the host machine to set up everything needed
# to run MatrixMouse. Safe to re-run — skips steps already done.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Colours and output helpers
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
header()  { echo -e "\n${BOLD}$*${RESET}"; }

prompt() {
    # prompt <variable_name> <prompt_text> <default>
    local varname="$1"
    local text="$2"
    local default="$3"

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
    # confirm <prompt_text> — returns 0 for yes, 1 for no
    local text="$1"
    local answer
    read -rp "$(echo -e "${CYAN}?${RESET} ${text} [y/N]: ")" answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Step 1 — Prerequisites
# ---------------------------------------------------------------------------

header "Step 1 — Checking prerequisites"

check_cmd() {
    local cmd="$1"
    local install_hint="$2"
    if command -v "$cmd" &>/dev/null; then
        success "$cmd found"
    else
        fatal "$cmd is not installed. $install_hint"
    fi
}

check_cmd docker    "Install from https://docs.docker.com/engine/install/"
check_cmd git       "Install with: sudo apt install git"

# Docker Compose v2 (plugin) or v1 (standalone)
if docker compose version &>/dev/null 2>&1; then
    success "docker compose found"
elif command -v docker-compose &>/dev/null; then
    success "docker-compose found (v1)"
else
    fatal "Docker Compose not found. Install from https://docs.docker.com/compose/install/"
fi

# Ollama
if command -v ollama &>/dev/null; then
    success "ollama found"
    if ! ollama list &>/dev/null; then
        warn "Ollama is installed but the service may not be running. Start it with: ollama serve"
    fi
else
    warn "ollama not found. Install from https://ollama.com — required for model inference."
    warn "Continuing installation, but the agent will not work until Ollama is installed."
fi

# systemd (for test_runner service)
HAS_SYSTEMD=false
if command -v systemctl &>/dev/null && systemctl --version &>/dev/null 2>&1; then
    HAS_SYSTEMD=true
    success "systemd found"
else
    warn "systemd not found — test_runner.sh will not be installed as a service."
    warn "You will need to start it manually: ./test_runner.sh &"
fi

# ---------------------------------------------------------------------------
# Step 2 — Workspace directory
# ---------------------------------------------------------------------------

header "Step 2 — Workspace directory"

DEFAULT_WORKSPACE="$HOME/matrixmouse-workspace"
prompt WORKSPACE_PATH "Workspace directory (where repos will be cloned)" "$DEFAULT_WORKSPACE"
WORKSPACE_PATH="$(eval echo "$WORKSPACE_PATH")"  # expand ~ if present

if [ -d "$WORKSPACE_PATH" ]; then
    success "Workspace directory already exists: $WORKSPACE_PATH"
else
    mkdir -p "$WORKSPACE_PATH"
    success "Created workspace directory: $WORKSPACE_PATH"
fi

# Scaffold workspace-level .matrixmouse/
WORKSPACE_MM_DIR="$WORKSPACE_PATH/.matrixmouse"
mkdir -p "$WORKSPACE_MM_DIR"
success "Workspace .matrixmouse/ directory ready"

# ---------------------------------------------------------------------------
# Step 3 — Agent GitHub credentials
# ---------------------------------------------------------------------------

header "Step 3 — Agent GitHub credentials"

echo "MatrixMouse uses a dedicated GitHub bot account for commits and pushes."
echo "The SSH key for that account should be stored on this machine."
echo ""

prompt AGENT_GH_KEY_PATH \
    "Path to the agent's GitHub SSH private key" \
    "$HOME/.ssh/matrixmouse_agent_ed25519"

AGENT_GH_KEY_PATH="$(eval echo "$AGENT_GH_KEY_PATH")"

if [ -f "$AGENT_GH_KEY_PATH" ]; then
    success "SSH key found at $AGENT_GH_KEY_PATH"
else
    warn "SSH key not found at $AGENT_GH_KEY_PATH"
    warn "You can generate one with:"
    warn "  ssh-keygen -t ed25519 -C 'matrixmouse-bot' -f $AGENT_GH_KEY_PATH"
    warn "Then add the public key to your GitHub bot account."
    warn "Continuing — the key path will be saved to .env for when you're ready."
fi

prompt AGENT_GH_NAME  "Agent git commit name"  "MatrixMouse Bot"
prompt AGENT_GH_EMAIL "Agent git commit email" "matrixmouse-bot@users.noreply.github.com"

# ---------------------------------------------------------------------------
# Step 4 — Model configuration
# ---------------------------------------------------------------------------

header "Step 4 — Model configuration"

echo "MatrixMouse uses three model roles. Enter the Ollama model names to use."
echo "Models must support tool calling (check with: ollama show <model>)."
echo ""

prompt CODER_MODEL     "Coder model (implementation)"   "qwen2.5-coder:14b"
prompt PLANNER_MODEL   "Planner model (design/critique)" "qwen2.5:14b"
prompt SUMMARIZER_MODEL "Summarizer model (context compression)" "qwen2.5:3b"

echo ""
echo "Optional: configure a coder cascade for escalation (comma-separated, smallest to largest)"
echo "Example: qwen2.5-coder:7b,qwen2.5-coder:14b,qwen2.5-coder:30b"
echo "Leave empty to use only the coder model with no escalation."
prompt CODER_CASCADE "Coder cascade" ""

# ---------------------------------------------------------------------------
# Step 5 — Notification configuration (optional)
# ---------------------------------------------------------------------------

header "Step 5 — Notifications (optional)"

echo "MatrixMouse can send push notifications via ntfy when it needs your attention."
echo "Leave blank to skip — you can configure this later in config.toml."
echo ""

prompt NTFY_URL   "ntfy server URL (e.g. https://ntfy.sh or your self-hosted URL)" ""
prompt NTFY_TOPIC "ntfy topic name" "matrixmouse"

# ---------------------------------------------------------------------------
# Step 6 — Write config files
# ---------------------------------------------------------------------------

header "Step 6 — Writing configuration"

# .env file next to docker-compose.yml
ENV_FILE="$INSTALL_DIR/.env"
cat > "$ENV_FILE" << EOF
# MatrixMouse environment configuration
# Generated by install.sh — edit as needed

# Absolute path to the workspace directory on the host
WORKSPACE_PATH=$WORKSPACE_PATH

# Path to the agent's GitHub SSH private key on the host
MATRIXMOUSE_AGENT_GH_KEY=$AGENT_GH_KEY_PATH

# Ollama configuration
OLLAMA_HOST=http://host.docker.internal:11434
OLLAMA_MAX_LOADED_MODELS=4

# Test runner FIFO directory (must match FIFO_DIR in test_runner.sh)
MM_FIFO_DIR=/run/matrixmouse-pipes

# Test execution timeout in seconds
MM_TEST_TIMEOUT=360

# Web server port
MM_SERVER_PORT=8080
EOF
success "Written $ENV_FILE"

# Workspace-level config.toml
CONFIG_FILE="$WORKSPACE_MM_DIR/config.toml"
if [ -f "$CONFIG_FILE" ]; then
    warn "config.toml already exists — skipping to avoid overwriting."
    warn "To regenerate, delete $CONFIG_FILE and re-run install.sh"
else
    # Build coder_cascade line
    CASCADE_LINE=""
    if [ -n "$CODER_CASCADE" ]; then
        # Convert comma-separated to TOML array
        IFS=',' read -ra CASCADE_MODELS <<< "$CODER_CASCADE"
        TOML_ARRAY=""
        for model in "${CASCADE_MODELS[@]}"; do
            model="$(echo "$model" | xargs)"  # trim whitespace
            TOML_ARRAY="${TOML_ARRAY}\"${model}\", "
        done
        TOML_ARRAY="[${TOML_ARRAY%, }]"
        CASCADE_LINE="coder_cascade = $TOML_ARRAY"
    else
        CASCADE_LINE="# coder_cascade = [\"qwen2.5-coder:7b\", \"qwen2.5-coder:14b\", \"qwen2.5-coder:30b\"]"
    fi

    # Build ntfy lines
    NTFY_LINES=""
    if [ -n "$NTFY_URL" ]; then
        NTFY_LINES="ntfy_url = \"$NTFY_URL\"
ntfy_topic = \"$NTFY_TOPIC\""
    else
        NTFY_LINES="# ntfy_url = \"https://ntfy.sh\"
# ntfy_topic = \"matrixmouse\""
    fi

    cat > "$CONFIG_FILE" << EOF
# MatrixMouse workspace configuration
# This file applies to all repos in this workspace.
# Repo-specific overrides go in <repo>/.matrixmouse/config.toml

# Models
coder = "$CODER_MODEL"
planner = "$PLANNER_MODEL"
summarizer = "$SUMMARIZER_MODEL"
$CASCADE_LINE

# Agent git identity (used for all commits made by the agent)
agent_git_name = "$AGENT_GH_NAME"
agent_git_email = "$AGENT_GH_EMAIL"

# Web UI
server_port = 8080

# Logging
log_level = "INFO"
log_to_file = false

# Notifications
$NTFY_LINES
EOF
    success "Written $CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# Step 7 — FIFO directory
# ---------------------------------------------------------------------------

header "Step 7 — FIFO pipes"

FIFO_DIR="/tmp/matrixmouse-pipes"
mkdir -p "$FIFO_DIR"
chmod 700 "$FIFO_DIR"

[ -p "$FIFO_DIR/request.fifo" ] || mkfifo "$FIFO_DIR/request.fifo"
[ -p "$FIFO_DIR/result.fifo"  ] || mkfifo "$FIFO_DIR/result.fifo"
success "FIFO pipes ready at $FIFO_DIR"

# ---------------------------------------------------------------------------
# Step 8 — Build Docker images
# ---------------------------------------------------------------------------

header "Step 8 — Building Docker images"

info "Building matrixmouse image..."
docker build -t matrixmouse "$INSTALL_DIR"
success "matrixmouse image built"

info "Building matrixmouse-test-runner image..."
docker build -f "$INSTALL_DIR/Dockerfile.testrunner" -t matrixmouse-test-runner "$INSTALL_DIR"
success "matrixmouse-test-runner image built"

# ---------------------------------------------------------------------------
# Step 9 — test_runner.sh service
# ---------------------------------------------------------------------------

header "Step 9 — Test runner"

# Make sure test_runner.sh is executable
chmod +x "$INSTALL_DIR/test_runner.sh"

if $HAS_SYSTEMD; then
    SERVICE_FILE="/etc/systemd/system/matrixmouse-test-runner.service"

    if [ -f "$SERVICE_FILE" ]; then
        success "test_runner systemd service already exists — skipping"
    else
        info "Installing test_runner.sh as a systemd service..."
        sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=MatrixMouse test runner
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=$INSTALL_DIR/test_runner.sh
Restart=always
RestartSec=5
User=$USER
Environment=FIFO_DIR=$FIFO_DIR
Environment=WORKSPACE=$WORKSPACE_PATH
Environment=TEST_IMAGE=matrixmouse-test-runner

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl daemon-reload
        sudo systemctl enable matrixmouse-test-runner
        sudo systemctl start matrixmouse-test-runner
        success "test_runner service installed and started"
    fi
else
    warn "To start the test runner manually:"
    warn "  FIFO_DIR=$FIFO_DIR WORKSPACE=$WORKSPACE_PATH $INSTALL_DIR/test_runner.sh &"
fi

# ---------------------------------------------------------------------------
# Step 10 — nginx template
# ---------------------------------------------------------------------------

header "Step 10 — nginx configuration"

NGINX_DIR="$INSTALL_DIR/nginx"
mkdir -p "$NGINX_DIR/certs"

NGINX_CONF="$NGINX_DIR/nginx.conf"
if [ -f "$NGINX_CONF" ]; then
    success "nginx.conf already exists — skipping"
else
    prompt DOMAIN "Your domain name (for nginx config)" "matrixmouse.example.com"

    cat > "$NGINX_CONF" << EOF
# nginx.conf — MatrixMouse reverse proxy
# Replace YOUR_DOMAIN with your actual domain.
# Place your TLS certificate and key in nginx/certs/:
#   nginx/certs/fullchain.pem
#   nginx/certs/privkey.pem
#
# To use Authelia for authentication:
#   1. Add Authelia to docker-compose.yml
#   2. Uncomment the auth_request lines below

events {
    worker_connections 1024;
}

http {
    # Redirect HTTP to HTTPS
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
        ssl_ciphers         HIGH:!aNULL:!MD5;

        # Basic auth — replace with Authelia when ready
        auth_basic           "MatrixMouse";
        auth_basic_user_file /etc/nginx/certs/.htpasswd;

        # Authelia forward auth (uncomment to use instead of basic auth):
        # auth_request /authelia;
        # auth_request_set \$target_url https://\$http_host\$request_uri;
        # error_page 401 =302 https://auth.$DOMAIN/?rd=\$target_url;

        location / {
            proxy_pass         http://matrixmouse:8080;
            proxy_http_version 1.1;

            # Required for websocket support
            proxy_set_header   Upgrade \$http_upgrade;
            proxy_set_header   Connection "upgrade";

            proxy_set_header   Host \$host;
            proxy_set_header   X-Real-IP \$remote_addr;
            proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto \$scheme;

            # Increase timeouts for long-running agent operations
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }
    }
}
EOF
    success "Written $NGINX_CONF"
    info "To create a basic auth password file:"
    info "  htpasswd -c nginx/certs/.htpasswd yourusername"
    info "Place your TLS certs in nginx/certs/fullchain.pem and nginx/certs/privkey.pem"
fi

# ---------------------------------------------------------------------------
# Step 11 — Ollama OLLAMA_MAX_LOADED_MODELS
# ---------------------------------------------------------------------------

header "Step 11 — Ollama configuration"

OLLAMA_SERVICE="/etc/systemd/system/ollama.service"
OLLAMA_OVERRIDE="/etc/systemd/system/ollama.service.d/override.conf"

if $HAS_SYSTEMD && [ -f "$OLLAMA_SERVICE" ]; then
    if grep -q "OLLAMA_MAX_LOADED_MODELS" "$OLLAMA_SERVICE" 2>/dev/null || \
       [ -f "$OLLAMA_OVERRIDE" ]; then
        success "OLLAMA_MAX_LOADED_MODELS already configured"
    else
        if confirm "Set OLLAMA_MAX_LOADED_MODELS=4 in Ollama's systemd service?"; then
            sudo mkdir -p "$(dirname "$OLLAMA_OVERRIDE")"
            sudo tee "$OLLAMA_OVERRIDE" > /dev/null << EOF
[Service]
Environment="OLLAMA_MAX_LOADED_MODELS=4"
EOF
            sudo systemctl daemon-reload
            sudo systemctl restart ollama
            success "Ollama configured with OLLAMA_MAX_LOADED_MODELS=4"
        fi
    fi
else
    warn "Could not find Ollama systemd service."
    warn "Set OLLAMA_MAX_LOADED_MODELS=4 in your Ollama environment manually."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Installation complete"

echo ""
echo -e "${BOLD}What was set up:${RESET}"
echo "  Workspace:        $WORKSPACE_PATH"
echo "  Config:           $WORKSPACE_MM_DIR/config.toml"
echo "  Environment:      $INSTALL_DIR/.env"
echo "  FIFO pipes:       $FIFO_DIR"
echo "  Docker images:    matrixmouse, matrixmouse-test-runner"
echo "  nginx template:   $NGINX_CONF"
if $HAS_SYSTEMD; then
echo "  test_runner:      systemd service (matrixmouse-test-runner)"
fi
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo "  1. Add your TLS certs to nginx/certs/ and create a .htpasswd file:"
echo "       htpasswd -c nginx/certs/.htpasswd yourusername"
echo ""
echo "  2. If your agent SSH key doesn't exist yet, generate it:"
echo "       ssh-keygen -t ed25519 -C 'matrixmouse-bot' -f $AGENT_GH_KEY_PATH"
echo "     Then add the public key to your GitHub bot account's SSH keys."
echo ""
echo "  3. Clone a repo into the workspace and initialise it:"
echo "       cd $WORKSPACE_PATH"
echo "       git clone git@github.com:you/yourrepo.git"
echo "       docker compose run --rm matrixmouse python -m matrixmouse init --repo yourrepo"
echo ""
echo "  4. Add tasks to <repo>/.matrixmouse/tasks.json"
echo ""
echo "  5. Start MatrixMouse:"
echo "       docker compose up -d"
echo ""
echo "  6. Open the web UI at https://$DOMAIN (or http://localhost:8080 for local access)"
echo ""
echo -e "${YELLOW}Remember:${RESET} test_runner.sh must be running on the host for isolated test execution."
if $HAS_SYSTEMD; then
echo "  Check its status with: sudo systemctl status matrixmouse-test-runner"
fi
echo ""
