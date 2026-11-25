const path = require("path");
const fs = require("fs");

function getRepoRoot() {
  return path.resolve(__dirname, "..", "..", "..");
}

function getAppRoot() {
  if (process.env.REALAI_APP_ROOT) {
    return path.resolve(process.env.REALAI_APP_ROOT);
  }
  return getRepoRoot();
}

function getDataRoot() {
  if (process.env.REALAI_DATA_ROOT) {
    return path.resolve(process.env.REALAI_DATA_ROOT);
  }
  return getRepoRoot();
}

function defaultDataRootSibling(appRoot) {
  return path.join(path.dirname(appRoot), "RealAiData");
}

function ensureDataLayout(dataRoot) {
  for (const sub of ["config", "vault", "skills/custom", "skills/public"]) {
    const p = path.join(dataRoot, sub);
    if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
  }
}

function isPortableMode() {
  return Boolean(process.env.REALAI_APP_ROOT && process.env.REALAI_DATA_ROOT);
}

module.exports = {
  getRepoRoot,
  getAppRoot,
  getDataRoot,
  defaultDataRootSibling,
  ensureDataLayout,
  isPortableMode,
};
