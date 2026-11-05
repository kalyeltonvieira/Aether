import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const frontend = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(frontend, '..');
const token = process.env.AETHER_OPERATOR_TOKEN ?? 'aether-e2e-test-token-not-for-production';
const python = process.env.AETHER_PYTHON_EXECUTABLE ?? 'python';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://localhost:3100', trace: 'retain-on-failure', screenshot: 'only-on-failure', browserName: 'chromium' },
  webServer: [
    { command: `${python} -m aether.interfaces.api --host 127.0.0.1 --port 8100 --auth-mode token --data-dir .aether-test-data --public-origin http://localhost:3100`, cwd: root, url: 'http://127.0.0.1:8100/health', reuseExistingServer: false, timeout: 60_000, env: { AETHER_OPERATOR_TOKEN: token, AETHER_AUTH_MODE: 'token' } },
    { command: 'pnpm dev --host 127.0.0.1 --port 3100 --strictPort', cwd: frontend, url: 'http://localhost:3100', reuseExistingServer: false, timeout: 60_000, env: { AETHER_API_TARGET: 'http://127.0.0.1:8100' } },
  ],
});
