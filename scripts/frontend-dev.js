#!/usr/bin/env node
/** Dev frontend with RealAi env (standalone, without Electron). */
const { spawn } = require("child_process");
const path = require("path");
const { PORTS } = require("./ports");

const frontendDir = path.join(__dirname, "..", "services", "deerflow", "frontend");
const env = {
  ...process.env,
  PORT: String(PORTS.frontend),
  DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: `http://127.0.0.1:${PORTS.gateway}`,
  DEER_FLOW_AUTH_DISABLED: "1",
};

const child = spawn("pnpm", ["dev"], {
  cwd: frontendDir,
  env,
  stdio: "inherit",
  shell: true,
});

child.on("exit", (code) => process.exit(code ?? 0));
