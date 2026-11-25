/** RealAi 本地服务端口（84** 段，单一来源：config/ports.json） */
const fs = require("fs");
const path = require("path");

const PORTS = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "config", "ports.json"), "utf8"),
);

const HOST = "127.0.0.1";

function gatewayUrl(host = HOST) {
  return `http://${host}:${PORTS.gateway}`;
}

function frontendUrl(host = HOST) {
  return `http://${host}:${PORTS.frontend}`;
}

function vueFrontendUrl(host = HOST) {
  return `http://${host}:${PORTS.vueFrontend || 8402}`;
}

function proxyUrl(host = HOST) {
  return `http://${host}:${PORTS.proxy}`;
}

module.exports = {
  PORTS,
  HOST,
  gatewayUrl,
  frontendUrl,
  vueFrontendUrl,
  proxyUrl,
};
