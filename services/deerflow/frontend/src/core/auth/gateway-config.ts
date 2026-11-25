import { z } from "zod";

import { frontendBaseUrl, gatewayBaseUrl, proxyBaseUrl } from "@/core/config/ports";

const gatewayConfigSchema = z.object({
  internalGatewayUrl: z.string().url(),
  trustedOrigins: z.array(z.string()).min(1),
});

export type GatewayConfig = z.infer<typeof gatewayConfigSchema>;

let _cached: GatewayConfig | null = null;

export function getGatewayConfig(): GatewayConfig {
  if (_cached) return _cached;

  const rawUrl = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  const internalGatewayUrl =
    rawUrl && rawUrl.length > 0
      ? rawUrl.replace(/\/+$/, "")
      : gatewayBaseUrl();

  const rawOrigins = process.env.DEER_FLOW_TRUSTED_ORIGINS?.trim();
  const trustedOrigins = rawOrigins
    ? rawOrigins
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
    : [frontendBaseUrl(), proxyBaseUrl()];

  _cached = gatewayConfigSchema.parse({ internalGatewayUrl, trustedOrigins });
  return _cached;
}
