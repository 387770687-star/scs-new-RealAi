#!/usr/bin/env node
// Use macOS's archive extractor for Electron's framework symlinks and resources.
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const { spawnSync } = require("node:child_process");

async function main() {
  if (process.platform !== "darwin") throw new Error("This installer requires macOS.");
  const desktopDir = path.resolve(__dirname, "../apps/desktop");
  const packagePath = require.resolve("electron/package.json", { paths: [desktopDir] });
  const electronRequire = createRequire(packagePath);
  const electronDir = path.dirname(packagePath);
  const { version } = electronRequire("./package.json");
  const { downloadArtifact } = electronRequire("@electron/get");
  const archive = await downloadArtifact({
    version,
    artifactName: "electron",
    platform: "darwin",
    arch: process.arch,
    checksums: electronRequire("./checksums.json"),
  });
  const tempDir = fs.mkdtempSync(path.join(electronDir, ".mac-install-"));
  const binary = "Electron.app/Contents/MacOS/Electron";
  try {
    const result = spawnSync("/usr/bin/ditto", ["-x", "-k", archive, tempDir], { stdio: "inherit" });
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(`Electron extraction failed (${result.status}).`);
    fs.accessSync(path.join(tempDir, binary), fs.constants.X_OK);
    if (fs.readFileSync(path.join(tempDir, "version"), "utf8").trim().replace(/^v/, "") !== version) {
      throw new Error("Electron archive version does not match the dependency lock.");
    }
    const distDir = path.join(electronDir, "dist");
    fs.rmSync(distDir, { recursive: true, force: true });
    fs.renameSync(tempDir, distDir);
    fs.writeFileSync(path.join(electronDir, "path.txt"), binary);
    console.log(`[setup] Electron ${version} (${process.arch}) 已安装。`);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
