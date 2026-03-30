# MatrixMouse Frontend

TypeScript-based web UI for MatrixMouse.

## Development

### Install Dependencies

```bash
cd frontend
npm install
```

Or using uv:
```bash
uv run --with esbuild --with typescript npm install
```

### Build

```bash
npm run build
```

Or:
```bash
uv run matrixmouse-frontend-build
```

### Type Check

```bash
npm run typecheck
```

## Project Structure

```
frontend/
├── src/
│   ├── index.ts           # Main entry point
│   ├── types/             # TypeScript type definitions
│   ├── api/               # API client and WebSocket handler
│   ├── state/             # State management
│   ├── components/        # UI components
│   └── utils/             # Utility functions
├── tests/                 # Unit tests (Vitest)
├── ui.template.html       # HTML template (optional)
├── build.ts               # Build script
└── package.json
```

## Migration from JavaScript

The old `ui.js`, `ui.css`, and `ui.html` files are still in `src/matrixmouse/web/` for backwards compatibility.

To migrate:
1. Edit TypeScript sources in `frontend/src/`
2. Run `npm run build`
3. The built file will be in `src/matrixmouse/web/ui.html`

## Testing

Unit tests (coming soon):
```bash
npm test
```

E2E tests with Playwright:
```bash
cd tests/frontend
pytest
```
