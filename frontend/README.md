# MatrixMouse Frontend

TypeScript-based web UI for MatrixMouse autonomous coding agent.

## Development

### Install Dependencies

```bash
cd frontend
npm install
```

### Run Development Server

```bash
npm run dev
```

This starts Vite dev server at http://localhost:3000 with hot reload.

### Build for Production

```bash
npm run build
```

Output goes to `dist/` directory.

### Run Tests

```bash
# Unit tests
npm run test

# E2E tests
npm run test:e2e

# Type checking
npm run typecheck

# Linting
npm run lint
```

## Project Structure

```
frontend/
├── src/
│   ├── main.ts                 # Application entry point
│   ├── app.ts                  # Main app component
│   ├── api/                    # API client & WebSocket
│   ├── components/             # Reusable UI components
│   ├── pages/                  # Page components (routes)
│   ├── state/                  # State management
│   ├── types/                  # TypeScript types
│   ├── utils/                  # Utility functions
│   └── styles/                 # CSS styles
├── public/                     # Static assets
├── index.html                  # HTML template
├── package.json                # Dependencies
├── tsconfig.json              # TypeScript config
└── vite.config.ts             # Build config
```

## Routing

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | Redirect | → `/channel/workspace` |
| `/channel/:scope` | ChannelPage | Workspace/repo conversation |
| `/task/:id` | TaskPage | Task detail & edit |
| `/tasks` | TasksPage | Task list |
| `/status` | StatusPage | Status dashboard |
| `/settings` | SettingsPage | Settings |

## Architecture

- **No framework**: Pure TypeScript + vanilla DOM
- **Component-based**: Reusable UI components
- **Type-safe**: Full TypeScript typing
- **Central state**: Single source of truth
- **Real-time**: WebSocket for live updates

## Testing Strategy

### Unit Tests (Vitest)
- API client
- State management
- Utility functions
- Component rendering

### Integration Tests (Playwright)
- Task management flows
- Conversation interactions
- Settings changes
- Modal interactions

### E2E Tests (Playwright)
- Complete user workflows
- Cross-page navigation
- WebSocket event handling

## Build & Deploy

Production builds are copied to `src/matrixmouse/web/` for serving by the Python backend.

```bash
npm run build
cp -r dist/* ../src/matrixmouse/web/
```

## License

MIT
