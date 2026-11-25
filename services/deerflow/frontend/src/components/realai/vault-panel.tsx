"use client";

import { FileUpIcon, FolderOpenIcon, Loader2Icon, SearchIcon } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchVaultFiles, importVaultFile } from "@/core/realai/api";
import { useRealAi } from "@/core/realai/store";
import { cn } from "@/lib/utils";
import { useQuery, useQueryClient } from "@tanstack/react-query";

const PAGE_SIZE = 50;

export function RealAiVaultPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const { setVaultBanner, openVaultPreview } = useRealAi();
  const qc = useQueryClient();

  const debounceRef = useRef<number | null>(null);
  const onSearchChange = (value: string) => {
    setSearch(value);
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setDebouncedQ(value);
      setOffset(0);
    }, 300);
  };

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["realai", "vault", "files", offset, debouncedQ],
    queryFn: () => fetchVaultFiles(PAGE_SIZE, offset, debouncedQ),
    refetchInterval: 30_000,
    retry: 1,
  });

  const files = data?.files ?? [];
  const total = data?.total ?? 0;
  const hasMore = offset + files.length < total;

  const onImport = useCallback(
    async (fileList: FileList | null) => {
      if (!fileList?.length) return;
      setUploading(true);
      setStatusText("解析中…");
      try {
        for (const file of Array.from(fileList)) {
          const result = await importVaultFile(file);
          toast.success(result.message || "导入成功");
        }
        setStatusText("成功");
        setOffset(0);
        await refetch();
        setVaultBanner("知识库已更新");
        void qc.invalidateQueries({ queryKey: ["realai", "vault"] });
      } catch (err) {
        setStatusText("失败");
        toast.error(err instanceof Error ? err.message : "导入失败");
      } finally {
        setUploading(false);
        if (inputRef.current) inputRef.current.value = "";
        window.setTimeout(() => setStatusText(null), 3000);
      }
    },
    [qc, refetch, setVaultBanner],
  );

  return (
    <div
      className={cn(
        "border-t px-3 py-3 text-sm transition-colors",
        dragOver && "bg-primary/10",
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        void onImport(e.dataTransfer.files);
      }}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-medium flex items-center gap-1">
          <FolderOpenIcon className="size-4" /> 知识库
          {total > 0 && (
            <span className="text-muted-foreground text-xs font-normal">({total})</span>
          )}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
        >
          {uploading ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <FileUpIcon className="size-4" />
          )}
          导入
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => void onImport(e.target.files)}
        />
      </div>
      <div className="relative mb-2">
        <SearchIcon className="text-muted-foreground absolute top-2 left-2 size-3.5" />
        <Input
          className="h-8 pl-7 text-xs"
          placeholder="搜索文件名…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      {statusText && (
        <p className="text-muted-foreground mb-1 text-xs">导入状态：{statusText}</p>
      )}
      <p className="text-muted-foreground mb-1 text-xs">拖拽导入 · 点击文件名预览/下载</p>
      {isLoading ? (
        <p className="text-muted-foreground text-xs">加载中…</p>
      ) : isError ? (
        <div className="space-y-1 text-xs">
          <p className="text-destructive">
            加载失败：{error instanceof Error ? error.message : "请确认后端已启动"}
          </p>
          <Button size="sm" variant="outline" className="h-7" onClick={() => void refetch()}>
            重试
          </Button>
        </div>
      ) : (
        <>
          <ul className="max-h-48 space-y-1 overflow-y-auto text-xs">
            {files.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  className="hover:text-primary w-full truncate text-left text-muted-foreground underline-offset-2 hover:underline"
                  title={`${f.path} · 点击预览`}
                  onClick={() => openVaultPreview(f.path)}
                >
                  {f.path}
                </button>
              </li>
            ))}
            {files.length === 0 && (
              <li className="text-muted-foreground">暂无文件，请导入或放入 vault/</li>
            )}
          </ul>
          {(hasMore || offset > 0) && (
            <div className="mt-2 flex gap-2">
              {offset > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  disabled={isFetching}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  上一页
                </Button>
              )}
              {hasMore && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  disabled={isFetching}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  {isFetching ? "加载中…" : `下一页 (${offset + files.length}/${total})`}
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
