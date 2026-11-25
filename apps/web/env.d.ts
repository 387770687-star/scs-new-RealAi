/// <reference types="vite/client" />

interface RealAiDesktopBridge {
  loadSettings?: () => Promise<unknown>;
  saveSettings?: (s: unknown) => Promise<{ ok: boolean }>;
  getPaths?: () => Promise<{ appRoot: string; dataRoot: string; portable: boolean }>;
  openVaultFolder?: () => Promise<void>;
  openSettingsFolder?: () => Promise<void>;
  onMenuAction?: (handler: (action: string, payload?: unknown) => void) => () => void;
}

interface Window {
  realai?: RealAiDesktopBridge;
}

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
