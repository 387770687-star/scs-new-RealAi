"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

import type { EvidencePack } from "./types";

const STORAGE_KEY = "realai.ui";

type RealAiUiState = {
  webSearchEnabled: boolean;
  evidenceOpen: boolean;
  lastEvidence: EvidencePack | null;
  vaultBanner: string | null;
  vaultPreviewPath: string | null;
};

type RealAiContextValue = RealAiUiState & {
  setWebSearchEnabled: (v: boolean) => void;
  openEvidence: (pack: EvidencePack | null) => void;
  closeEvidence: () => void;
  setVaultBanner: (msg: string | null) => void;
  openVaultPreview: (path: string) => void;
  closeVaultPreview: () => void;
};

const defaultState: RealAiUiState = {
  webSearchEnabled: false,
  evidenceOpen: false,
  lastEvidence: null,
  vaultBanner: null,
  vaultPreviewPath: null,
};

function loadState(): RealAiUiState {
  if (typeof window === "undefined") return defaultState;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState;
    const parsed = JSON.parse(raw) as Partial<RealAiUiState>;
    return { ...defaultState, ...parsed, evidenceOpen: false };
  } catch {
    return defaultState;
  }
}

const RealAiContext = createContext<RealAiContextValue | null>(null);

export function RealAiProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<RealAiUiState>(() => loadState());

  const persist = useCallback((next: RealAiUiState) => {
    setState(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          webSearchEnabled: next.webSearchEnabled,
          lastEvidence: next.lastEvidence,
        }),
      );
    }
  }, []);

  const value = useMemo<RealAiContextValue>(
    () => ({
      ...state,
      setWebSearchEnabled: (webSearchEnabled) =>
        persist({ ...state, webSearchEnabled }),
      openEvidence: (pack) =>
        persist({
          ...state,
          lastEvidence: pack,
          evidenceOpen: true,
        }),
      closeEvidence: () => persist({ ...state, evidenceOpen: false }),
      setVaultBanner: (vaultBanner) => persist({ ...state, vaultBanner }),
      openVaultPreview: (vaultPreviewPath) => persist({ ...state, vaultPreviewPath }),
      closeVaultPreview: () => persist({ ...state, vaultPreviewPath: null }),
    }),
    [persist, state],
  );

  return (
    <RealAiContext.Provider value={value}>{children}</RealAiContext.Provider>
  );
}

export function useRealAi() {
  const ctx = useContext(RealAiContext);
  if (!ctx) {
    throw new Error("useRealAi must be used within RealAiProvider");
  }
  return ctx;
}
