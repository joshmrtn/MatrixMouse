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

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVOKING_USER="$USER"

# ---------------------------------------------------------------------------
# Step 1 — Prerequisites
# ---------------------------------------------------------------------------

header "Step 1 — Prerequisites"

# uv — install as current user, never root
if command -v uv &>/dev/null; then
    success "uv found ($(uv --version))"
else
    warn "uv not found. Installing for current user..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
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
    # Once published to PyPI: uv tool install matrixmouse
    uv tool install "$INSTALL_DIR"
    success "matrixmouse installed"
fi

export PATH="$HOME/.local/bin:$PATH"
command -v matrixmouse &>/dev/null \
    || fatal "matrixmouse binary not found. Expected at $HOME/.local/bin/matrixmouse"
command -v matrixmouse-service &>/dev/null \
    || fatal "matrixmouse-service binary not found."

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
    sudo chown "$MM_USER:$MM_USER" "$ETC_DIR"
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

# ---------------------------------------------------------------------------
# Step 5 — Agent credentials
# ---------------------------------------------------------------------------

header "Step 5 — Agent credentials"

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

prompt_required AGENT_GIT_NAME  "Agent git commit name"  "MatrixMouse Bot"
prompt_required AGENT_GIT_EMAIL "Agent git commit email" "matrixmouse-bot@users.noreply.github.com"

# ---------------------------------------------------------------------------
# Step 6 — Workspace directory
# ---------------------------------------------------------------------------

header "Step 6 — Workspace directory"

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


# ---------------------------------------------------------------------------
# Step 7 — Model configuration
# ---------------------------------------------------------------------------

header "Step 7 — Model configuration"

echo "Enter Ollama model names for each role."
echo "Models must support tool calling. Check available: ollama list"
echo ""

prompt_required CODER_MODEL      "Coder model (implementation)"           "qwen3.5:4b"
prompt_required PLANNER_MODEL    "Planner model (design/critique)"        "qwen3.5:9b"
prompt_required SUMMARIZER_MODEL "Summarizer model (context compression)" "qwen3.5:4b"

echo ""
echo "Coder cascade: models to escalate through when stuck (comma-separated,"
echo "smallest to largest). Defaults to just the coder model (no escalation)."
prompt_required CODER_CASCADE "Coder cascade" "$CODER_MODEL"

# ---------------------------------------------------------------------------
# Step 8 — Notifications (optional)
# ---------------------------------------------------------------------------

header "Step 8 — Notifications (optional)"

echo "MatrixMouse can push notifications via ntfy when it needs attention."
echo "Leave blank to skip — configure later in /etc/matrixmouse/config.toml"
echo ""

prompt NTFY_URL   "ntfy server URL (e.g. https://ntfy.sh)" ""
prompt NTFY_TOPIC "ntfy topic"                              "matrixmouse"

# ---------------------------------------------------------------------------
# Step 9 — Write configuration files
# ---------------------------------------------------------------------------

header "Step 9 — Configuration files"

# .env secrets file — 600 matrixmouse:matrixmouse
ENV_FILE="$ETC_DIR/matrixmouse.env"

if sudo test -f "$ENV_FILE"; then
    success "$ENV_FILE already exists — skipping"
else
    sudo -u "$MM_USER" tee "$ENV_FILE" > /dev/null << EOF
# MatrixMouse environment / secrets file
# Loaded by the service at startup via the env_file config setting.
# Owned by matrixmouse:matrixmouse, mode 600.
# Never commit this file.

WORKSPACE_PATH=$WORKSPACE_PATH
SECRETS_PATH=$SECRETS_DIR
MATRIXMOUSE_AGENT_GH_KEY_FILE=$(basename "$AGENT_KEY_PATH")
MATRIXMOUSE_GITHUB_TOKEN_FILE=$(basename "$AGENT_TOKEN_PATH")
MM_SERVER_PORT=8080
EOF
    sudo chmod 600 "$ENV_FILE"
    success "Written $ENV_FILE"
fi

# workspace config.toml — 640 matrixmouse:matrixmouse
CONFIG_FILE="$WORKSPACE_PATH/.matrixmouse/config.toml"

if sudo test -f "$CONFIG_FILE"; then
    success "$CONFIG_FILE already exists — skipping"
