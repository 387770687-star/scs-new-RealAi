const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("realai", {
  loadSettings: () => ipcRenderer.invoke("settings:load"),
  saveSettings: (s) => ipcRenderer.invoke("settings:save", s),
  sendChat: (message) => ipcRenderer.invoke("chat:send", { message }),
  openSettingsFolder: () => ipcRenderer.invoke("shell:openSettingsFolder"),
  openVaultFolder: () => ipcRenderer.invoke("shell:openVaultFolder"),
  getPaths: () => ipcRenderer.invoke("realai:paths"),
  onMenuAction: (handler) => {
    const listener = (_event, action, payload) => handler(action, payload);
    ipcRenderer.on("menu:action", listener);
    return () => ipcRenderer.removeListener("menu:action", listener);
  },
});
