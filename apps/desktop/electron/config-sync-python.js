const path = require("path");
const fs = require("fs");
const { spawnSync } = require("child_process");

function syncDeerFlowConfigViaPython(appRoot) {
  const backend = path.join(appRoot, "services", "deerflow", "backend");
  const dataRoot = process.env.REALAI_DATA_ROOT || appRoot;
  const uv =
    process.env.UV_EXE ||
    (fs.existsSync(path.join(process.env.USERPROFILE || "", ".local", "bin", "uv.exe"))
      ? path.join(process.env.USERPROFILE, ".local", "bin", "uv.exe")
      : "uv");
  const embeddedPy = path.join(appRoot, "runtime", "venv", "Scripts", "python.exe");
  const env = {
    ...process.env,
    REALAI_APP_ROOT: appRoot,
    REALAI_DATA_ROOT: dataRoot,
    REALAI_REPO_ROOT: appRoot,
    DEER_FLOW_PROJECT_ROOT: path.join(appRoot, "services", "deerflow"),
  };
  const res = fs.existsSync(embeddedPy)
    ? spawnSync(embeddedPy, ["-m", "realai.config_sync"], { cwd: backend, env, encoding: "utf8" })
    : spawnSync(uv, ["run", "python", "-m", "realai.config_sync"], {
        cwd: backend,
        env,
        encoding: "utf8",
      });
  if (res.status !== 0) {
    console.warn("[realai] Python config_sync failed:", res.stderr || res.stdout);
  }
}

module.exports = { syncDeerFlowConfigViaPython };
