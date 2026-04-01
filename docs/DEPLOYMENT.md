# MatrixMouse Deployment Guide

This document describes how to build and deploy MatrixMouse with the TypeScript frontend.

---

## Quick Start

### Development Deployment

For development/testing where you're running in the current environment:

```bash
# Build and install to current environment
uv run poe deploy
```

Then restart the service:
```bash
sudo systemctl restart matrixmouse
```

### Production/System-Wide Deployment

For production deployments or system-wide installation (requires sudo):

```bash
# Force reinstall system-wide (replaces old force-upgrade.sh)
uv run poe force-install
```

This will:
1. Stop the MatrixMouse service
2. Reinstall from source with `uv tool install --force --no-cache`
3. Set correct permissions for systemd access
4. Restart the service
5. Follow logs automatically (Ctrl+C to exit)

**Note:** The first installation must be done with `./install.sh`. The `force-install` task is for upgrades only — it assumes symlinks are already in place from the initial install.

---

## Poe the Poet - Task Runner

MatrixMouse uses [Poe the Poet](https://poethepoet.natn.io/) for task automation, configured in `pyproject.toml`. All tasks are run with `uv run poe <task>`.

### View Available Tasks

```bash
# List all available tasks
uv run poe --help
```

### Common Tasks

| Task | Description |
|------|-------------|
| `poe deploy` | Full build + install (development environment) |
| `poe force-install` | System-wide install (production, requires sudo) |
| `poe build` | Build frontend + backend |
| `poe build-frontend` | Build frontend only |
| `poe build-backend` | Build Python package |
| `poe dev` | Run frontend + backend in parallel (dev mode) |
| `poe test` | Run all tests |
| `poe check` | Run lint + typecheck + test |
| `poe clean` | Remove build artifacts |
| `poe fresh` | Clean + reinstall everything |
| `poe restart` | Restart systemd service |
| `poe logs` | View service logs (follow mode) |

---

## Manual Steps

If you prefer manual control:

### 1. Build Frontend

```bash
cd frontend
npm install          # Only needed first time
npm run build
cp -r dist/* ../src/matrixmouse/web/
```

### 2. Build & Install Python Package

```bash
uv build
uv pip install --upgrade .
```

### 3. Restart Service

```bash
sudo systemctl restart matrixmouse
```

---

## Development Workflow

### Run Frontend + Backend Concurrently

```bash
# Starts both servers in parallel
uv run poe dev

# Frontend: http://localhost:3000
# Backend:  http://localhost:8080
```

### Run Separately

```bash
# Frontend only (in one terminal)
uv run poe dev-frontend

# Backend only (in another terminal)
uv run poe dev-backend
```

---

## Testing

### Run All Tests

```bash
# All tests
uv run poe test

# Python tests only
uv run poe test-python

# Frontend tests only
uv run poe test-frontend

# E2E tests (requires running server)
uv run poe test-frontend-e2e
```

### Run with Coverage

```bash
uv run poe test-python-cov
```

---

## Quality Checks

### Run All Checks

```bash
# Lint + typecheck + test
uv run poe check
```

### Individual Checks

```bash
# Linting
uv run poe lint          # All linters
uv run poe lint-python   # Python (ruff)
uv run poe lint-frontend # TypeScript (ESLint)

# Type checking
uv run poe typecheck          # All type checkers
uv run poe typecheck-python   # Python (pyright)
uv run poe typecheck-frontend # TypeScript (tsc)
```

---

## Environment Management

### Install Dependencies

```bash
# All dependencies (Python + frontend)
uv run poe install-all

# Python only
uv run poe install

# Frontend only
uv run poe install-frontend
```

### Clean Build Artifacts

```bash
# Clean all build artifacts
uv run poe clean

# Fresh reinstall (clean + install-all)
uv run poe fresh
```

---

## Service Management

```bash
# Start service
uv run poe start

# Stop service
uv run poe stop

# Restart service
uv run poe restart

# Check status
uv run poe status

# View logs (follow mode)
uv run poe logs
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      
      - name: Install Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
      
      - name: Install dependencies
        run: uv sync
      
      - name: Run tests
        run: uv run poe test
      
      - name: Build and deploy
        run: uv run poe deploy
      
      - name: Restart service
        run: sudo systemctl restart matrixmouse
```

### GitLab CI Example

```yaml
deploy:
  image: python:3.11-slim
  before_script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    - apt-get update && apt-get install -y nodejs npm
  script:
    - uv sync
    - uv run poe test
    - uv run poe deploy
    - sudo systemctl restart matrixmouse
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install Node.js for frontend build
RUN apt-get update && apt-get install -y nodejs npm

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY frontend/ ./frontend/
COPY src/ ./src/

# Install dependencies and build
RUN uv sync --no-dev
RUN cd frontend && npm install && npm run build
RUN rm -rf src/matrixmouse/web/* && cp -r frontend/dist/* src/matrixmouse/web/

# Install system-wide
RUN uv pip install .

CMD ["matrixmouse-service"]
```

---

## Troubleshooting

### Poe Not Found

```bash
# Install poe-the-poet
uv sync
```

### Frontend Build Fails

```bash
# Clear node_modules and reinstall
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

### Python Package Install Fails

```bash
# Clean build artifacts
uv run poe clean
uv sync
uv pip install --upgrade .
```

### Service Won't Start

```bash
# Check logs
uv run poe logs

# Check if port is in use
sudo lsof -i :8080

# Verify workspace exists
ls -la /var/lib/matrixmouse-workspace/
```

### SPA Routes Return 404

Make sure the frontend has been built and copied:

```bash
# Verify web directory has files
ls -la src/matrixmouse/web/

# Should contain:
# - index.html
# - assets/
```

---

## Task Reference

Complete list of Poe tasks:

### Build
- `build-frontend` - Build TypeScript frontend
- `build-backend` - Build Python package  
- `build` - Build both (sequence)

### Deploy
- `deploy` - Full build + install

### Development
- `dev-frontend` - Frontend dev server (:3000)
- `dev-backend` - Backend service (:8080)
- `dev` - Both in parallel

### Testing
- `test-python` - Pytest
- `test-python-cov` - Pytest with coverage
- `test-frontend` - Vitest unit tests
- `test-frontend-e2e` - Playwright E2E
- `test` - All tests (sequence)

### Quality
- `lint-python` - Ruff
- `lint-frontend` - ESLint
- `lint` - All linters
- `typecheck-python` - Pyright
- `typecheck-frontend` - TypeScript
- `typecheck` - All type checks
- `check` - Lint + typecheck + test

### Environment
- `install` - Sync Python deps
- `install-frontend` - npm install
- `install-all` - Both
- `clean` - Remove artifacts
- `fresh` - Clean + reinstall

### Service
- `start` - systemctl start
- `stop` - systemctl stop
- `restart` - systemctl restart
- `status` - systemctl status
- `logs` - journalctl -f

### Helpers
- `docs` - Open API docs in browser

---

## Version Information

- **MatrixMouse:** v0.4.6+
- **Frontend:** TypeScript + Vite
- **Backend:** Python 3.11+ + FastAPI
- **Task Runner:** Poe the Poet
- **Package Manager:** uv

---

## Additional Resources

- [Poe the Poet Documentation](https://poethepoet.natn.io/)
- [uv Package Manager](https://docs.astral.sh/uv/)
- [Vite Build Tool](https://vitejs.dev/)
