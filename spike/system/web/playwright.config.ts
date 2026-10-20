import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";
import type { Backend } from "./tests/fixtures";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const commit =
  process.env.GEARWELL_COMMIT ??
  execSync("git rev-parse HEAD", { cwd: repoRoot }).toString().trim();
const python = process.env.GEARWELL_PYTHON ?? "python3";

const backends: { name: Backend; serve: string; port: number }[] = [
  { name: "mocked", serve: "none", port: 4301 },
  { name: "fake", serve: "fake", port: 4302 },
  { name: "real", serve: "real", port: 4303 },
];

export default defineConfig<{ backend: Backend }>({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  metadata: { commit, step: process.env.GEARWELL_STEP ?? null },
  use: { trace: "off", screenshot: "off", video: "off" },
  projects: backends.map(({ name, port }) => ({
    name,
    metadata: { backend: commit },
    use: { baseURL: `http://127.0.0.1:${port}`, backend: name },
  })),
  webServer: backends.map(({ serve, port }) => ({
    command: `${python} web/serve.py --backend ${serve} --port ${port}`,
    cwd: repoRoot,
    env: { PYTHONPATH: "." },
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
  })),
});
