"use client";

import { DownloadIcon, Loader2Icon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  downloadVaultFile,
  fetchVaultFileBlob,
  fetchVaultFilePreview,
} from "@/core/realai/api";
import type { VaultFilePreview } from "@/core/realai/types";
import { useRealAi } from "@/core/realai/store";

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function VaultFilePreviewDialog() {
  const { vaultPreviewPath, closeVaultPreview } = useRealAi();
  const [preview, setPreview] = useState<VaultFilePreview | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (path: string) => {
    setBusy(true);
    setPreview(null);
    setImageUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    try {
      const data = await fetchVaultFilePreview(path);
      setPreview(data);
      if (data.preview_mode === "image") {
        const blob = await fetchVaultFileBlob(path);
        setImageUrl(URL.createObjectURL(blob));
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "无法打开文件");
      closeVaultPreview();
    } finally {
      setBusy(false);
    }
  }, [closeVaultPreview]);

  useEffect(() => {
    if (vaultPreviewPath) {
      void load(vaultPreviewPath);
    } else {
      setPreview(null);
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
        setImageUrl(null);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when path changes only
  }, [vaultPreviewPath]);

  useEffect(
    () => () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    },
    [imageUrl],
  );

  const onDownload = useCallback(async () => {
    if (!preview) return;
    setBusy(true);
    try {
      await downloadVaultFile(preview.path, preview.name);
      toast.success("已开始下载");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "下载失败");
    } finally {
      setBusy(false);
    }
  }, [preview]);

  return (
    <Dialog open={!!vaultPreviewPath} onOpenChange={(open) => !open && closeVaultPreview()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{preview?.name || vaultPreviewPath}</DialogTitle>
          <DialogDescription className="truncate">
            {preview
              ? `${preview.path} · ${formatSize(preview.size)} · ${new Date(preview.mtime * 1000).toLocaleString()}`
              : "加载中…"}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {busy && !preview && (
            <div className="text-muted-foreground flex items-center gap-2 py-8 text-sm">
              <Loader2Icon className="size-4 animate-spin" /> 加载预览…
            </div>
          )}
          {preview?.preview_mode === "text" && (
            <pre className="bg-muted max-h-[50vh] overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
              {preview.content}
              {preview.truncated && (
                <span className="text-muted-foreground block mt-2">（内容已截断，请下载查看完整文件）</span>
              )}
            </pre>
          )}
          {preview?.preview_mode === "image" && imageUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageUrl} alt={preview.name} className="mx-auto max-h-[50vh] rounded-md object-contain" />
          )}
          {preview?.preview_mode === "download_only" && (
            <p className="text-muted-foreground text-sm">{preview.message || "此格式不支持在线预览，请下载查看。"}</p>
          )}
        </div>

        <div className="flex flex-wrap gap-2 pt-2">
          <Button size="sm" disabled={!preview || busy} onClick={() => void onDownload()}>
            {busy ? <Loader2Icon className="size-4 animate-spin" /> : <DownloadIcon className="size-4" />}
            下载
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
