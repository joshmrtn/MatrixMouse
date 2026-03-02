#!/usr/bin/env bash
# test_runner.sh
#
# Host-side FIFO listener for MatrixMouse test execution.
# Runs alongside docker-compose.yml on the host machine.
#
# This script:
#   1. Creates the FIFO pipes if they don't exist
#   2. Listens on request.fifo for test requests from the agent container
#   3. Runs tests in a locked-down temporary Docker container
#   4. Writes results back to result.fifo
#
# Security properties:
#   - docker run invocation is entirely hardcoded
#   - Only "tests/" paths are accepted — anything else is rejected
#   - Test container runs with --network none (no internet access)
#   - Workspace is mounted read-only into the test container
#   - Test container is destroyed immediately after each run (--rm)
#   - This script lives on the host and cannot be modified by the agent
#
# Usage:
#   chmod +x test_runner.sh
#   ./test_runner.sh &        # run in background alongside docker-compose up
#
# Or run it as a systemd service — see docs/deployment.md
#
# Configuration (edit these variables):
FIFO_DIR="${FIFO_DIR:-/tmp/matrixmouse-pipes}"   # must match volume mount in docker-compose
WORKSPACE="${WORKSPACE:-$(pwd)/workspace}"        # absolute path to the repo on the host
TEST_IMAGE="${TEST_IMAGE:-matrixmouse-test-runner}" # docker image used for test execution
REQUEST_FIFO="$FIFO_DIR/request.fifo"
RESULT_FIFO="$FIFO_DIR/result.fifo"
TEST_TIMEOUT="${TEST_TIMEOUT:-300}"               # seconds before a test run is killed

set -euo pipefail

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [test_runner] $*" >&2
}

cleanup() {
    log "Shutting down."
    # FIFOs persist intentionally — they are recreated on next start
    exit 0
}
trap cleanup SIGINT SIGTERM

# Create FIFO directory
mkdir -p "$FIFO_DIR"
chmod 700 "$FIFO_DIR"

# Create FIFOs if they don't exist
[ -p "$REQUEST_FIFO" ] || mkfifo "$REQUEST_FIFO"
[ -p "$RESULT_FIFO"  ] || mkfifo "$RESULT_FIFO"

log "Listening on $REQUEST_FIFO"
log "Workspace: $WORKSPACE"
log "Test image: $TEST_IMAGE"

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

validate_path() {
    local path="$1"

    # Empty path means "run everything" — always allowed
    [ -z "$path" ] && return 0

    # Must start with "tests/" or be exactly "tests"
    if [[ "$path" != "tests" && "$path" != tests/* ]]; then
        log "REJECTED: path '$path' does not start with 'tests/'"
        return 1
    fi

    # No path traversal
    if [[ "$path" == *".."* ]]; then
        log "REJECTED: path '$path' contains '..'"
        return 1
    fi

    # No shell metacharacters
    if [[ "$path" =~ [^a-zA-Z0-9_./:\ -] ]]; then
        log "REJECTED: path '$path' contains disallowed characters"
        return 1
    fi

    return 0
}

# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

run_test() {
    local token="$1"
    local test_path="$2"

    log "Running tests. Token: $token Path: '${test_path:-tests}'"

    # Build the pytest command
    local pytest_args=("tests")
    if [ -n "$test_path" ]; then
        pytest_args=("$test_path")
    fi

    # Run the test container
    # All flags are hardcoded — the agent cannot influence this invocation
    local output
    local exit_code=0

    output=$(timeout "$TEST_TIMEOUT" docker run \
        --rm \
        --network none \
        --read-only \
        --tmpfs /tmp \
        --tmpfs /root/.pytest_cache \
        --memory 512m \
        --cpus 1.0 \
        --volume "$WORKSPACE:/workspace:ro" \
        --workdir /workspace \
        --name "mm-test-$(date +%s)-$$" \
        "$TEST_IMAGE" \
        python -m pytest "${pytest_args[@]}" \
            --tb=short \
            --no-header \
            -v \
        2>&1) || exit_code=$?

    log "Test run complete. Exit code: $exit_code Token: $token"

    # Write result back: first line is "<token> <exit_code>", rest is output
    printf '%s %d\n%s\n' "$token" "$exit_code" "$output" > "$RESULT_FIFO"
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

log "Ready. Waiting for test requests..."

while true; do
    # Block until a request arrives.
    # The read will return when the agent writes to the FIFO.
    # Using a subshell with a timeout prevents hanging forever if the
    # agent container is down and nobody ever writes to the pipe.
    if ! IFS= read -r -t 60 line < "$REQUEST_FIFO" 2>/dev/null; then
        # Timeout or error — loop back and wait again
        continue
    fi

    [ -z "$line" ] && continue

    # Parse: "<token> <path>" where path is optional
    token=$(echo "$line" | awk '{print $1}')
    test_path=$(echo "$line" | awk '{$1=""; print $0}' | xargs)

    # Validate token (8 hex chars)
    if ! [[ "$token" =~ ^[0-9a-f]{8}$ ]]; then
        log "REJECTED: invalid token format '$token'"
        continue
    fi

    # Validate test path
    if ! validate_path "$test_path"; then
        # Write an error result back so the agent isn't left hanging
        printf '%s 1\nERROR: Invalid test path rejected by host runner.\n' "$token" > "$RESULT_FIFO"
        continue
    fi

    run_test "$token" "$test_path"
done
