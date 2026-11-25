#!/usr/bin/env node
/** P0 smoke checks (no MiniMax key required for gateway/models). */
const http = require("http");
const { gatewayUrl } = require("./ports");

function get(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => resolve({ status: res.statusCode, body: data }));
      })
      .on("error", reject);
  });
}

async function main() {
  const checks = [];
  const fs = require("fs");
  const path = require("path");
  const root = path.resolve(__dirname, "..");
  checks.push(["deerflow vendored", fs.existsSync(path.join(root, "services/deerflow/LICENSE"))]);
  checks.push(["VENDOR.md", fs.existsSync(path.join(root, "services/deerflow/VENDOR.md"))]);
  checks.push(["electron app", fs.existsSync(path.join(root, "apps/desktop/electron/main.js"))]);
  checks.push(["settings example", fs.existsSync(path.join(root, "config/settings.example.json"))]);
  try {
    const models = await get(`${gatewayUrl()}/api/models`);
    checks.push(["gateway /api/models", models.status === 200]);
  } catch {
    checks.push(["gateway /api/models", false]);
  }
  let failed = 0;
  for (const [name, ok] of checks) {
    console.log(`${ok ? "OK" : "FAIL"} ${name}`);
    if (!ok) failed++;
  }
  process.exit(failed ? 1 : 0);
}

main();