else
    # Build coder_cascade TOML array
    IFS=',' read -ra CASCADE_MODELS <<< "$CODER_CASCADE"
    TOML_ARRAY=""
    for m in "${CASCADE_MODELS[@]}"; do
        m="$(echo "$m" | xargs)"
        TOML_ARRAY="${TOML_ARRAY}\"${m}\", "
    done
    CASCADE_LINE="coder_cascade = [${TOML_ARRAY%, }]"

    if [ -n "$NTFY_URL" ]; then
        NTFY_LINES="ntfy_url   = \"$NTFY_URL\"\nntfy_topic = \"$NTFY_TOPIC\""
    else
        NTFY_LINES="# ntfy_url   = \"https://ntfy.sh\"\n# ntfy_topic = \"matrixmouse\""
    fi

    sudo -u "$MM_USER" tee "$CONFIG_FILE" > /dev/null << EOF
# MatrixMouse workspace configuration
# Repo-specific overrides: <repo>/.matrixmouse/config.toml
# Secrets are in env_file — not here.

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

$(echo -e "$NTFY_LINES")

priority_aging_rate      = 0.01
priority_max_aging_bonus = 0.3
EOF
    success "Written $CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
# Step 10 — FIFO pipes
# ---------------------------------------------------------------------------

header "Step 10 — Test runner FIFO pipes"

FIFO_DIR="/tmp/matrixmouse-pipes"
sudo mkdir -p "$FIFO_DIR"
sudo chown "$MM_USER:$MM_USER" "$FIFO_DIR"
sudo chmod 750 "$FIFO_DIR"

sudo test -p "$FIFO_DIR/request.fifo" || sudo -u "$MM_USER" mkfifo "$FIFO_DIR/request.fifo"
sudo test -p "$FIFO_DIR/result.fifo"  || sudo -u "$MM_USER" mkfifo "$FIFO_DIR/result.fifo"
sudo chmod 660 "$FIFO_DIR/request.fifo" "$FIFO_DIR/result.fifo"

success "FIFO pipes ready at $FIFO_DIR"

# ---------------------------------------------------------------------------
# Step 11 — Build test runner Docker image
# ---------------------------------------------------------------------------

header "Step 11 — Test runner Docker image"

DOCKERFILE_TR="$INSTALL_DIR/Dockerfile.testrunner"
[ -f "$DOCKERFILE_TR" ] || fatal "Dockerfile.testrunner not found at $INSTALL_DIR"

# Hash stored in workspace so it's owned by the service user
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
MM_TEST_RUNNER="$INSTALL_DIR/test_runner.sh"
chmod +x "$MM_TEST_RUNNER"

if $HAS_SYSTEMD; then

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
# Workspace is under /var/lib so ProtectHome=read-only is safe —
# no service files live under any user's home directory.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$WORKSPACE_PATH $SECRETS_DIR /tmp/matrixmouse-pipes $ETC_DIR

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
# Step 13 — Ollama configuration
# ---------------------------------------------------------------------------

header "Step 13 — Ollama configuration"

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
# Step 14 — Reverse proxy (optional)
# ---------------------------------------------------------------------------

header "Step 14 — Reverse proxy (optional)"

echo "The web UI runs at http://localhost:8080 by default."
echo "See docs/deployment/ for nginx, Caddy, and Traefik examples."
echo ""

if confirm "Generate a basic nginx config template?"; then
    NGINX_DIR="$INSTALL_DIR/nginx"
    mkdir -p "$NGINX_DIR/certs"
    prompt_required DOMAIN "Your domain name" "matrixmouse.example.com"
    cat > "$NGINX_DIR/nginx.conf" << EOF
# MatrixMouse nginx reverse proxy template
# htpasswd -c nginx/certs/.htpasswd youruser

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
echo -e "${BOLD}Directory layout:${RESET}"
echo "  /etc/matrixmouse/          config, secrets (.env, SSH key, PAT)"
echo "  $WORKSPACE_PATH"
echo "    .matrixmouse/            tasks, repos, workspace config.toml"
echo "  /tmp/matrixmouse-pipes/    test runner FIFO pipes"
echo ""
echo -e "${BOLD}Binaries:${RESET}"
echo "  matrixmouse:         $(command -v matrixmouse)"
echo "  matrixmouse-service: $(command -v matrixmouse-service)"
echo ""
if $HAS_SYSTEMD; then
echo -e "${BOLD}Services:${RESET}"
echo "  matrixmouse               matrixmouse-test-runner"
echo ""
fi
echo -e "${BOLD}Next steps:${RESET}"
echo ""
echo "  1. Pull your models:"
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
echo "  4. Check status:"
echo "       matrixmouse status"
echo "       curl http://localhost:8080/health"
if $HAS_SYSTEMD; then
echo "       sudo systemctl status matrixmouse"
echo "       journalctl -u matrixmouse -f"
fi
echo ""
