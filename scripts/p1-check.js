#!/usr/bin/env node
/** P1 smoke checks for RealAi APIs. */
const http = require("http");
const { PORTS, gatewayUrl } = require("./ports");

function post(path, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: PORTS.gateway,
        path,
        method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => resolve({ status: res.statusCode, body: raw }));
      },
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function get(path) {
  return new Promise((resolve, reject) => {
    http
      .get(`${gatewayUrl()}${path}`, (res) => {
        let raw = "";
        res.on("data", (c) => (raw += c));
        res.on("end", () => resolve({ status: res.statusCode, body: raw }));
      })
      .on("error", reject);
  });
}

async function main() {
  const checks = [];
  try {
    const files = await get("/api/realai/vault/files");
    checks.push(["vault/files", files.status === 200]);
    const ask = await post("/api/realai/light/ask", {
      query: "去年采用了什么最新技术策略，降低了多少成本？",
      web_search_mode: "off",
    });
    const askBody = JSON.parse(ask.body);
    checks.push(["light/ask", ask.status === 200 && askBody.evidence?.items?.length > 0]);
    checks.push(["light/kb+data", askBody.evidence.items.some((i) => i.type === "kb")]);
    const report = await post("/api/realai/report/run", {
      goal: "P1复盘测试报告",
      web_search_mode: "off",
    });
    const repBody = JSON.parse(report.body);
    checks.push(["report/run", report.status === 200 && !!repBody.vault_path]);
  } catch (e) {
    checks.push(["gateway reachable", false]);
  }
  let failed = 0;
  for (const [name, ok] of checks) {
    console.log(`${ok ? "OK" : "FAIL"} ${name}`);
    if (!ok) failed++;
  }
  process.exit(failed ? 1 : 0);
}

main();
