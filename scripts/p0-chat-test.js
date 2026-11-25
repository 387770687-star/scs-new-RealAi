#!/usr/bin/env node
/** One-shot MiniMax chat smoke test (P0). Does not print API keys. */
const { gatewayUrl } = require("./ports");
const BASE = gatewayUrl();

async function main() {
  const threadRes = await fetch(`${BASE}/api/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ metadata: { source: "realai-p0-test" } }),
  });
  if (!threadRes.ok) {
    console.error("FAIL create thread:", threadRes.status, await threadRes.text());
    process.exit(1);
  }
  const thread = await threadRes.json();
  const threadId = thread.thread_id || thread.id;
  console.log("thread:", threadId);

  const waitRes = await fetch(`${BASE}/api/threads/${threadId}/runs/wait`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      assistant_id: "lead_agent",
      input: { messages: [{ role: "user", content: "你好，请用一句话介绍你自己。" }] },
      context: { model_name: "minimax-m3", thinking_enabled: false },
    }),
    signal: AbortSignal.timeout(180000),
  });
  const bodyText = await waitRes.text();
  if (!waitRes.ok) {
    console.error("FAIL chat:", waitRes.status, bodyText.slice(0, 800));
    process.exit(1);
  }
  let body;
  try {
    body = JSON.parse(bodyText);
  } catch {
    console.error("FAIL invalid JSON:", bodyText.slice(0, 800));
    process.exit(1);
  }
  const messages = body.messages || [];
  const last = [...messages].reverse().find((m) => {
    const role = m.role || m.type;
    return role === "assistant" || role === "ai";
  });
  const content =
    typeof last?.content === "string"
      ? last.content
      : Array.isArray(last?.content)
        ? last.content.map((c) => (typeof c === "string" ? c : c.text || "")).join("\n")
        : body.error || JSON.stringify(body, null, 2);
  const redacted = String(content).replace(/sk-[A-Za-z0-9_-]+/g, "[REDACTED]");
  console.log("OK reply:", redacted.slice(0, 500));
}

main().catch((e) => {
  console.error("FAIL", e.message || e);
  process.exit(1);
});
