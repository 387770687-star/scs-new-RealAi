"use client";

import { ArrowRightIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { fetchSkillsWorkshop } from "@/core/realai/api";
import { useQuery } from "@tanstack/react-query";

export function RealAiSkillsPanel() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["realai", "skills", "workshop"],
    queryFn: fetchSkillsWorkshop,
    refetchInterval: 120_000,
    retry: 1,
  });

  const skills = (data?.skills ?? []).slice(0, 5);

  return (
    <div className="border-t px-3 py-3 text-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 font-medium">
          <SparklesIcon className="size-4" /> Skill
        </span>
        <Button size="sm" variant="outline" asChild>
          <Link href="/workspace/realai/skills">
            工坊
            <ArrowRightIcon className="size-3.5" />
          </Link>
        </Button>
      </div>
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
        <ul className="max-h-36 space-y-1 overflow-y-auto text-xs">
          {skills.map((s) => (
            <li key={`${s.source ?? "skill"}-${s.id}`} className="truncate">
              <span className="font-medium">{s.name || s.id}</span>
              <span className="text-muted-foreground ml-1">
                {s.enabled === false ? "（停）" : ""}
                {s.source === "deerflow" ? " · DF" : ""}
              </span>
            </li>
          ))}
          {(data?.count ?? 0) > 5 && (
            <li className="text-muted-foreground">还有 {(data?.count ?? 0) - 5} 个…</li>
          )}
          {skills.length === 0 && (
            <li className="text-muted-foreground">暂无 Skill，请打开工坊</li>
          )}
        </ul>
      )}
    </div>
  );
}
