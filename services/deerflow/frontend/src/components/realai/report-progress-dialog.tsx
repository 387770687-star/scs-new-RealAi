"use client";

import {
  CheckCircle2Icon,
  CircleDashedIcon,
  Loader2Icon,
  MinusCircleIcon,
  XCircleIcon,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AgentProgressStep } from "@/core/realai/types";
import { cn } from "@/lib/utils";

const STATUS_ICON = {
  pending: CircleDashedIcon,
  running: Loader2Icon,
  completed: CheckCircle2Icon,
  skipped: MinusCircleIcon,
  failed: XCircleIcon,
} as const;

export function ReportProgressDialog({
  open,
  goal,
  steps,
  phase,
  onOpenChange,
}: {
  open: boolean;
  goal: string;
  steps: AgentProgressStep[];
  phase?: string;
  onOpenChange: (open: boolean) => void;
}) {
  const done = steps.filter((s) => s.status === "completed" || s.status === "skipped").length;
  const total = steps.length || 8;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>报告生成进度</DialogTitle>
          <DialogDescription className="line-clamp-2">{goal}</DialogDescription>
        </DialogHeader>
        <div className="text-muted-foreground mb-3 text-xs">
          {phase === "await_outline_confirm"
            ? "大纲已生成，等待确认后继续写作"
            : `子 Agent ${done}/${total}`}
        </div>
        <ul className="max-h-72 space-y-2 overflow-y-auto text-sm">
          {steps.map((step) => {
            const Icon = STATUS_ICON[step.status] ?? CircleDashedIcon;
            return (
              <li
                key={step.id}
                className={cn(
                  "flex items-start gap-2 rounded-md border px-2 py-1.5",
                  step.status === "running" && "border-primary/40 bg-primary/5",
                  step.status === "failed" && "border-destructive/40",
                )}
              >
                <Icon
                  className={cn(
                    "mt-0.5 size-4 shrink-0",
                    step.status === "running" && "animate-spin text-primary",
                    step.status === "completed" && "text-green-600",
                    step.status === "skipped" && "text-muted-foreground",
                    step.status === "failed" && "text-destructive",
                  )}
                />
                <div className="min-w-0">
                  <div className="font-medium">{step.label}</div>
                  {step.message && (
                    <div className="text-muted-foreground text-xs">{step.message}</div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
