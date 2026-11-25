const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { ensureLocalConfig } = require("../scripts/ensure-config");
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "realai-setup-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, "config"), { recursive: true });
  fs.mkdirSync(path.join(root, "services/deerflow"), { recursive: true });
  fs.writeFileSync(path.join(root, "config/settings.example.json"), JSON.stringify({ llm: { apiKey: "" }, obsidianVaultPath: "./vault" }));
  fs.writeFileSync(path.join(root, "services/deerflow/config.example.yaml"), "models: []\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n");
  return root;
}
test("fresh checkout initializes local config with an empty model key", (t) => {
  const root = fixture(t);
  ensureLocalConfig(root);
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, "config/settings.json"))).llm.apiKey, "");
  assert.ok(fs.existsSync(path.join(root, "services/deerflow/config.yaml")));
  assert.ok(fs.existsSync(path.join(root, "vault")));
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root, "config/extensions_config.json"))), { mcpServers: {}, skills: {} });
});
test("repeated setup preserves local settings, credentials and gateway config", (t) => {
  const root = fixture(t);
  ensureLocalConfig(root);
  const names = ["config/settings.json", "config/extensions_config.json", "services/deerflow/config.yaml", "services/deerflow/.env"];
  for (const name of names) fs.writeFileSync(path.join(root, name), `existing:${name}`);
  ensureLocalConfig(root);
  for (const name of names) assert.equal(fs.readFileSync(path.join(root, name), "utf8"), `existing:${name}`);
});
test("external data root receives settings and vault, with code config in app root", (t) => {
  const root = fixture(t);
  const data = path.join(root, "separate-data");
  ensureLocalConfig(root, data);
  assert.ok(fs.existsSync(path.join(data, "config/settings.json")));
  assert.ok(fs.existsSync(path.join(data, "vault")));
  assert.equal(fs.existsSync(path.join(root, "config/settings.json")), false);
  assert.ok(fs.existsSync(path.join(root, "services/deerflow/config.yaml")));
});
