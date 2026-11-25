#!/usr/bin/env node
/** P3 smoke checks (Skill CRUD list + report skill binding). */
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

function postJson(path, obj) {
  const data = JSON.stringify(obj);
  return request("POST", path, data, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(data),
  });
}

async function main() {
  const checks = [];
  try {
    const list = await get("/api/realai/skills");
    const parsed = JSON.parse(list.body);
    checks.push(["skills list", list.status === 200 && parsed.count >= 4]);
    const ids = new Set((parsed.skills || []).map((s) => s.id));
    checks.push(["preset weekly-digest", ids.has("weekly-digest")]);
    checks.push(["preset document-highlights", ids.has("document-highlights")]);

    const report = await postJson("/api/realai/report/run", {
      goal: "P3 Skill 冒烟",
      step_confirm: true,
      confirmed: false,
    });
    const rep = JSON.parse(report.body);
    checks.push([
      "report strategic skills",
      rep.phase === "await_outline_confirm" &&
        rep.skills?.writer === "strategic-planning-writer" &&
        rep.skills?.review === "strategic-planning-reviewer" &&
        rep.skills?.researcher === "strategic-planning-researcher",
    ]);
    checks.push([
      "report seven agents",
      Array.isArray(rep.agent_progress) &&
        rep.agent_progress.length === 7 &&
        rep.agent_progress[0]?.id === "intake" &&
        rep.agent_progress[1]?.id === "researcher",
    ]);

    const badExec = await postJson("/api/realai/skills/not-a-valid-id/execute", { input: "x" });
    checks.push(["invalid execute blocked", badExec.status === 404 || badExec.status === 400]);
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
