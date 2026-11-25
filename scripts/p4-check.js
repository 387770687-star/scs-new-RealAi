#!/usr/bin/env node
/** P4 smoke checks (paths, vault pagination, onboarding, health). */
const http = require("http");
const { PORTS } = require("./ports");

function request(method, path, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: "127.0.0.1",
      port: PORTS.gateway,
      path,
      method,
      headers,
    };
    const req = http.request(opts, (res) => {
      let raw = "";
      res.on("data", (c) => (raw += c));
      res.on("end", () => resolve({ status: res.statusCode, body: raw }));
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

function get(path) {
  return request("GET", path);
}

async function main() {
  const checks = [];
  try {
    const health = await get("/api/realai/health");
    const h = JSON.parse(health.body);
    checks.push(["health", health.status === 200 && h.data_root]);
    checks.push(["vault path", Boolean(h.vault_path)]);

    const onboard = await get("/api/realai/onboarding/status");
    const ob = JSON.parse(onboard.body);
    checks.push(["onboarding status", onboard.status === 200 && typeof ob.needed === "boolean"]);

    const files = await get("/api/realai/vault/files?limit=10&offset=0");
    const vf = JSON.parse(files.body);
    checks.push(["vault pagination", files.status === 200 && typeof vf.total === "number"]);
    checks.push(["vault limit cap", vf.limit <= 500]);
  } catch {
    checks.push(["gateway", false]);
  }

  const fs = require("fs");
  const path = require("path");
  checks.push(["pack script", fs.existsSync(path.join(__dirname, "pack-portable.js"))]);
  checks.push(["paths.js", fs.existsSync(path.join(__dirname, "..", "apps", "desktop", "electron", "paths.js"))]);

  let failed = 0;
  for (const [name, ok] of checks) {
    console.log(`${ok ? "OK" : "FAIL"} ${name}`);
    if (!ok) failed++;
  }
  process.exit(failed ? 1 : 0);
}

main();
