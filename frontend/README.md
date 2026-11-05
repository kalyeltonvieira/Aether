# AETHER Studio frontend

React + TypeScript + Vite client for the `/api/v1` and `/ws` Studio contract. The Vite dev server proxies API and WebSocket requests to `127.0.0.1:8000` and serves on port `3000`.

```bash
pnpm install
pnpm --dir frontend dev --host 0.0.0.0 --port 3000
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
```

The browser uses `credentials: include`, keeps CSRF only in memory, and never persists an installation token. Managed Manus OAuth is the default. Sessions with `role: reader` can inspect all read pages but see write, process, and configuration actions disabled; only an explicit `operator` session can mutate the server.

No fixtures are loaded by the application. Test fixtures exist only in `src/tests/` and are clearly mocked.
