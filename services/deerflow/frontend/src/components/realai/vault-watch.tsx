"use client";

import { useEffect, useRef } from "react";

import { fetchVaultStatus } from "@/core/realai/api";
import { useRealAi } from "@/core/realai/store";

/** Poll Vault mtime; show banner when external/Obsidian edits detected. */
export function RealAiVaultWatch() {
  const { setVaultBanner } = useRealAi();
  const lastMtime = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await fetchVaultStatus();
        if (cancelled) return;
        if (lastMtime.current != null && status.vault_mtime > lastMtime.current) {
          setVaultBanner("知识库已更新（Obsidian/外部修改）");
        }
        lastMtime.current = status.vault_mtime;
      } catch {
        /* gateway offline */
      }
    };
    void tick();
    const id = window.setInterval(tick, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [setVaultBanner]);

  return null;
}
