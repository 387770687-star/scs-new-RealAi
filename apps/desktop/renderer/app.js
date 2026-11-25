async function init() {
  const s = await window.realai.loadSettings();
  document.getElementById("vaultPath").value = s.obsidianVaultPath || "./vault";
  document.getElementById("apiKey").value = s.llm?.apiKey || "";
  document.getElementById("model").value = s.llm?.model || "MiniMax-M3";
  document.getElementById("baseUrl").value = s.llm?.baseUrl || "https://api.minimaxi.com/v1";
}

document.getElementById("saveBtn").addEventListener("click", async () => {
  const settings = {
    obsidianVaultPath: document.getElementById("vaultPath").value.trim(),
    llm: {
      provider: "minimax",
      apiKey: document.getElementById("apiKey").value.trim(),
      model: document.getElementById("model").value.trim(),
      baseUrl: document.getElementById("baseUrl").value.trim(),
    },
  };
  await window.realai.saveSettings(settings);
  document.getElementById("saveStatus").textContent = "已保存并同步到 DeerFlow 配置（Key 未写入 git）";
});

document.getElementById("openFolderBtn").addEventListener("click", () => {
  window.realai.openSettingsFolder();
});

document.getElementById("sendBtn").addEventListener("click", async () => {
  const btn = document.getElementById("sendBtn");
  const reply = document.getElementById("reply");
  const message = document.getElementById("prompt").value.trim();
  if (!message) return;
  btn.disabled = true;
  reply.textContent = "等待回复…";
  try {
    const res = await window.realai.sendChat(message);
    reply.textContent = res.content || JSON.stringify(res, null, 2);
  } catch (e) {
    reply.textContent = String(e.message || e);
  } finally {
    btn.disabled = false;
  }
});

init();
