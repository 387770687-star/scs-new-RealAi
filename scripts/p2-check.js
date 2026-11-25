#!/usr/bin/env node
/** P2 smoke checks (SQL readonly + report docx). */
const http = require("http");
const { PORTS } = require("./ports");

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

async function main() {
  const checks = [];
  try {
    const bad = await post("/api/realai/data/sql", { sql: "DELETE FROM x" });
    checks.push(["sql blocks DELETE", bad.status === 400]);
    const report = await post("/api/realai/report/run", {
      goal: "P2油气管道管网工程检查",
      confirmed: true,
    });
    const body = JSON.parse(report.body);
    checks.push(["report docx path", !!body.vault_path_docx]);
    checks.push(["pipeline review", body.review?.pipeline_adapted === true]);
  } catch {
    checks.push(["gateway", false]);
  }
  let failed = 0;
  for (const [name, ok] of checks) {
    console.log(`${ok ? "OK" : "FAIL"} ${name}`);
    if (!ok) failed++;
  }
  process.exit(failed ? 1 : 0);
}

main();
