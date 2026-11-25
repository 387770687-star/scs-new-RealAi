"use client";

import { DownloadIcon, ExternalLinkIcon, EyeIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { downloadVaultFile } from "@/core/realai/api";
import { useRealAi } from "@/core/realai/store";
import type { EvidenceItem, EvidenceType } from "@/core/realai/types";
import { toast } from "sonner";

const SECTION_ORDER: EvidenceType[] = ["kb", "data", "web", "viz", "inference"];

const SECTION_LABEL: Record<EvidenceType, string> = {
  kb: "知识库依据",
  data: "问数依据",
  web: "联网依据",
  viz: "视觉依据",
  inference: "模型推测",
};

function isWebUrl(source: string) {
  return /^https?:\/\//i.test(source);
}

function vaultPathFromKb(item: EvidenceItem): string | null {
  if (item.type !== "kb") return null;
  const src = item.source.trim();
  if (!src || isWebUrl(src)) return null;
  return src;
}

function EvidenceSection({
  title,
  items,
  onPreviewVault,
}: {
  title: string;
  items: EvidenceItem[];
  onPreviewVault: (path: string) => void;
}) {
  if (!items.length) return null;
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      <ul className="space-y-3">
        {items.map((item) => {
          const vaultPath = vaultPathFromKb(item);
          const webUrl = item.type === "web" && isWebUrl(item.source) ? item.source : null;
          return (
            <li key={item.id} className="rounded-md border p-3 text-sm">
              <div className="text-muted-foreground mb-1 text-xs">{item.id}</div>
              <div className="font-medium break-all">{item.source}</div>
              <p className="mt-1 whitespace-pre-wrap">{item.excerpt}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {vaultPath && (
                  <>
                    <Button size="sm" variant="secondary" onClick={() => onPreviewVault(vaultPath)}>
                      <EyeIcon className="size-3.5" /> 预览文件
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        void downloadVaultFile(vaultPath).catch((err) =>
                          toast.error(err instanceof Error ? err.message : "下载失败"),
                        )
                      }
                    >
                      <DownloadIcon className="size-3.5" /> 下载
                    </Button>
                  </>
                )}
                {webUrl && (
                  <Button size="sm" variant="outline" asChild>
                    <a href={webUrl} target="_blank" rel="noopener noreferrer">
                      <ExternalLinkIcon className="size-3.5" /> 打开链接
                    </a>
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function RealAiEvidenceDrawer() {
  const { evidenceOpen, lastEvidence, closeEvidence, openVaultPreview } = useRealAi();
  const items = lastEvidence?.items ?? [];

  return (
    <Sheet open={evidenceOpen} onOpenChange={(open) => !open && closeEvidence()}>
      <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle>循证依据</SheetTitle>
          <SheetDescription>知识库 → 联网 → 推测；知识库条目可预览/下载原文</SheetDescription>
        </SheetHeader>
        <div className="mt-4 space-y-6">
          {SECTION_ORDER.map((type) => (
            <EvidenceSection
              key={type}
              title={SECTION_LABEL[type]}
              items={items.filter((i) => i.type === type)}
              onPreviewVault={(path) => {
                openVaultPreview(path);
              }}
            />
          ))}
          {!items.length && (
            <p className="text-muted-foreground text-sm">暂无证据条目。轻量问答或生成报告后会显示在这里。</p>
          )}
        </div>
        <div className="mt-6">
          <Button variant="outline" size="sm" onClick={closeEvidence}>
            <XIcon className="size-4" /> 关闭
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
