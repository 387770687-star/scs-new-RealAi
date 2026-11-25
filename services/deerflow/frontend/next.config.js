/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import { readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

import "./src/env.js";

const ports = JSON.parse(
  readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../../../config/ports.json"),
    "utf8",
  ),
);
const defaultGatewayURL = `http://127.0.0.1:${ports.gateway}`;

function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
import nextra from "nextra";

const withNextra = nextra({});

/** @type {import("next").NextConfig} */
const config = {
  output:
    process.env.NEXT_CONFIG_BUILD_OUTPUT === "standalone"
      ? "standalone"
      : undefined,
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  // Electron / 浏览器用 127.0.0.1 打开 dev 时，允许 HMR 与 dev 资源
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    const rewrites = [];
    const gatewayURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
      defaultGatewayURL,
    );

    if (!process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
      rewrites.push({
        source: "/api/langgraph",
        destination: `${gatewayURL}/api`,
      });
      rewrites.push({
        source: "/api/langgraph/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      rewrites.push({
        source: "/api/agents",
        destination: `${gatewayURL}/api/agents`,
      });
      rewrites.push({
        source: "/api/agents/:path*",
        destination: `${gatewayURL}/api/agents/:path*`,
      });
      rewrites.push({
        source: "/api/skills",
        destination: `${gatewayURL}/api/skills`,
      });
      rewrites.push({
        source: "/api/skills/:path*",
        destination: `${gatewayURL}/api/skills/:path*`,
      });
      rewrites.push({
        source: "/api/realai",
        destination: `${gatewayURL}/api/realai`,
      });
      rewrites.push({
        source: "/api/realai/:path*",
        destination: `${gatewayURL}/api/realai/:path*`,
      });

      // Catch-all for remaining gateway API routes (models, threads, memory,
      // mcp, artifacts, uploads, suggestions, runs, etc.) that don't have
      // their own NEXT_PUBLIC_* env var toggle.
      //
      // NOTE: this must come AFTER the /api/langgraph rewrite above so that
      // LangGraph-compatible routes keep their public prefix while Gateway
      // receives its native /api/* paths.
      rewrites.push({
        source: "/api/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    return rewrites;
  },
};

export default withNextra(config);
