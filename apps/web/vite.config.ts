import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";
import fs from "node:fs";

function readGatewayPort(): number {
  try {
    const portsPath = path.resolve(__dirname, "../../config/ports.json");
    const ports = JSON.parse(fs.readFileSync(portsPath, "utf8")) as {
      gateway?: number;
      vueFrontend?: number;
    };
    return Number(ports.gateway || 8401);
  } catch {
    return 8401;
  }
}

function readVuePort(): number {
  try {
    const portsPath = path.resolve(__dirname, "../../config/ports.json");
    const ports = JSON.parse(fs.readFileSync(portsPath, "utf8")) as {
      vueFrontend?: number;
    };
    return Number(ports.vueFrontend || 8402);
  } catch {
    return 8402;
  }
}

const gatewayPort = readGatewayPort();
const vuePort = readVuePort();

export default defineConfig({
  // 相对路径：便携包里 Electron 可用 loadFile(file://) 打开界面
  base: "./",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: vuePort,
    strictPort: true,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${gatewayPort}`,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: vuePort,
    strictPort: true,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${gatewayPort}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
