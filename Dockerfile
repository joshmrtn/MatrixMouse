# Dockerfile
# MatrixMouse agent container
#
# Build:
#   docker build -t matrixmouse .
#
# The test runner image is built separately — see Dockerfile.testrunner

FROM python:3.12-slim

# Install git (required by git_tools) and curl (for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for the agent process
# The agent runs as 'mouse' — it should not run as root
RUN useradd --create-home --shell /bin/bash mouse

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[server]" \
    && pip install --no-cache-dir ollama fastapi uvicorn requests

# Copy source
COPY src/ ./src/

# The workspace (repo being worked on) is mounted at runtime
# The FIFO pipes are mounted at runtime from the host
RUN mkdir -p /workspace /run/matrixmouse-pipes

# Switch to non-root user
USER mouse

# Default command — can be overridden in docker-compose
CMD ["python", "-m", "matrixmouse", "run"]
