/** RealAi 本地端口（与仓库根 config/ports.json 保持一致，修改请同步两处） */
export const REALAI_PORTS = {
  frontend: 8400,
  gateway: 8401,
  proxy: 8426,
  sandbox: 8480,
  browserless: 8432,
  qdrant: 8433,
  searxng: 8488,
} as const;

export function gatewayBaseUrl(host = "127.0.0.1") {
  return `http://${host}:${REALAI_PORTS.gateway}`;
}

export function frontendBaseUrl(host = "localhost") {
  return `http://${host}:${REALAI_PORTS.frontend}`;
}

export function proxyBaseUrl(host = "localhost") {
  return `http://${host}:${REALAI_PORTS.proxy}`;
}
